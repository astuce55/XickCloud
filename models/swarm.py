# models/swarm.py - VERSION COMPLÈTE AVEC GESTION DES IPs
import os
import json
import time
from typing import Dict, List, Optional
from config import SWARM_CLUSTERS_FILE
from models.vm import VMManager

class SwarmManager:
    def __init__(self):
        self.clusters_file = SWARM_CLUSTERS_FILE
        self.clusters = self._load_clusters()
        self.vm_manager = VMManager()
    
    def _load_clusters(self) -> Dict:
        """Charge les clusters depuis le fichier"""
        if os.path.exists(self.clusters_file):
            try:
                with open(self.clusters_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_clusters(self):
        """Sauvegarde les clusters dans le fichier"""
        with open(self.clusters_file, 'w') as f:
            json.dump(self.clusters, f, indent=2)
    
    def get_user_clusters(self, username: str) -> Dict:
        """Récupère les clusters d'un utilisateur"""
        return {k: v for k, v in self.clusters.items() if v.get('owner') == username}
    
    def create_cluster(self, cluster_name: str, username: str, num_managers: int, 
                      num_workers: int, manager_ip: str, network: str, host_uri: str) -> Dict:
        """Crée un nouveau cluster dans la base de données"""
        
        # Générer les informations des nœuds (sans IPs prédéfinies)
        nodes = []
        
        # Créer les managers
        for i in range(num_managers):
            node_name = f"{cluster_name}-manager-{i+1}"
            full_vm_name = self.vm_manager.get_full_vm_name(username, node_name)
            
            nodes.append({
                'name': node_name,
                'full_name': full_vm_name,
                'type': 'manager',
                'ip': '',  # Sera rempli après obtention
                'status': 'deploying'
            })
        
        # Créer les workers
        for i in range(num_workers):
            node_name = f"{cluster_name}-worker-{i+1}"
            full_vm_name = self.vm_manager.get_full_vm_name(username, node_name)
            
            nodes.append({
                'name': node_name,
                'full_name': full_vm_name,
                'type': 'worker',
                'ip': '',  # Sera rempli après obtention
                'status': 'deploying'
            })
        
        # Enregistrer le cluster
        self.clusters[cluster_name] = {
            'owner': username,
            'created_at': time.time(),
            'network': network,
            'nodes': nodes,
            'status': 'deploying',
            'manager_ip': '',  # Sera rempli après
            'host': host_uri,
            'num_managers': num_managers,
            'num_workers': num_workers,
            'init_commands': {
                'init_swarm': f"# Connectez-vous d'abord au manager puis exécutez:\nsudo docker swarm init --advertise-addr <MANAGER_IP>",
                'get_manager_token': f"# Sur le manager principal:\nsudo docker swarm join-token manager -q",
                'get_worker_token': f"# Sur le manager principal:\nsudo docker swarm join-token worker -q"
            }
        }
        
        self._save_clusters()
        return self.clusters[cluster_name]
    
    def get_cluster(self, cluster_name: str) -> Optional[Dict]:
        """Récupère un cluster par son nom"""
        return self.clusters.get(cluster_name)
    
    def update_cluster(self, cluster_name: str, updates: Dict):
        """Met à jour un cluster"""
        if cluster_name in self.clusters:
            self.clusters[cluster_name].update(updates)
            
            # Si on met à jour le manager_ip, mettre à jour les commandes
            if 'manager_ip' in updates and updates['manager_ip']:
                manager_ip = updates['manager_ip']
                self.clusters[cluster_name]['init_commands'] = {
                    'init_swarm': f"ssh {self.clusters[cluster_name]['owner']}@{manager_ip} 'sudo docker swarm init --advertise-addr {manager_ip}'",
                    'get_manager_token': f"ssh {self.clusters[cluster_name]['owner']}@{manager_ip} 'sudo docker swarm join-token manager -q'",
                    'get_worker_token': f"ssh {self.clusters[cluster_name]['owner']}@{manager_ip} 'sudo docker swarm join-token worker -q'"
                }
            
            self._save_clusters()
    
    def delete_cluster(self, cluster_name: str) -> bool:
        """Supprime un cluster et toutes ses VMs"""
        if cluster_name not in self.clusters:
            return False
        
        cluster = self.clusters[cluster_name]
        
        # Supprimer toutes les VMs du cluster via libvirt
        from services.libvirt_service import LibvirtService
        
        host_uri = cluster.get('host')
        if host_uri:
            for node in cluster.get('nodes', []):
                vm_name = node.get('full_name')
                if vm_name:
                    # Supprimer la VM de libvirt
                    LibvirtService.control_domain(host_uri, vm_name, 'delete')
                    # Supprimer les métadonnées
                    self.vm_manager.delete_vm_metadata(vm_name)
        
        # Supprimer le cluster de la base
        del self.clusters[cluster_name]
        self._save_clusters()
        return True
    
    def update_node_status(self, cluster_name: str, node_name: str, status: str):
        """Met à jour le statut d'un nœud"""
        if cluster_name in self.clusters:
            cluster = self.clusters[cluster_name]
            for node in cluster.get('nodes', []):
                if node.get('name') == node_name:
                    node['status'] = status
                    self._save_clusters()
                    break
    
    def update_node_ip(self, cluster_name: str, node_name: str, ip: str):
        """Met à jour l'IP d'un nœud"""
        if cluster_name in self.clusters:
            cluster = self.clusters[cluster_name]
            
            for node in cluster.get('nodes', []):
                if node.get('name') == node_name:
                    node['ip'] = ip
                    
                    # Si c'est le premier manager et qu'on n'a pas encore d'IP manager
                    if node.get('type') == 'manager' and not cluster.get('manager_ip'):
                        cluster['manager_ip'] = ip
                        # Mettre à jour les commandes avec l'IP
                        self.update_cluster(cluster_name, {'manager_ip': ip})
                    
                    self._save_clusters()
                    break
    
    def get_cluster_status(self, cluster_name: str) -> Dict:
        """Récupère le statut détaillé d'un cluster"""
        cluster = self.get_cluster(cluster_name)
        if not cluster:
            return {'error': 'Cluster non trouvé'}
        
        from services.libvirt_service import LibvirtService
        
        # Vérifier le statut des nœuds
        nodes_status = []
        all_ready = True
        all_have_ips = True
        
        host_uri = cluster.get('host')
        
        for node in cluster.get('nodes', []):
            vm_name = node.get('full_name')
            vm_info = self.vm_manager.get_vm_info(vm_name)
            
            # Récupérer l'IP si elle n'est pas encore connue
            node_ip = node.get('ip', '')
            if not node_ip and host_uri:
                # Essayer de récupérer l'IP
                node_ip = LibvirtService.wait_for_vm_ip(vm_name, host_uri, timeout=5)
                if node_ip:
                    self.update_node_ip(cluster_name, node['name'], node_ip)
            
            node_status = {
                'name': node.get('name'),
                'full_name': vm_name,
                'type': node.get('type'),
                'ip': node_ip or 'Attente...',
                'vm_status': vm_info.get('status', 'unknown') if vm_info else 'not_found',
                'deployed': vm_info is not None
            }
            nodes_status.append(node_status)
            
            if node_status['vm_status'] != 'ready':
                all_ready = False
            if not node_ip:
                all_have_ips = False
        
        # Déterminer le statut global
        if all_ready and all_have_ips:
            status = 'ready'
        elif all_have_ips:
            status = 'deployed'
        else:
            status = 'deploying'
        
        return {
            'cluster_name': cluster_name,
            'owner': cluster.get('owner'),
            'status': status,
            'manager_ip': cluster.get('manager_ip', 'Attente...'),
            'num_managers': cluster.get('num_managers'),
            'num_workers': cluster.get('num_workers'),
            'nodes': nodes_status,
            'network': cluster.get('network'),
            'host': cluster.get('host'),
            'created_at': cluster.get('created_at'),
            'init_commands': cluster.get('init_commands', {})
        }
    
    def get_first_manager_ip(self, cluster_name: str) -> Optional[str]:
        """Récupère l'IP du premier manager d'un cluster"""
        cluster = self.get_cluster(cluster_name)
        if not cluster:
            return None
        
        # Chercher le premier manager avec une IP
        for node in cluster.get('nodes', []):
            if node.get('type') == 'manager' and node.get('ip'):
                return node['ip']
        
        return None
