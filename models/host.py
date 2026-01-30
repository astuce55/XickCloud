# models/host.py - VERSION SANS PRINT
import time
import socket
import queue
import threading
from typing import Dict, List, Optional
from models.storage import StorageManager
from services.libvirt_service import LibvirtService
from config_logging import host_logger as logger

class HostManager:
    def __init__(self):
        self.storage = StorageManager()
        self.libvirt_service = LibvirtService()
    
    def get_all_hosts(self) -> List[Dict]:
        """Récupère tous les hôtes"""
        return self.storage.load_hosts()
    
    def get_enabled_hosts(self) -> List[Dict]:
        """Récupère les hôtes activés"""
        hosts = self.get_all_hosts()
        return [h for h in hosts if h.get('enabled', True)]
    
    def get_host_by_id(self, host_id: str) -> Optional[Dict]:
        """Récupère un hôte par son ID"""
        hosts = self.get_all_hosts()
        for host in hosts:
            if host.get('id') == host_id:
                return host
        return None
    
    def add_host(self, host_data: Dict) -> Dict:
        """Ajoute un nouvel hôte"""
        hosts = self.get_all_hosts()
        
        new_host = {
            'id': host_data.get('id', f"host-{int(time.time())}"),
            'name': host_data.get('name', 'Nouvel hôte'),
            'uri': host_data.get('uri', 'qemu:///system'),
            'enabled': host_data.get('enabled', True),
            'priority': host_data.get('priority', len(hosts) + 1),
            'storage_path': host_data.get('storage_path', '/var/lib/libvirt/images'),
            'quotas': {
                'max_vcpu': host_data.get('max_vcpu', 8),
                'max_ram': host_data.get('max_ram', 16384),
                'max_disk': host_data.get('max_disk', 200)
            },
            'description': host_data.get('description', '')
        }
        
        hosts.append(new_host)
        self.storage.save_hosts(hosts)
        logger.info(f"Hôte ajouté: {new_host['name']}")
        return new_host
    
    def update_host(self, host_id: str, updates: Dict) -> Optional[Dict]:
        """Met à jour un hôte"""
        hosts = self.get_all_hosts()
        
        for i, host in enumerate(hosts):
            if host.get('id') == host_id:
                hosts[i].update(updates)
                self.storage.save_hosts(hosts)
                logger.info(f"Hôte mis à jour: {host_id}")
                return hosts[i]
        
        return None
    
    def delete_host(self, host_id: str) -> bool:
        """Supprime un hôte"""
        hosts = self.get_all_hosts()
        new_hosts = [h for h in hosts if h.get('id') != host_id]
        
        if len(new_hosts) != len(hosts):
            self.storage.save_hosts(new_hosts)
            logger.info(f"Hôte supprimé: {host_id}")
            return True
        
        return False
    
    def get_host_usage(self, host_uri: str) -> Optional[Dict]:
        """Récupère l'utilisation d'un hôte"""
        return self.libvirt_service.get_host_usage(host_uri)
    
    def select_best_host(self, required_vcpu: int, required_ram: int, required_disk: int = 0, 
                        timeout_per_host: int = 5) -> Optional[Dict]:
        """Sélectionne le meilleur hôte avec gestion des timeouts"""
        hosts = self.get_enabled_hosts()
        
        if not hosts:
            logger.error("Aucun hôte activé disponible")
            return None
        
        hosts.sort(key=lambda h: h.get('priority', 999))
        
        logger.info(f"Recherche hôte: {required_vcpu}vCPU, {required_ram}MiB RAM, {required_disk}GB Disk")
        logger.debug(f"Hôtes disponibles: {len(hosts)}")
        
        for i, host in enumerate(hosts):
            logger.debug(f"Test hôte [{i+1}/{len(hosts)}]: {host['name']}")
            
            start_time = time.time()
            try:
                # Test connectivité SSH si nécessaire
                if host['uri'].startswith('qemu+ssh://'):
                    try:
                        parts = host['uri'].split('@')
                        if len(parts) >= 2:
                            hostname = parts[1].split('/')[0].split(':')[0]
                            
                            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(3)
                            result = sock.connect_ex((hostname, 22))
                            sock.close()
                            
                            if result != 0:
                                logger.debug(f"SSH inaccessible: {hostname}:22")
                                continue
                    except Exception as e:
                        logger.debug(f"Test SSH échoué: {e}")
                        continue
                
                # Récupérer usage avec timeout
                usage = self.get_host_usage_with_timeout(host['uri'], timeout=timeout_per_host)
                
                if not usage:
                    logger.debug(f"Impossible de récupérer ressources hôte {host['name']}")
                    continue
                
                # Vérifier ressources
                has_cpu = usage.get('available_vcpu', 0) >= required_vcpu
                has_ram = usage.get('available_ram', 0) >= required_ram
                has_disk = usage.get('available_disk', 0) >= required_disk
                
                if has_cpu and has_ram and has_disk:
                    elapsed = time.time() - start_time
                    logger.info(f"Hôte sélectionné: {host['name']} (temps: {elapsed:.2f}s)")
                    logger.debug(f"Ressources: CPU {usage.get('available_vcpu')}/{required_vcpu}, " +
                               f"RAM {usage.get('available_ram')}/{required_ram}, " +
                               f"Disk {usage.get('available_disk')}/{required_disk}")
                    return host
                else:
                    logger.debug(f"Ressources insuffisantes sur {host['name']}: " +
                               f"CPU={'✓' if has_cpu else '✗'} " +
                               f"RAM={'✓' if has_ram else '✗'} " +
                               f"Disk={'✓' if has_disk else '✗'}")
                    
            except Exception as e:
                logger.error(f"Erreur test hôte {host['name']}: {e}")
                continue
        
        logger.warning("Aucun hôte avec ressources suffisantes")
        return None
    
    def get_host_usage_with_timeout(self, host_uri: str, timeout: int = 5):
        """Récupère l'utilisation d'un hôte avec timeout"""
        result_queue = queue.Queue()
        
        def worker():
            try:
                usage = self.get_host_usage(host_uri)
                result_queue.put(('success', usage))
            except Exception as e:
                result_queue.put(('error', e))
        
        thread = threading.Thread(target=worker)
        thread.daemon = True
        thread.start()
        thread.join(timeout=timeout)
        
        if thread.is_alive():
            logger.debug(f"Timeout récupération usage: {host_uri}")
            return None
        
        try:
            status, result = result_queue.get_nowait()
            if status == 'success':
                return result
            else:
                logger.debug(f"Erreur récupération usage: {result}")
                return None
        except queue.Empty:
            return None
    
    def test_host_connectivity(self, host_uri: str) -> Dict:
        """Test la connectivité d'un hôte"""
        result = {
            'uri': host_uri,
            'accessible': False,
            'status': 'unknown',
            'response_time': 0,
            'error': None
        }
        
        start_time = time.time()
        
        try:
            if host_uri.startswith('qemu+ssh://'):
                parts = host_uri.split('@')
                if len(parts) >= 2:
                    hostname = parts[1].split('/')[0].split(':')[0]
                    
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3)
                    connect_result = sock.connect_ex((hostname, 22))
                    sock.close()
                    
                    if connect_result == 0:
                        result['accessible'] = True
                        result['status'] = 'ssh_ok'
                    else:
                        result['status'] = 'ssh_unreachable'
                        result['error'] = f'Port 22 fermé'
            else:
                conn = LibvirtService.get_connection(host_uri, timeout=3)
                if conn:
                    result['accessible'] = True
                    result['status'] = 'libvirt_ok'
                    conn.close()
                else:
                    result['status'] = 'libvirt_failed'
                    result['error'] = 'Connexion refusée'
                    
        except Exception as e:
            result['status'] = 'error'
            result['error'] = str(e)
            logger.debug(f"Test connectivité échoué {host_uri}: {e}")
        
        result['response_time'] = time.time() - start_time
        return result