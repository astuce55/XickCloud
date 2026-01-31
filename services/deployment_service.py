# services/deployment_service.py - VERSION SIMPLE QUI FONCTIONNE
import os
import subprocess
import time
from typing import Dict
from config import GEN_DIR, OS_IMAGES, VM_STORAGE_DIR, FLAVORS
from services.libvirt_service import LibvirtService
from config_logging import deployment_logger as logger

class DeploymentService:
    
    @staticmethod
    def generate_cloudinit(vm_name: str, hostname: str, username: str, 
                          password: str, ssh_key: str = "") -> Dict:
        """Cloud-init SIMPLE qui fonctionne - comme dans ton app.py original"""
        
        ssh_block = f"\n      - {ssh_key}" if ssh_key else ""
        
        # Exactement comme dans ton app.py qui marche
        user_data = f"""#cloud-config
hostname: {hostname}
manage_etc_hosts: true
users:
  - default
  - name: {username}
    groups: sudo
    shell: /bin/bash
    lock_passwd: false
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:{ssh_block}
chpasswd:
  list: |
    {username}:{password}
  expire: false
ssh_pwauth: true
package_update: false
package_upgrade: false
packages:
  - qemu-guest-agent
write_files:
  - path: /etc/netplan/99-custom.yaml
    content: |
      network:
        version: 2
        ethernets:
          main: {{match: {{name: "e*"}}, dhcp4: true}}
    permissions: '0600'
runcmd:
  - netplan apply
  - systemctl start qemu-guest-agent
"""
        
        meta_data = f"""instance-id: {vm_name}
local-hostname: {hostname}
"""
        
        return {
            'user_data': user_data,
            'meta_data': meta_data
        }
    
    @staticmethod
    def deploy_vm(vm_name: str, host_uri: str, storage_path: str, 
                 base_image: str, disk_size: int, vcpu: int, 
                 ram: int, network: str, cloudinit_data: Dict) -> bool:
        """Déploiement SIMPLE qui fonctionne"""
        
        vm_disk = f"{storage_path}/{vm_name}.qcow2"
        seed_iso = f"{GEN_DIR}/{vm_name}-seed.iso"
        user_data_file = f"{GEN_DIR}/{vm_name}-user-data"
        meta_data_file = f"{GEN_DIR}/{vm_name}-meta-data"
        
        logger.info(f"Déploiement VM {vm_name}")
        
        try:
            # Créer le disque
            if host_uri.startswith('qemu+ssh://'):
                ssh_host = host_uri.split('@')[1].split('/')[0]
                ssh_user = host_uri.split('//')[1].split('@')[0]
                
                subprocess.run([
                    "ssh", "-o", "StrictHostKeyChecking=no",
                    f"{ssh_user}@{ssh_host}",
                    f"qemu-img create -f qcow2 -F qcow2 -b {base_image} {vm_disk} {disk_size}G"
                ], check=True, timeout=30)
            else:
                subprocess.run([
                    "qemu-img", "create", "-f", "qcow2", "-F", "qcow2",
                    "-b", base_image, vm_disk, f"{disk_size}G"
                ], check=True, timeout=30)
            
            # Écrire cloud-init
            with open(user_data_file, 'w') as f:
                f.write(cloudinit_data['user_data'])
            with open(meta_data_file, 'w') as f:
                f.write(cloudinit_data['meta_data'])
            
            # Créer ISO (SANS network-config, comme dans ton original)
            subprocess.run([
                "cloud-localds",
                seed_iso,
                user_data_file,
                meta_data_file
            ], check=True, timeout=30)
            
            # Copier ISO si distant
            if host_uri.startswith('qemu+ssh://'):
                ssh_host = host_uri.split('@')[1].split('/')[0]
                ssh_user = host_uri.split('//')[1].split('@')[0]
                remote_seed = f"{storage_path}/{vm_name}-seed.iso"
                
                subprocess.run([
                    "scp", "-o", "StrictHostKeyChecking=no",
                    seed_iso, f"{ssh_user}@{ssh_host}:{remote_seed}"
                ], check=True, timeout=30)
                
                seed_iso = remote_seed
            
            # Déterminer variant
            if 'ubuntu' in base_image.lower():
                variant = "ubuntu22.04"
            elif 'debian' in base_image.lower():
                variant = "debian11"
            else:
                variant = "generic"
            
            # Déployer - EXACTEMENT comme dans ton app.py
            virt_install_cmd = [
                "virt-install",
                f"--name={vm_name}",
                f"--vcpus={vcpu}",
                f"--memory={ram}",
                f"--disk=path={vm_disk},device=disk,bus=virtio",
                f"--disk=path={seed_iso},device=cdrom",
                f"--os-variant={variant}",
                "--import",
                "--noautoconsole",
                "--graphics=none",
                "--network", f"network={network},model=virtio",
                "--connect", host_uri
            ]
            
            logger.info(f"Lancement virt-install pour {vm_name}")
            
            result = subprocess.run(
                virt_install_cmd,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode == 0:
                logger.info(f"✓ VM {vm_name} déployée")
                
                # Attendre un peu puis lancer récupération IP
                time.sleep(5)
                LibvirtService.update_vm_ip_in_background(vm_name, host_uri)
                
                return True
            else:
                logger.error(f"Erreur virt-install: {result.stderr}")
                return False
            
        except Exception as e:
            logger.error(f"Erreur déploiement: {e}", exc_info=True)
            return False
    
    @staticmethod
    def deploy_swarm_node(username: str, node_name: str, cluster_name: str,
                         node_type: str, host_uri: str, storage_path: str,
                         password: str, ssh_key: str = "") -> bool:
        """Déploie un nœud Swarm avec la méthode simple"""
        
        from models.vm import VMManager
        from services.network_service import NetworkService
        
        logger.info(f"Déploiement nœud Swarm: {node_name}")
        
        vm_manager = VMManager()
        full_vm_name = vm_manager.get_full_vm_name(username, node_name)
        
        flavor = FLAVORS['swarm']
        network_name = NetworkService.get_swarm_network_name(username, cluster_name)
        
        # Cloud-init pour Swarm
        cloudinit = DeploymentService.generate_swarm_cloudinit(
            vm_name=full_vm_name,
            hostname=node_name,
            username=username,
            password=password,
            ssh_key=ssh_key,
            node_type=node_type
        )
        
        base_image = OS_IMAGES.get('ubuntu', '/var/lib/libvirt/images/base-images/base-ubuntu.qcow2')
        
        return DeploymentService.deploy_vm(
            vm_name=full_vm_name,
            host_uri=host_uri,
            storage_path=storage_path,
            base_image=base_image,
            disk_size=flavor['disk'],
            vcpu=flavor['vcpu'],
            ram=flavor['ram'],
            network=network_name,
            cloudinit_data=cloudinit
        )
    
    @staticmethod
    def generate_swarm_cloudinit(vm_name: str, hostname: str, username: str,
                                password: str, ssh_key: str, node_type: str) -> Dict:
        """Cloud-init pour Swarm - version simple"""
        
        ssh_block = f"\n      - {ssh_key}" if ssh_key else ""
        
        user_data = f"""#cloud-config
hostname: {hostname}
manage_etc_hosts: true
users:
  - default
  - name: {username}
    groups: sudo, docker
    shell: /bin/bash
    lock_passwd: false
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:{ssh_block}
chpasswd:
  list: |
    {username}:{password}
  expire: false
ssh_pwauth: true
package_update: false
package_upgrade: false
packages:
  - qemu-guest-agent
  - docker.io
write_files:
  - path: /etc/netplan/99-custom.yaml
    content: |
      network:
        version: 2
        ethernets:
          main: {{match: {{name: "e*"}}, dhcp4: true}}
    permissions: '0600'
runcmd:
  - netplan apply
  - systemctl enable docker
  - systemctl start docker
  - usermod -aG docker {username}
  - systemctl start qemu-guest-agent
  - ufw allow 2377/tcp || true
  - ufw allow 7946/tcp || true
  - ufw allow 7946/udp || true
  - ufw allow 4789/udp || true
"""
        
        meta_data = f"""instance-id: {vm_name}
local-hostname: {hostname}
"""
        
        return {
            'user_data': user_data,
            'meta_data': meta_data
        }