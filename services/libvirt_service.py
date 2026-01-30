# services/libvirt_service.py - VERSION CORRIGÉE AVEC RÉCUPÉRATION IP
import libvirt
import sys
import time
import socket
from typing import Dict, List, Optional, Any
from config_logging import libvirt_logger as logger

class LibvirtService:
    def __init__(self):
        pass
    
    @staticmethod
    def get_connection(uri: str = 'qemu:///system', timeout: int = 5):
        """Établit une connexion à libvirt avec timeout"""
        try:
            logger.debug(f"Tentative connexion: {uri} (timeout: {timeout}s)")
            
            # Test connectivité SSH si nécessaire
            if uri.startswith('qemu+ssh://'):
                try:
                    parts = uri.split('@')
                    if len(parts) >= 2:
                        hostname = parts[1].split('/')[0].split(':')[0]
                        
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(timeout)
                        result = sock.connect_ex((hostname, 22))
                        sock.close()
                        
                        if result != 0:
                            logger.warning(f"SSH inaccessible: {hostname}:22")
                            return None
                except Exception as e:
                    logger.debug(f"Test SSH échoué: {e}")
            
            # Connexion avec retry
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    conn = libvirt.open(uri)
                    if conn:
                        logger.debug(f"Connexion OK: {uri}")
                        return conn
                        
                except libvirt.libvirtError as e:
                    error_msg = str(e).lower()
                    
                    if any(x in error_msg for x in ['connection refused', 'authentication failed', 'no route to host']):
                        logger.warning(f"Connexion échouée: {uri} - {e}")
                        return None
                    elif 'timed out' in error_msg:
                        if attempt < max_retries - 1:
                            time.sleep(1)
                            continue
                        else:
                            logger.warning(f"Timeout connexion: {uri}")
                            return None
                    else:
                        if attempt < max_retries - 1:
                            time.sleep(1)
                            continue
                        else:
                            logger.error(f"Erreur libvirt: {uri} - {e}")
                            return None
                            
                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    else:
                        logger.error(f"Erreur connexion: {uri} - {e}")
                        return None
            
            return None
            
        except Exception as e:
            logger.error(f"Erreur critique: {uri} - {e}", exc_info=True)
            return None
    
    @staticmethod
    def get_vm_ip_address(domain_name: str, host_uri: str, timeout: int = 60) -> Optional[str]:
        """
        Récupère l'adresse IP d'une VM depuis le DHCP de libvirt
        
        Args:
            domain_name: Nom de la VM
            host_uri: URI de l'hôte KVM
            timeout: Temps d'attente maximum (secondes)
        
        Returns:
            L'adresse IP ou None si non trouvée
        """
        logger.info(f"Récupération IP pour {domain_name} (timeout: {timeout}s)")
        
        conn = LibvirtService.get_connection(host_uri, timeout=10)
        if not conn:
            logger.error(f"Impossible de se connecter à {host_uri}")
            return None
        
        try:
            dom = conn.lookupByName(domain_name)
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                try:
                    # Vérifier que la VM est démarrée
                    if dom.isActive() != 1:
                        logger.debug(f"{domain_name} n'est pas encore active")
                        time.sleep(3)
                        continue
                    
                    # Méthode 1: Via les leases DHCP (plus fiable)
                    try:
                        ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
                        
                        for name, val in ifaces.items():
                            addrs = val.get('addrs', [])
                            for addr in addrs:
                                if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                                    ip = addr['addr']
                                    # Éviter l'IP loopback
                                    if not ip.startswith('127.'):
                                        logger.info(f"✓ IP trouvée (LEASE) pour {domain_name}: {ip}")
                                        return ip
                    except Exception as e:
                        logger.debug(f"LEASE method failed: {e}")
                    
                    # Méthode 2: Via QEMU Guest Agent (fallback)
                    try:
                        ifaces_agent = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT)
                        
                        for name, val in ifaces_agent.items():
                            addrs = val.get('addrs', [])
                            for addr in addrs:
                                if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                                    ip = addr['addr']
                                    if not ip.startswith('127.'):
                                        logger.info(f"✓ IP trouvée (AGENT) pour {domain_name}: {ip}")
                                        return ip
                    except Exception as e:
                        logger.debug(f"AGENT method failed: {e}")
                    
                    logger.debug(f"IP non encore disponible pour {domain_name}, attente...")
                    time.sleep(5)
                    
                except libvirt.libvirtError as e:
                    logger.debug(f"Erreur récupération IP {domain_name}: {e}")
                    time.sleep(3)
            
            logger.warning(f"⚠ Timeout récupération IP pour {domain_name} après {timeout}s")
            return None
            
        except Exception as e:
            logger.error(f"Erreur récupération IP {domain_name}: {e}", exc_info=True)
            return None
        finally:
            if conn:
                conn.close()
    
    @staticmethod
    def get_all_domains(uri: str = 'qemu:///system', timeout: int = 10) -> List[Dict]:
        """Récupère toutes les VMs d'un hôte avec timeout"""
        logger.debug(f"Récupération VMs: {uri}")
        
        start_time = time.time()
        conn = LibvirtService.get_connection(uri, timeout=3)
        
        if not conn:
            logger.warning(f"Connexion impossible: {uri}")
            return []
        
        domains = []
        try:
            elapsed_connect = time.time() - start_time
            remaining_time = timeout - elapsed_connect
            
            if remaining_time <= 0:
                logger.warning(f"Timeout avant récupération VMs: {uri}")
                return []
            
            try:
                all_domains = conn.listAllDomains(
                    libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE | 
                    libvirt.VIR_CONNECT_LIST_DOMAINS_INACTIVE
                )
                logger.debug(f"Trouvé {len(all_domains)} VMs sur {uri}")
                
                for dom in all_domains:
                    try:
                        if time.time() - start_time > timeout:
                            logger.warning(f"Timeout traitement VMs: {uri}")
                            break
                            
                        domain_info = LibvirtService.get_domain_info(conn, dom.name())
                        if domain_info:
                            domains.append(domain_info)
                    except Exception as e:
                        logger.debug(f"Erreur VM {dom.name()}: {e}")
                        continue
                        
            except Exception as e:
                logger.debug(f"listAllDomains échoué, méthode alternative: {e}")
                
                try:
                    defined_domains = conn.listDefinedDomains()
                    
                    for domain_name in defined_domains:
                        try:
                            if time.time() - start_time > timeout:
                                break
                                
                            domain_info = LibvirtService.get_domain_info(conn, domain_name)
                            if domain_info:
                                domains.append(domain_info)
                        except Exception as e:
                            logger.debug(f"Erreur VM {domain_name}: {e}")
                            continue
                            
                except Exception as e2:
                    logger.error(f"Toutes méthodes échouées: {uri} - {e2}")
            
            logger.info(f"Récupéré {len(domains)} VMs depuis {uri}")
                
        except Exception as e:
            logger.error(f"Erreur récupération VMs: {uri} - {e}", exc_info=True)
        finally:
            if conn:
                conn.close()
        
        return domains
    
    @staticmethod
    def get_domain_info(conn, domain_name: str) -> Optional[Dict]:
        """Récupère les informations d'une VM"""
        try:
            dom = conn.lookupByName(domain_name)
            info = dom.info()
            
            status_map = {
                0: "No State", 1: "Running", 2: "Blocked", 3: "Paused",
                4: "Shutdown", 5: "Shutoff", 6: "Crashed", 7: "Suspended"
            }
            
            status_text = status_map.get(info[0], "Unknown")
            
            # IP uniquement si running
            ip_addr = "N/A"
            if info[0] == 1:  # Running
                try:
                    # Essayer LEASE d'abord
                    ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
                    if ifaces:
                        for _, val in ifaces.items():
                            if 'addrs' in val and val['addrs']:
                                for addr in val['addrs']:
                                    if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                                        if not addr['addr'].startswith('127.'):
                                            ip_addr = addr['addr']
                                            break
                except:
                    # Fallback: essayer AGENT
                    try:
                        ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT)
                        if ifaces:
                            for _, val in ifaces.items():
                                if 'addrs' in val and val['addrs']:
                                    for addr in val['addrs']:
                                        if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                                            if not addr['addr'].startswith('127.'):
                                                ip_addr = addr['addr']
                                                break
                    except:
                        pass
            
            return {
                'name': domain_name,
                'status': status_text,
                'ip': ip_addr,
                'cpu_time': info[4],
                'vcpu': info[3],
                'max_mem': info[1] / 1024,  # KiB to MiB
                'used_mem': info[2] / 1024,
                'domain': dom
            }
            
        except Exception as e:
            logger.debug(f"Erreur info VM {domain_name}: {e}")
            return None
    
    @staticmethod
    def get_host_usage(uri: str) -> Optional[Dict]:
        """Récupère l'utilisation des ressources d'un hôte"""
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
            logger.error(f"Erreur usage hôte: {uri} - {e}")
            return None
        finally:
            if conn:
                conn.close()
    
    @staticmethod
    def control_domain(uri: str, domain_name: str, action: str) -> bool:
        """Contrôle une VM (start/stop/delete/restart)"""
        conn = LibvirtService.get_connection(uri, timeout=5)
        if not conn:
            logger.error(f"Impossible de se connecter pour {action} sur {domain_name}")
            return False
        
        try:
            dom = conn.lookupByName(domain_name)
            
            if action == 'start':
                if dom.isActive() == 0:
                    dom.create()
                    logger.info(f"VM démarrée: {domain_name}")
                    return True
                else:
                    logger.warning(f"VM déjà active: {domain_name}")
                    return False
                    
            elif action == 'stop':
                if dom.isActive() == 1:
                    dom.destroy()
                    logger.info(f"VM arrêtée: {domain_name}")
                    return True
                else:
                    logger.warning(f"VM déjà arrêtée: {domain_name}")
                    return False
                    
            elif action == 'restart':
                if dom.isActive() == 1:
                    dom.destroy()
                    time.sleep(2)
                dom.create()
                logger.info(f"VM redémarrée: {domain_name}")
                return True
                    
            elif action == 'delete':
                if dom.isActive() == 1:
                    dom.destroy()
                dom.undefine()
                logger.info(f"VM supprimée: {domain_name}")
                return True
            
            return False
        except libvirt.libvirtError as e:
            logger.error(f"Erreur libvirt {action} sur {domain_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Erreur {action} sur {domain_name}: {e}", exc_info=True)
            return False
        finally:
            if conn:
                conn.close()
    
    @staticmethod
    def get_domain_host_uri(domain_name: str, hosts_to_check: List[str]) -> Optional[str]:
        """
        Cherche sur quel hôte se trouve une VM
        Retourne l'URI de l'hôte si trouvé
        """
        for uri in hosts_to_check:
            try:
                conn = LibvirtService.get_connection(uri, timeout=3)
                if not conn:
                    continue
                
                try:
                    dom = conn.lookupByName(domain_name)
                    if dom:
                        logger.debug(f"VM {domain_name} trouvée sur {uri}")
                        conn.close()
                        return uri
                except libvirt.libvirtError:
                    pass
                finally:
                    if conn:
                        conn.close()
            except:
                continue
        
        logger.warning(f"VM {domain_name} non trouvée sur les hôtes disponibles")
        return None