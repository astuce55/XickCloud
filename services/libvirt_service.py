# services/libvirt_service.py - VERSION SIMPLE AVEC LEASE (qui fonctionne)
import libvirt
import sys
import time
import socket
from typing import Dict, List, Optional
from config_logging import libvirt_logger as logger

class LibvirtService:
    
    @staticmethod
    def get_connection(uri: str = 'qemu:///system', timeout: int = 5):
        """Connexion libvirt simple"""
        try:
            if uri.startswith('qemu+ssh://'):
                parts = uri.split('@')
                if len(parts) >= 2:
                    hostname = parts[1].split('/')[0].split(':')[0]
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(timeout)
                    result = sock.connect_ex((hostname, 22))
                    sock.close()
                    if result != 0:
                        return None
            
            conn = libvirt.open(uri)
            return conn
        except Exception as e:
            logger.error(f"Erreur connexion {uri}: {e}")
            return None
    
    @staticmethod
    def get_vm_ip_via_lease(domain_name: str, host_uri: str, timeout: int = 60) -> Optional[str]:
        """
        Récupère l'IP via LEASE - la méthode qui fonctionne dans ton app.py
        """
        logger.info(f"Récupération IP via lease pour {domain_name}")
        
        conn = LibvirtService.get_connection(host_uri)
        if not conn:
            return None
        
        try:
            dom = conn.lookupByName(domain_name)
            
            if dom.isActive() != 1:
                logger.warning(f"VM {domain_name} pas active")
                return None
            
            start_time = time.time()
            
            # Essayer plusieurs fois
            while time.time() - start_time < timeout:
                try:
                    # Méthode LEASE - comme dans ton app.py
                    ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
                    
                    for iface_name, iface_info in ifaces.items():
                        if iface_info and 'addrs' in iface_info and iface_info['addrs']:
                            for addr in iface_info['addrs']:
                                if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                                    ip = addr['addr']
                                    logger.info(f"✓ IP trouvée via lease: {ip}")
                                    return ip
                    
                    # Pas encore d'IP, attendre
                    time.sleep(5)
                    
                except libvirt.libvirtError as e:
                    logger.debug(f"Lease pas encore prêt: {e}")
                    time.sleep(5)
            
            logger.warning(f"Pas d'IP après {timeout}s")
            return None
            
        except Exception as e:
            logger.error(f"Erreur: {e}")
            return None
        finally:
            if conn:
                conn.close()
    
    @staticmethod
    def wait_for_vm_ip(domain_name: str, host_uri: str, timeout: int = 120) -> Optional[str]:
        """Attend l'IP - simple"""
        return LibvirtService.get_vm_ip_via_lease(domain_name, host_uri, timeout)
    
    @staticmethod
    def get_all_domains(uri: str, timeout: int = 15) -> List[Dict]:
        """Récupère toutes les VMs"""
        domains = []
        conn = LibvirtService.get_connection(uri, timeout=5)
        
        if not conn:
            return []
        
        try:
            all_domains = conn.listAllDomains(
                libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE | 
                libvirt.VIR_CONNECT_LIST_DOMAINS_INACTIVE
            )
            
            for dom in all_domains:
                try:
                    domain_info = LibvirtService.get_domain_info(conn, dom.name())
                    if domain_info:
                        domains.append(domain_info)
                except:
                    continue
                    
        except Exception as e:
            logger.error(f"Erreur récupération VMs: {e}")
        finally:
            if conn:
                conn.close()
        
        return domains
    
    @staticmethod
    def get_domain_info(conn, domain_name: str) -> Optional[Dict]:
        """Info d'une VM - comme dans ton app.py"""
        try:
            dom = conn.lookupByName(domain_name)
            info = dom.info()
            
            state = info[0]
            status_text = "Shutoff"
            if state == libvirt.VIR_DOMAIN_RUNNING:
                status_text = "Running"
            elif state == libvirt.VIR_DOMAIN_PAUSED:
                status_text = "Paused"
            
            ip_addr = "En attente..."
            
            # Essayer de récupérer l'IP rapidement
            if state == libvirt.VIR_DOMAIN_RUNNING:
                try:
                    ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
                    for _, val in ifaces.items():
                        if val and 'addrs' in val and val['addrs']:
                            for addr in val['addrs']:
                                if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                                    ip_addr = addr['addr']
                                    break
                except:
                    pass
            
            return {
                'name': domain_name,
                'status': status_text,
                'ip': ip_addr,
                'vcpu': info[3],
                'max_mem': info[1] / 1024,
                'used_mem': info[2] / 1024,
                'domain': dom
            }
            
        except Exception as e:
            logger.debug(f"Erreur info VM {domain_name}: {e}")
            return None
    
    @staticmethod
    def get_host_usage(uri: str) -> Optional[Dict]:
        """Usage hôte"""
        conn = LibvirtService.get_connection(uri, timeout=5)
        if not conn:
            return None
        
        try:
            nodeinfo = conn.getInfo()
            total_memory = nodeinfo[1]
            total_cpus = nodeinfo[2]
            
            all_domains = conn.listAllDomains(
                libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE | 
                libvirt.VIR_CONNECT_LIST_DOMAINS_INACTIVE
            )
            
            used_vcpu = 0
            used_ram = 0
            
            for dom in all_domains:
                try:
                    info = dom.info()
                    if info[0] == 1:  # Running
                        used_vcpu += info[3]
                        used_ram += info[2] / 1024
                except:
                    continue
            
            return {
                'total_vcpu': total_cpus,
                'used_vcpu': used_vcpu,
                'available_vcpu': total_cpus - used_vcpu,
                'total_ram': total_memory,
                'used_ram': used_ram,
                'available_ram': total_memory - used_ram,
                'available_disk': 500
            }
            
        except Exception as e:
            logger.error(f"Erreur usage: {e}")
            return None
        finally:
            if conn:
                conn.close()
    
    @staticmethod
    def control_domain(uri: str, domain_name: str, action: str) -> bool:
        """Contrôle VM"""
        conn = LibvirtService.get_connection(uri, timeout=5)
        if not conn:
            return False
        
        try:
            dom = conn.lookupByName(domain_name)
            
            if action == 'start':
                if dom.isActive() == 0:
                    dom.create()
                    return True
            elif action == 'stop':
                if dom.isActive() == 1:
                    dom.destroy()
                    return True
            elif action == 'restart':
                if dom.isActive() == 1:
                    dom.destroy()
                    time.sleep(2)
                dom.create()
                return True
            elif action == 'delete':
                if dom.isActive() == 1:
                    dom.destroy()
                dom.undefine()
                return True
            
            return False
        except Exception as e:
            logger.error(f"Erreur {action}: {e}")
            return False
        finally:
            if conn:
                conn.close()
    
    @staticmethod
    def get_domain_host_uri(domain_name: str, hosts_to_check: List[str]) -> Optional[str]:
        """Cherche l'hôte d'une VM"""
        for uri in hosts_to_check:
            try:
                conn = LibvirtService.get_connection(uri, timeout=3)
                if not conn:
                    continue
                
                try:
                    dom = conn.lookupByName(domain_name)
                    if dom:
                        conn.close()
                        return uri
                except:
                    pass
                finally:
                    if conn:
                        conn.close()
            except:
                continue
        
        return None
    
    @staticmethod
    def update_vm_ip_in_background(vm_name: str, host_uri: str):
        """Récupération IP en arrière-plan"""
        import threading
        
        def background_task():
            try:
                # Attendre un peu
                time.sleep(10)
                
                logger.info(f"Récupération IP pour {vm_name}")
                ip = LibvirtService.wait_for_vm_ip(vm_name, host_uri, timeout=120)
                
                if ip:
                    from models.vm import VMManager
                    vm_manager = VMManager()
                    vm_manager.update_vm_metadata(vm_name, {
                        'ip_address': ip, 
                        'status': 'ready'
                    })
                    logger.info(f"✓ IP mise à jour: {ip}")
                else:
                    logger.warning(f"IP non disponible pour {vm_name}")
                    
            except Exception as e:
                logger.error(f"Erreur récupération IP: {e}")
        
        thread = threading.Thread(target=background_task)
        thread.daemon = True
        thread.start()