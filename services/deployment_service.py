# services/deployment_service.py
import os
import subprocess
import time
from typing import Dict, Optional
from config import GEN_DIR, OS_IMAGES, VM_STORAGE_DIR
from services.libvirt_service import LibvirtService
from services.network_service import NetworkService

class DeploymentService:
    def __init__(self):
        pass
    
    @staticmethod
    def generate_cloudinit(vm_name: str, hostname: str, username: str, 
                          password: str, ssh_key: str = "", 
                          static_ip: str = None) -> Dict:
        """Génère les fichiers cloud-init"""
        
        ssh_block = f"\n      - {ssh_key}" if ssh_key else ""
        
        # Configuration réseau
        network_config = "dhcp4: true"
        if static_ip:
            network_ip = static_ip.rsplit('.', 1)[0]
            network_config = f"dhcp4: false\n        addresses: [{static_ip}/24]\n        gateway4: {network_ip}.1\n        nameservers:\n          addresses: [8.8.8.8, 8.8.4.4]"
        
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
package_update: true
package_upgrade: true
write_files:
  - path: /etc/netplan/99-custom.yaml
    content: |
      network:
        version: 2
        ethernets:
          main: {{match: {{name: "e*"}}, {network_config}}}
    permissions: '0600'
runcmd:
  - netplan apply
  - systemctl start qemu-guest-agent
"""
        
        meta_data = f"instance-id: {vm_name}\nlocal-hostname: {hostname}"
        
        return {'user_data': user_data, 'meta_data': meta_data}
    
    @staticmethod
    def deploy_vm(vm_name: str, host_uri: str, storage_path: str, 
                 base_image: str, disk_size: int, vcpu: int, 
                 ram: int, network: str, cloudinit_data: Dict) -> bool:
        """Déploie une VM"""
        
        # Chemins des fichiers
        vm_disk = f"{storage_path}/{vm_name}.qcow2"
        seed_iso = f"{GEN_DIR}/{vm_name}-seed.iso"
        user_data_file = f"{GEN_DIR}/{vm_name}-user-data"
        meta_data_file = f"{GEN_DIR}/{vm_name}-meta-data"
        
        try:
            # Créer le disque
            if host_uri.startswith('qemu+ssh://'):
                # Hôte distant
                ssh_host = host_uri.split('@')[1].split('/')[0]
                ssh_user = host_uri.split('//')[1].split('@')[0]
                
                subprocess.run([
                    "ssh", f"{ssh_user}@{ssh_host}",
                    f"qemu-img create -f qcow2 -F qcow2 -b {base_image} {vm_disk} {disk_size}G"
                ], check=True)
            else:
                # Hôte local
                subprocess.run([
                    "qemu-img", "create", "-f", "qcow2", "-F", "qcow2",
                    "-b", base_image, vm_disk, f"{disk_size}G"
                ], check=True)
            
            # Écrire les fichiers cloud-init
            with open(user_data_file, 'w') as f:
                f.write(cloudinit_data['user_data'])
            with open(meta_data_file, 'w') as f:
                f.write(cloudinit_data['meta_data'])
            
            # Créer l'ISO seed
            subprocess.run(["cloud-localds", seed_iso, user_data_file, meta_data_file], check=True)
            
            # Copier l'ISO sur l'hôte distant si nécessaire
            if host_uri.startswith('qemu+ssh://'):
                ssh_host = host_uri.split('@')[1].split('/')[0]
                ssh_user = host_uri.split('//')[1].split('@')[0]
                remote_seed = f"{storage_path}/{vm_name}-seed.iso"
                subprocess.run(["scp", seed_iso, f"{ssh_user}@{ssh_host}:{remote_seed}"], check=True)
                seed_iso = remote_seed
            
            # Déterminer l'OS variant
            if 'ubuntu' in base_image:
                variant = "ubuntu22.04"
            elif 'debian' in base_image:
                variant = "debian11"
            else:
                variant = "generic"
            
            # Déployer la VM avec virt-install
            subprocess.run([
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
            ], check=True)
            
            return True
            
        except Exception as e:
            print(f"Erreur déploiement VM {vm_name}: {e}")
            return False
    
    @staticmethod
    def deploy_swarm_node(username: str, node_name: str, cluster_name: str,
                         node_type: str, ip_address: str, host_uri: str,
                         storage_path: str, password: str, ssh_key: str) -> bool:
        """Déploie un nœud Docker Swarm"""
        
        full_vm_name = f"{username}_{node_name}"
        network_name = NetworkService.get_swarm_network_name(username, cluster_name)
        base_image = OS_IMAGES['ubuntu']
        
        # Générer cloud-init avec installation Docker
        cloudinit_data = DeploymentService.generate_cloudinit(
            vm_name=full_vm_name,
            hostname=node_name,
            username=username,
            password=password,
            ssh_key=ssh_key,
            static_ip=ip_address
        )
        
        # Ajouter l'installation de Docker
        docker_setup = """
  - path: /usr/local/bin/setup-docker.sh
    content: |
      #!/bin/bash
      # Installation Docker
      curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
      echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
      apt-get update
      apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
      systemctl enable docker
      systemctl start docker
      usermod -aG docker {username}
      
      # Configuration Firewall pour Swarm
      ufw allow 2377/tcp  # Cluster management
      ufw allow 7946/tcp  # Node communication
      ufw allow 7946/udp  # Node communication
      ufw allow 4789/udp  # Overlay network
      ufw allow 22/tcp    # SSH
      echo "y" | ufw enable
      
      # Marquer comme prêt
      touch /var/lib/cloud/docker-ready
    permissions: '0755'
runcmd:
  - netplan apply
  - /usr/local/bin/setup-docker.sh
  - systemctl start qemu-guest-agent
"""
        
        # Remplacer {username} dans le script Docker
        docker_setup = docker_setup.format(username=username)
        
        # Ajouter le script Docker au cloud-init
        user_data = cloudinit_data['user_data']
        if 'runcmd:' in user_data:
            user_data = user_data.replace('runcmd:', docker_setup)
        
        cloudinit_data['user_data'] = user_data
        
        # Déployer la VM
        return DeploymentService.deploy_vm(
            vm_name=full_vm_name,
            host_uri=host_uri,
            storage_path=storage_path,
            base_image=base_image,
            disk_size=30,  # Taille fixe pour les nœuds Swarm
            vcpu=2,
            ram=4096,
            network=network_name,
            cloudinit_data=cloudinit_data
        )