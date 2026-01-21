# models/vm.py
import os
import json
import time
import re
import subprocess
import libvirt
from typing import Dict, List, Optional, Any
from datetime import datetime
from config import METADATA_FILE, FLAVORS, OS_IMAGES, VM_STORAGE_DIR, GEN_DIR
from services.libvirt_service import LibvirtService

class VMManager:
    def __init__(self):
        self.metadata_file = METADATA_FILE
        self.metadata = self._load_metadata()
    
    def _load_metadata(self) -> Dict:
        """Charge les métadonnées des VMs"""
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_metadata(self):
        """Sauvegarde les métadonnées des VMs"""
        with open(self.metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)
    
    def get_full_vm_name(self, username: str, hostname: str) -> str:
        """Génère le nom complet de la VM"""
        return f"{username}_{hostname}"
    
    def get_user_vm_name(self, full_vm_name: str) -> str:
        """Extrait le nom court sans préfixe utilisateur"""
        if '_' in full_vm_name:
            return full_vm_name.split('_', 1)[1]
        return full_vm_name
    
    def get_vm_owner(self, full_vm_name: str) -> Optional[str]:
        """Extrait le propriétaire d'une VM"""
        if '_' in full_vm_name:
            return full_vm_name.split('_', 1)[0]
        return self.metadata.get(full_vm_name, {}).get('user')
    
    def get_user_vms(self, username: str) -> List[Dict]:
        """Récupère toutes les VMs d'un utilisateur"""
        user_vms = []
        for vm_name, vm_data in self.metadata.items():
            if vm_data.get('user') == username:
                user_vms.append({
                    'name': vm_name,
                    'display_name': vm_data.get('display_name', self.get_user_vm_name(vm_name)),
                    **vm_data
                })
        return user_vms
    
    def create_vm_metadata(self, username: str, hostname: str, flavor_id: str, 
                          host_uri: str, host_name: str) -> str:
        """Crée les métadonnées pour une nouvelle VM"""
        full_vm_name = self.get_full_vm_name(username, hostname)
        
        self.metadata[full_vm_name] = {
            'user': username,
            'created_at': time.time(),
            'flavor': flavor_id,
            'host': host_uri,
            'host_name': host_name,
            'display_name': hostname,
            'cluster_node': False,
            'status': 'deploying'
        }
        
        self._save_metadata()
        return full_vm_name
    
    def update_vm_metadata(self, vm_name: str, updates: Dict):
        """Met à jour les métadonnées d'une VM"""
        if vm_name in self.metadata:
            self.metadata[vm_name].update(updates)
            self._save_metadata()
    
    def delete_vm_metadata(self, vm_name: str):
        """Supprime les métadonnées d'une VM"""
        if vm_name in self.metadata:
            del self.metadata[vm_name]
            self._save_metadata()
    
    def vm_exists(self, vm_name: str) -> bool:
        """Vérifie si une VM existe dans les métadonnées"""
        return vm_name in self.metadata
    
    def get_vm_info(self, vm_name: str) -> Optional[Dict]:
        """Récupère les informations d'une VM"""
        return self.metadata.get(vm_name)
    
    def mark_as_swarm_node(self, vm_name: str, cluster_name: str, node_type: str, 
                          node_ip: str, network: str):
        """Marque une VM comme nœud Swarm"""
        self.update_vm_metadata(vm_name, {
            'cluster_node': True,
            'cluster_name': cluster_name,
            'node_type': node_type,
            'node_ip': node_ip,
            'network': network,
            'status': 'ready'
        })