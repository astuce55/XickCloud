# services/libvirt_service.py - CODE COMPLET CORRIGÉ
import libvirt
import sys
import time
from typing import Dict, List, Optional, Any

class LibvirtService:
    def __init__(self):
        pass
    
    @staticmethod
    def get_connection(uri: str = 'qemu:///system', timeout: int = 5):
        """Établit une connexion à libvirt avec timeout"""
        try:
            print(f"🔗 Tentative de connexion à: {uri} (timeout: {timeout}s)")
            
            # Configurer le timeout pour les connexions SSH
            if uri.startswith('qemu+ssh://'):
                # Vérifier d'abord si l'hôte SSH est accessible
                try:
                    # Extraire hostname de l'URI
                    parts = uri.split('@')
                    if len(parts) >= 2:
                        hostname = parts[1].split('/')[0].split(':')[0]
                        
                        # Test de connectivité TCP sur le port 22
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(timeout)
                        result = sock.connect_ex((hostname, 22))
                        sock.close()
                        
                        if result != 0:
                            print(f"❌ Hôte SSH {hostname}:22 inaccessible, skip")
                            return None
                except Exception as e:
                    print(f"⚠️  Test connectivité SSH échoué: {e}")
            
            # Tentative de connexion avec timeout
            start_time = time.time()
            
            # Essayer plusieurs fois avec délai
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    conn = libvirt.open(uri)
                    if conn:
                        elapsed = time.time() - start_time
                        print(f"✅ Connexion réussie à: {uri} (temps: {elapsed:.2f}s)")
                        return conn
                    else:
                        print(f"⚠️  Connexion refusée à: {uri} (tentative {attempt+1}/{max_retries})")
                        
                except libvirt.libvirtError as e:
                    error_msg = str(e)
                    elapsed = time.time() - start_time
                    
                    # Vérifier les erreurs spécifiques
                    if 'connection refused' in error_msg.lower():
                        print(f"❌ Connexion refusée à: {uri}")
                        return None
                    elif 'authentication failed' in error_msg.lower():
                        print(f"❌ Échec authentification à: {uri}")
                        return None
                    elif 'no route to host' in error_msg.lower():
                        print(f"❌ Hôte inaccessible: {uri}")
                        return None
                    elif 'timed out' in error_msg.lower():
                        print(f"⏱️  Timeout connexion à: {uri} (tentative {attempt+1}/{max_retries})")
                        if attempt < max_retries - 1:
                            time.sleep(1)  # Attendre avant réessai
                            continue
                        else:
                            print(f"❌ Échec après {max_retries} tentatives: {uri}")
                            return None
                    else:
                        print(f"⚠️  Erreur libvirt [{uri}]: {error_msg}")
                        if attempt < max_retries - 1:
                            time.sleep(1)
                            continue
                        else:
                            return None
                            
                except Exception as e:
                    print(f"❌ ERREUR GÉNÉRALE [{uri}]: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    else:
                        return None
            
            return None
            
        except Exception as e:
            print(f"❌ ERREUR CRITIQUE [{uri}]: {e}", file=sys.stderr)
            return None
    
    @staticmethod
    def get_all_domains(uri: str = 'qemu:///system', timeout: int = 10) -> List[Dict]:
        """Récupère toutes les VMs d'un hôte avec timeout"""
        print(f"🔍 Recherche VMs sur: {uri} (timeout: {timeout}s)")
        
        start_time = time.time()
        conn = LibvirtService.get_connection(uri, timeout=3)
        
        if not conn:
            elapsed = time.time() - start_time
            print(f"❌ Impossible de se connecter à {uri} (temps: {elapsed:.2f}s)")
            return []
        
        domains = []
        try:
            elapsed_connect = time.time() - start_time
            remaining_time = timeout - elapsed_connect
            
            if remaining_time <= 0:
                print(f"⏱️  Timeout avant récupération VMs")
                return []
            
            print(f"📋 Tentative de liste des domaines (temps restant: {remaining_time:.1f}s)...")
            
            # Méthode principale
            try:
                all_domains = conn.listAllDomains(libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE | 
                                                 libvirt.VIR_CONNECT_LIST_DOMAINS_INACTIVE)
                print(f"   ✅ listAllDomains: {len(all_domains)} domaines trouvés")
                
                for dom in all_domains:
                    try:
                        if time.time() - start_time > timeout:
                            print(f"⏱️  Timeout pendant le traitement des VMs")
                            break
                            
                        domain_info = LibvirtService.get_domain_info(conn, dom.name())
                        if domain_info:
                            domains.append(domain_info)
                    except Exception as e:
                        print(f"   ⚠️  Erreur domaine {dom.name()}: {e}")
                        continue
                        
            except Exception as e:
                print(f"   ⚠️  listAllDomains échoué: {e}")
                
                # Méthode alternative
                try:
                    defined_domains = conn.listDefinedDomains()
                    print(f"   ✅ listDefinedDomains: {len(defined_domains)} domaines définis")
                    
                    active_ids = conn.listDomainsID()
                    print(f"   ✅ listDomainsID: {len(active_ids)} domaines actifs")
                    
                    for domain_name in defined_domains:
                        try:
                            if time.time() - start_time > timeout:
                                print(f"⏱️  Timeout pendant le traitement des VMs")
                                break
                                
                            domain_info = LibvirtService.get_domain_info(conn, domain_name)
                            if domain_info:
                                domains.append(domain_info)
                        except Exception as e:
                            print(f"   ⚠️  Erreur domaine {domain_name}: {e}")
                            continue
                            
                except Exception as e2:
                    print(f"   ❌ Toutes les méthodes ont échoué: {e2}")
            
            elapsed_total = time.time() - start_time
            print(f"📊 Total VMs récupérées: {len(domains)} (temps total: {elapsed_total:.2f}s)")
            
            if domains:
                for domain in domains:
                    print(f"   - {domain['name']} ({domain['status']}) IP: {domain.get('ip', 'N/A')}")
            else:
                print(f"   ℹ️  Aucune VM trouvée sur cet hôte")
                
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"❌ Erreur récupération VMs: {e} (temps: {elapsed:.2f}s)", file=sys.stderr)
        finally:
            if conn:
                conn.close()
                print(f"🔒 Connexion fermée: {uri}")
        
        return domains
    
    @staticmethod
    def get_domain_info(conn, domain_name: str) -> Optional[Dict]:
        """Récupère les informations d'une VM"""
        try:
            dom = conn.lookupByName(domain_name)
            info = dom.info()
            
            # État de la VM
            state = info[0]
            maxmem = info[1]  # en KiB
            mem = info[2]     # en KiB
            ncpu = info[3]
            cputime = info[4]
            
            status_text = "Unknown"
            if state == 0:  # no state
                status_text = "No State"
            elif state == 1:  # running
                status_text = "Running"
            elif state == 2:  # blocked
                status_text = "Blocked"
            elif state == 3:  # paused
                status_text = "Paused"
            elif state == 4:  # shutdown
                status_text = "Shutdown"
            elif state == 5:  # shut off
                status_text = "Shutoff"
            elif state == 6:  # crashed
                status_text = "Crashed"
            elif state == 7:  # suspended
                status_text = "Suspended"
            
            # Récupérer l'adresse IP
            ip_addr = "N/A"
            if state == 1:  # Running
                try:
                    ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
                    if ifaces:
                        for _, val in ifaces.items():
                            if 'addrs' in val and val['addrs']:
                                for addr in val['addrs']:
                                    if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                                        ip_addr = addr['addr']
                                        break
                except Exception as e:
                    print(f"   ⚠️  Impossible de récupérer IP pour {domain_name}: {e}")
            
            # Convertir la mémoire de KiB en MiB
            maxmem_mb = maxmem / 1024
            used_mem_mb = mem / 1024
            
            return {
                'name': domain_name,
                'status': status_text,
                'ip': ip_addr,
                'cpu_time': cputime,
                'vcpu': ncpu,
                'max_mem': maxmem_mb,
                'used_mem': used_mem_mb,
                'domain': dom
            }
            
        except Exception as e:
            print(f"   ⚠️  Erreur récupération info {domain_name}: {e}")
            return None
    
    @staticmethod
    def get_host_capabilities(uri: str) -> Optional[Dict]:
        """Récupère les capacités de l'hôte"""
        conn = LibvirtService.get_connection(uri)
        if not conn:
            return None
        
        try:
            nodeinfo = conn.getInfo()
            
            return {
                'model': nodeinfo[0],
                'total_memory': nodeinfo[1],  # MiB
                'total_cpus': nodeinfo[2],
                'mhz': nodeinfo[3],
                'nodes': nodeinfo[4],
                'sockets': nodeinfo[5],
                'cores': nodeinfo[6],
                'threads': nodeinfo[7]
            }
        except Exception as e:
            print(f"❌ Erreur récupération capacités: {e}", file=sys.stderr)
            return None
        finally:
            if conn:
                conn.close()
    
    @staticmethod
    def control_domain(uri: str, domain_name: str, action: str) -> bool:
        """Contrôle une VM (start/stop/delete)"""
        conn = LibvirtService.get_connection(uri)
        if not conn:
            return False
        
        try:
            dom = conn.lookupByName(domain_name)
            
            if action == 'start':
                if dom.isActive() == 0:  # Not active
                    dom.create()
                    print(f"✅ VM {domain_name} démarrée")
                    return True
                else:
                    print(f"⚠️ VM {domain_name} déjà en cours d'exécution")
                    return False
                    
            elif action == 'stop':
                if dom.isActive() == 1:  # Active
                    dom.destroy()
                    print(f"✅ VM {domain_name} arrêtée")
                    return True
                else:
                    print(f"⚠️ VM {domain_name} déjà arrêtée")
                    return False
                    
            elif action == 'delete':
                if dom.isActive() == 1:  # Active
                    dom.destroy()
                dom.undefine()
                print(f"✅ VM {domain_name} supprimée")
                return True
            
            return False
        except Exception as e:
            print(f"❌ Erreur contrôle VM {domain_name}: {e}", file=sys.stderr)
            return False
        finally:
            if conn:
                conn.close()