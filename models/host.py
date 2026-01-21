# models/host.py
from typing import Dict, List, Optional
from models.storage import StorageManager
from services.libvirt_service import LibvirtService

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
        return new_host
    
    def update_host(self, host_id: str, updates: Dict) -> Optional[Dict]:
        """Met à jour un hôte"""
        hosts = self.get_all_hosts()
        
        for i, host in enumerate(hosts):
            if host.get('id') == host_id:
                hosts[i].update(updates)
                self.storage.save_hosts(hosts)
                return hosts[i]
        
        return None
    
    def delete_host(self, host_id: str) -> bool:
        """Supprime un hôte"""
        hosts = self.get_all_hosts()
        new_hosts = [h for h in hosts if h.get('id') != host_id]
        
        if len(new_hosts) != len(hosts):
            self.storage.save_hosts(new_hosts)
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
            print("❌ Aucun hôte activé disponible")
            return None
        
        # Trier par priorité
        hosts.sort(key=lambda h: h.get('priority', 999))
        
        print(f"🔍 Recherche hôte optimal pour {required_vcpu}vCPU, {required_ram}MiB RAM, {required_disk}GB Disk")
        print(f"   Hôtes disponibles: {len(hosts)}")
        
        for i, host in enumerate(hosts):
            print(f"\n[{i+1}/{len(hosts)}] Test hôte: {host['name']} (priorité: {host.get('priority', 999)})")
            
            start_time = time.time()
            try:
                # Vérifier rapidement si l'hôte est accessible
                if host['uri'].startswith('qemu+ssh://'):
                    # Test rapide de connectivité SSH
                    try:
                        import socket
                        parts = host['uri'].split('@')
                        if len(parts) >= 2:
                            hostname = parts[1].split('/')[0].split(':')[0]
                            
                            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            sock.settimeout(3)
                            result = sock.connect_ex((hostname, 22))
                            sock.close()
                            
                            if result != 0:
                                elapsed = time.time() - start_time
                                print(f"   ❌ Hôte SSH inaccessible: {hostname}:22 (temps: {elapsed:.2f}s)")
                                continue
                    except Exception as e:
                        elapsed = time.time() - start_time
                        print(f"   ⚠️  Test connectivité échoué: {e} (temps: {elapsed:.2f}s)")
                        continue
                
                # Récupérer l'utilisation avec timeout
                usage = self.get_host_usage_with_timeout(host['uri'], timeout=timeout_per_host)
                
                if not usage:
                    elapsed = time.time() - start_time
                    print(f"   ❌ Impossible de récupérer les ressources (temps: {elapsed:.2f}s)")
                    continue
                
                elapsed = time.time() - start_time
                
                # Vérifier si l'hôte a assez de ressources disponibles
                has_cpu = usage.get('available_vcpu', 0) >= required_vcpu
                has_ram = usage.get('available_ram', 0) >= required_ram
                has_disk = usage.get('available_disk', 0) >= required_disk
                
                if has_cpu and has_ram and has_disk:
                    print(f"   ✅ Hôte sélectionné: {host['name']}")
                    print(f"      CPU: {usage.get('available_vcpu', 0)}/{required_vcpu}")
                    print(f"      RAM: {usage.get('available_ram', 0)}/{required_ram} MiB")
                    print(f"      Disk: {usage.get('available_disk', 0)}/{required_disk} GB")
                    print(f"      Temps de sélection: {elapsed:.2f}s")
                    return host
                else:
                    print(f"   ❌ Ressources insuffisantes sur {host['name']}")
                    print(f"      CPU: {usage.get('available_vcpu', 0)}/{required_vcpu} {'✅' if has_cpu else '❌'}")
                    print(f"      RAM: {usage.get('available_ram', 0)}/{required_ram} {'✅' if has_ram else '❌'}")
                    print(f"      Disk: {usage.get('available_disk', 0)}/{required_disk} {'✅' if has_disk else '❌'}")
                    print(f"      Temps de vérification: {elapsed:.2f}s")
                    
            except Exception as e:
                elapsed = time.time() - start_time
                print(f"   ❌ Erreur sur hôte {host['name']}: {e} (temps: {elapsed:.2f}s)")
                continue
        
        print(f"\n❌ Aucun hôte n'a suffisamment de ressources disponibles")
        return None
    
    def get_host_usage_with_timeout(self, host_uri: str, timeout: int = 5):
        """Récupère l'utilisation d'un hôte avec timeout"""
        import threading
        import queue
        
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
            print(f"⏱️  Timeout récupération usage pour {host_uri}")
            return None
        
        try:
            status, result = result_queue.get_nowait()
            if status == 'success':
                return result
            else:
                print(f"❌ Erreur récupération usage: {result}")
                return None
        except queue.Empty:
            print(f"❌ Aucun résultat pour {host_uri}")
            return None