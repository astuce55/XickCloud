# models/host.py - VERSION CORRIGÉE POUR HÔTES DISTANTS
import time
import socket
import queue
import threading
import subprocess
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
        """
        Ajoute un nouvel hôte avec validation optionnelle
        
        CORRECTIONS:
        - Validation de connexion optionnelle (pas bloquante)
        - Meilleure gestion des erreurs
        - Logs détaillés
        """
        hosts = self.get_all_hosts()
        
        # Validation des données minimales
        if not host_data.get('name'):
            raise ValueError("Le nom de l'hôte est requis")
        if not host_data.get('uri'):
            raise ValueError("L'URI de l'hôte est requis")
        
        # Créer la structure de l'hôte
        new_host = {
            'id': host_data.get('id', f"host-{int(time.time())}"),
            'name': host_data.get('name'),
            'uri': host_data.get('uri', 'qemu:///system'),
            'enabled': host_data.get('enabled', True),
            'priority': host_data.get('priority', len(hosts) + 1),
            'storage_path': host_data.get('storage_path', '/var/lib/libvirt/images'),
            'quotas': host_data.get('quotas', {
                'max_vcpu': 8,
                'max_ram': 16384,
                'max_disk': 200
            }),
            'description': host_data.get('description', ''),
            'connection_verified': False,
            'last_check': None
        }
        
        logger.info(f"Ajout de l'hôte: {new_host['name']} ({new_host['uri']})")
        
        # Tester la connexion en mode non-bloquant
        if new_host['uri'].startswith('qemu+ssh://'):
            logger.info(f"Tentative de connexion à l'hôte distant: {new_host['name']}")
            
            # Test rapide SSH (non bloquant)
            try:
                ssh_result = self._quick_ssh_test(new_host['uri'], timeout=3)
                if ssh_result['accessible']:
                    logger.info(f"✓ Connexion SSH OK pour {new_host['name']}")
                    new_host['connection_verified'] = True
                    new_host['last_check'] = time.time()
                else:
                    logger.warning(f"⚠ SSH non accessible: {ssh_result.get('error')}")
                    logger.info("L'hôte sera ajouté mais marqué comme non vérifié")
            except Exception as e:
                logger.warning(f"⚠ Erreur test connexion: {e}")
                logger.info("L'hôte sera ajouté mais nécessitera une vérification ultérieure")
        
        # Ajouter l'hôte même si la connexion n'est pas vérifiée
        hosts.append(new_host)
        self.storage.save_hosts(hosts)
        
        logger.info(f"✓ Hôte ajouté: {new_host['name']}")
        return new_host
    
    def _quick_ssh_test(self, uri: str, timeout: int = 3) -> Dict:
        """
        Test SSH rapide et simple
        """
        result = {'accessible': False, 'error': None}
        
        try:
            # Extraire hostname et port
            if '@' not in uri:
                result['error'] = 'Format URI invalide (attendu: qemu+ssh://user@host/system)'
                return result
            
            parts = uri.split('@')
            user = parts[0].replace('qemu+ssh://', '')
            hostname_part = parts[1].split('/')[0]
            
            if ':' in hostname_part:
                hostname, port_str = hostname_part.split(':')
                port = int(port_str)
            else:
                hostname = hostname_part
                port = 22
            
            logger.debug(f"Test SSH: {user}@{hostname}:{port}")
            
            # Test 1: Port accessible
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            connect_result = sock.connect_ex((hostname, port))
            sock.close()
            
            if connect_result != 0:
                result['error'] = f'Port SSH {port} inaccessible sur {hostname}'
                return result
            
            # Test 2: Authentification SSH (optionnel, non bloquant)
            ssh_cmd = [
                'ssh',
                '-o', 'StrictHostKeyChecking=no',
                '-o', 'BatchMode=yes',
                '-o', f'ConnectTimeout={timeout}',
                '-p', str(port),
                f'{user}@{hostname}',
                'echo "OK"'
            ]
            
            try:
                ssh_result = subprocess.run(
                    ssh_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout + 2
                )
                
                if ssh_result.returncode == 0:
                    result['accessible'] = True
                    logger.debug(f"✓ SSH accessible")
                else:
                    result['error'] = 'Clés SSH non configurées ou authentification refusée'
                    logger.debug(f"⚠ {result['error']}")
            except subprocess.TimeoutExpired:
                result['error'] = 'Timeout SSH'
            
            return result
            
        except Exception as e:
            result['error'] = str(e)
            logger.debug(f"Erreur test SSH: {e}")
            return result
    
    def verify_host_connection(self, host_id: str) -> Dict:
        """
        Vérifie la connexion d'un hôte (peut être appelé manuellement)
        """
        host = self.get_host_by_id(host_id)
        if not host:
            return {'success': False, 'error': 'Hôte non trouvé'}
        
        result = {
            'success': False,
            'host_id': host_id,
            'host_name': host['name'],
            'tests': {}
        }
        
        try:
            # Test SSH si distant
            if host['uri'].startswith('qemu+ssh://'):
                ssh_test = self._quick_ssh_test(host['uri'], timeout=5)
                result['tests']['ssh'] = ssh_test
                
                if not ssh_test['accessible']:
                    result['error'] = f"SSH: {ssh_test['error']}"
                    return result
            
            # Test Libvirt
            conn = LibvirtService.get_connection(host['uri'], timeout=10)
            if conn:
                result['tests']['libvirt'] = {'accessible': True}
                
                # Récupérer infos hôte
                try:
                    usage = LibvirtService.get_host_usage(host['uri'])
                    if usage:
                        result['tests']['resources'] = usage
                    conn.close()
                except Exception as e:
                    logger.warning(f"Impossible de récupérer les ressources: {e}")
                
                # Marquer comme vérifié
                self.update_host(host_id, {
                    'connection_verified': True,
                    'last_check': time.time()
                })
                
                result['success'] = True
                result['message'] = 'Connexion vérifiée avec succès'
            else:
                result['tests']['libvirt'] = {'accessible': False}
                result['error'] = 'Connexion libvirt refusée'
                
        except Exception as e:
            result['error'] = f'Erreur: {str(e)}'
            logger.error(f"Erreur vérification hôte {host_id}: {e}")
        
        return result
    
    def update_host(self, host_id: str, updates: Dict) -> Optional[Dict]:
        """Met à jour un hôte"""
        hosts = self.get_all_hosts()
        for i, host in enumerate(hosts):
            if host.get('id') == host_id:
                # Garder l'ID
                updates['id'] = host_id
                # Mettre à jour quotas si présent
                if 'quotas' in updates and isinstance(updates['quotas'], dict):
                    if 'quotas' not in host:
                        host['quotas'] = {}
                    host['quotas'].update(updates['quotas'])
                    del updates['quotas']
                
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
    
    def select_best_host(self, required_vcpu: int, required_ram: int, 
                        required_disk: int = 0, timeout_per_host: int = 10) -> Optional[Dict]:
        """
        Sélectionne le meilleur hôte disponible
        
        AMÉLIORATIONS:
        - Timeout plus long pour hôtes distants
        - Meilleure gestion des erreurs
        - Logs détaillés
        """
        hosts = self.get_enabled_hosts()
        
        if not hosts:
            logger.error("Aucun hôte activé disponible")
            return None
        
        # Trier par priorité
        hosts.sort(key=lambda h: h.get('priority', 999))
        
        logger.info(f"Recherche hôte pour: {required_vcpu}vCPU, {required_ram}MiB RAM, {required_disk}GB Disk")
        logger.info(f"{len(hosts)} hôte(s) à tester")
        
        for i, host in enumerate(hosts):
            logger.info(f"Test hôte [{i+1}/{len(hosts)}]: {host['name']}")
            
            try:
                # Timeout adapté au type d'hôte
                if host['uri'].startswith('qemu+ssh://'):
                    timeout = timeout_per_host
                else:
                    timeout = 5
                
                # Récupérer usage
                usage = self._get_host_usage_with_timeout(host['uri'], timeout)
                
                if not usage:
                    logger.warning(f"Impossible de récupérer ressources de {host['name']}")
                    continue
                
                # Vérifier disponibilité
                has_cpu = usage.get('available_vcpu', 0) >= required_vcpu
                has_ram = usage.get('available_ram', 0) >= required_ram
                has_disk = usage.get('available_disk', 0) >= required_disk
                
                logger.debug(f"Ressources {host['name']}: " +
                           f"CPU {usage.get('available_vcpu')}/{required_vcpu} " +
                           f"RAM {usage.get('available_ram')}/{required_ram} " +
                           f"Disk {usage.get('available_disk')}/{required_disk}")
                
                if has_cpu and has_ram and has_disk:
                    logger.info(f"✓ Hôte sélectionné: {host['name']}")
                    return host
                else:
                    reasons = []
                    if not has_cpu:
                        reasons.append(f"CPU insuffisant ({usage.get('available_vcpu')}/{required_vcpu})")
                    if not has_ram:
                        reasons.append(f"RAM insuffisante ({usage.get('available_ram')}/{required_ram})")
                    if not has_disk:
                        reasons.append(f"Disk insuffisant ({usage.get('available_disk')}/{required_disk})")
                    logger.debug(f"Ressources insuffisantes: {', '.join(reasons)}")
                    
            except Exception as e:
                logger.error(f"Erreur test hôte {host['name']}: {e}")
                continue
        
        logger.error("Aucun hôte avec ressources suffisantes trouvé")
        return None
    
    def _get_host_usage_with_timeout(self, host_uri: str, timeout: int = 10):
        """Récupère usage avec timeout"""
        result_queue = queue.Queue()
        
        def worker():
            try:
                usage = self.get_host_usage(host_uri)
                result_queue.put(('success', usage))
            except Exception as e:
                result_queue.put(('error', str(e)))
        
        thread = threading.Thread(target=worker)
        thread.daemon = True
        thread.start()
        thread.join(timeout=timeout)
        
        if thread.is_alive():
            logger.debug(f"Timeout récupération usage ({timeout}s)")
            return None
        
        try:
            status, result = result_queue.get_nowait()
            return result if status == 'success' else None
        except queue.Empty:
            return None
    
    def get_ssh_setup_guide(self, host_uri: str) -> str:
        """Guide pour configurer SSH"""
        try:
            if '@' not in host_uri:
                return "URI invalide"
            
            parts = host_uri.split('@')
            user = parts[0].replace('qemu+ssh://', '')
            hostname = parts[1].split('/')[0].split(':')[0]
            
            guide = f"""
╔═══════════════════════════════════════════════════════════════╗
║  CONFIGURATION SSH POUR L'HÔTE DISTANT                        ║
║  Hôte: {hostname:<52} ║
╚═══════════════════════════════════════════════════════════════╝

📋 ÉTAPES DE CONFIGURATION:

1️⃣  Générer une paire de clés SSH (si nécessaire):
   $ ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa

2️⃣  Copier la clé publique vers l'hôte distant:
   $ ssh-copy-id {user}@{hostname}
   
   OU manuellement:
   $ cat ~/.ssh/id_rsa.pub | ssh {user}@{hostname} "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"

3️⃣  Tester la connexion SSH:
   $ ssh {user}@{hostname} 'echo "Connexion OK"'

4️⃣  Configurer libvirt sur l'hôte distant:
   $ ssh {user}@{hostname}
   $ sudo usermod -aG libvirt {user}
   $ sudo systemctl restart libvirtd
   $ exit

5️⃣  Tester la connexion libvirt:
   $ virsh -c {host_uri} list --all

6️⃣  Dans l'interface web, cliquer sur "Vérifier la connexion"

╔═══════════════════════════════════════════════════════════════╗
║  DÉPANNAGE                                                     ║
╚═══════════════════════════════════════════════════════════════╝

❌ Si "Permission denied":
   • Vérifier que la clé publique est dans ~/.ssh/authorized_keys
   • Vérifier les permissions: chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys

❌ Si "Connection refused":
   • Vérifier que SSH est actif: sudo systemctl status sshd
   • Vérifier le firewall: sudo ufw allow ssh

❌ Si "libvirt: authentication unavailable":
   • Vérifier groupe libvirt: groups {user}
   • Redémarrer session SSH après usermod

"""
            return guide
            
        except Exception as e:
            return f"Erreur: {e}"