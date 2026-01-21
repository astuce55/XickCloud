# models/swarm.py
import os
import json
import time
import hashlib
from typing import Dict, List, Optional, Any
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
        
        # Générer les informations des nœuds
        nodes = []
        cluster_ip_base = f"192.168.{abs(hash(cluster_name)) % 240 + 10}"
        
        # Créer les managers
        for i in range(num_managers):
            node_name = f"{cluster_name}-manager-{i+1}"
            full_vm_name = self.vm_manager.get_full_vm_name(username, node_name)
            ip_address = f"{cluster_ip_base}.{10 + i}"
            
            nodes.append({
                'name': node_name,
                'full_name': full_vm_name,
                'type': 'manager',
                'ip': ip_address,
                'status': 'deploying'
            })
        
        # Créer les workers
        for i in range(num_workers):
            node_name = f"{cluster_name}-worker-{i+1}"
            full_vm_name = self.vm_manager.get_full_vm_name(username, node_name)
            ip_address = f"{cluster_ip_base}.{20 + i}"
            
            nodes.append({
                'name': node_name,
                'full_name': full_vm_name,
                'type': 'worker',
                'ip': ip_address,
                'status': 'deploying'
            })
        
        # Enregistrer le cluster
        self.clusters[cluster_name] = {
            'owner': username,
            'created_at': time.time(),
            'network': network,
            'nodes': nodes,
            'status': 'deploying',
            'manager_ip': manager_ip,
            'host': host_uri,
            'num_managers': num_managers,
            'num_workers': num_workers,
            'init_commands': {
                'init_swarm': f"ssh {username}@{manager_ip} 'sudo docker swarm init --advertise-addr {manager_ip}'",
                'get_manager_token': f"ssh {username}@{manager_ip} 'sudo docker swarm join-token manager -q'",
                'get_worker_token': f"ssh {username}@{manager_ip} 'sudo docker swarm join-token worker -q'"
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
            self._save_clusters()
    
    def delete_cluster(self, cluster_name: str) -> bool:
        """Supprime un cluster et toutes ses VMs"""
        if cluster_name not in self.clusters:
            return False
        
        cluster = self.clusters[cluster_name]
        
        # Supprimer toutes les VMs du cluster
        for node in cluster.get('nodes', []):
            vm_name = node.get('full_name')
            if vm_name and self.vm_manager.vm_exists(vm_name):
                # Ici, vous devez implémenter la suppression des VMs
                # via LibvirtService
                self.vm_manager.delete_vm_metadata(vm_name)
        
        # Supprimer le cluster
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
    
    def get_cluster_status(self, cluster_name: str) -> Dict:
        """Récupère le statut détaillé d'un cluster"""
        cluster = self.get_cluster(cluster_name)
        if not cluster:
            return {'error': 'Cluster not found'}
        
        # Vérifier le statut des nœuds
        nodes_status = []
        all_ready = True
        
        for node in cluster.get('nodes', []):
            vm_info = self.vm_manager.get_vm_info(node.get('full_name'))
            node_status = {
                'name': node.get('name'),
                'type': node.get('type'),
                'ip': node.get('ip'),
                'vm_status': vm_info.get('status', 'unknown') if vm_info else 'not_found',
                'deployed': vm_info is not None
            }
            nodes_status.append(node_status)
            
            if node_status['vm_status'] != 'ready':
                all_ready = False
        
        return {
            'cluster_name': cluster_name,
            'owner': cluster.get('owner'),
            'status': 'ready' if all_ready else 'deploying',
            'manager_ip': cluster.get('manager_ip'),
            'num_managers': cluster.get('num_managers'),
            'num_workers': cluster.get('num_workers'),
            'nodes': nodes_status,
            'init_commands': cluster.get('init_commands')
        }