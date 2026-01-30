# services/deployment_service.py - VERSION CORRIGÉE
import os
import subprocess
import time
from typing import Dict, Optional
from config import GEN_DIR, OS_IMAGES, VM_STORAGE_DIR
from services.libvirt_service import LibvirtService
from services.network_service import NetworkService
from config_logging import deployment_logger as logger

class DeploymentService:
    def __init__(self):
        pass
    
    @staticmethod
    def generate_cloudinit(vm_name: str, hostname: str, username: str, 
                          password: str, ssh_key: str = "", 
                          static_ip: str = None) -> Dict:
        """Génère les fichiers cloud-init avec configuration réseau correcte"""
        
        ssh_block = f"\n      - {ssh_key}" if ssh_key else ""
        
        # Configuration réseau - CORRECTION ICI
        if static_ip:
            # IP statique avec configuration netplan correcte
            network_ip_base = static_ip.rsplit('.', 1)[0]
            gateway_ip = f"{network_ip_base}.1"
            
            # Utiliser network-config au lieu de write_files pour netplan
            network_config = f"""version: 2
ethernets:
  ens3:
    dhcp4: false
    addresses:
      - {static_ip}/24
    gateway4: {gateway_ip}
    nameservers:
      addresses:
        - 8.8.8.8
        - 8.8.4.4
"""
        else:
            # DHCP par défaut
            network_config = f"""version: 2
ethernets:
  ens3:
    dhcp4: true
    dhcp-identifier: mac
"""
        
        user_data = f"""#cloud-config
hostname: {hostname}
manage_etc_hosts: true
fqdn: {hostname}.local
prefer_fqdn_over_hostname: true

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
disable_root: false

package_update: true
package_upgrade: false

packages:
  - qemu-guest-agent
  - net-tools
  - curl
  - vim

runcmd:
  - systemctl enable qemu-guest-agent
  - systemctl start qemu-guest-agent
  - systemctl restart systemd-networkd
  - echo "Cloud-init terminé" > /var/lib/cloud/instance/boot-finished

final_message: "Le système est prêt après $UPTIME secondes"
"""
        
        meta_data = f"""instance-id: {vm_name}
local-hostname: {hostname}
"""
        
        # Retourner les données avec network-config séparé
        return {
            'user_data': user_data,
            'meta_data': meta_data,
            'network_config': network_config
        }
    
    @staticmethod
    def deploy_vm(vm_name: str, host_uri: str, storage_path: str, 
                 base_image: str, disk_size: int, vcpu: int, 
                 ram: int, network: str, cloudinit_data: Dict) -> bool:
        """Déploie une VM avec configuration réseau correcte"""
        
        # Chemins des fichiers
        vm_disk = f"{storage_path}/{vm_name}.qcow2"
        seed_iso = f"{GEN_DIR}/{vm_name}-seed.iso"
        user_data_file = f"{GEN_DIR}/{vm_name}-user-data"
        meta_data_file = f"{GEN_DIR}/{vm_name}-meta-data"
        network_config_file = f"{GEN_DIR}/{vm_name}-network-config"
        
        logger.info(f"Déploiement VM {vm_name} sur {host_uri}")
        
        try:
            # Créer le disque
            if host_uri.startswith('qemu+ssh://'):
                # Hôte distant
                ssh_host = host_uri.split('@')[1].split('/')[0]
                ssh_user = host_uri.split('//')[1].split('@')[0]
                
                logger.debug(f"Création disque distant: {ssh_user}@{ssh_host}:{vm_disk}")
                
                subprocess.run([
                    "ssh",
                    "-o", "StrictHostKeyChecking=no",
                    f"{ssh_user}@{ssh_host}",
                    f"qemu-img create -f qcow2 -F qcow2 -b {base_image} {vm_disk} {disk_size}G"
                ], check=True, timeout=30)
            else:
                # Hôte local
                logger.debug(f"Création disque local: {vm_disk}")
                
                subprocess.run([
                    "qemu-img", "create", "-f", "qcow2", "-F", "qcow2",
                    "-b", base_image, vm_disk, f"{disk_size}G"
                ], check=True, timeout=30)
            
            # Écrire les fichiers cloud-init
            with open(user_data_file, 'w') as f:
                f.write(cloudinit_data['user_data'])
            with open(meta_data_file, 'w') as f:
                f.write(cloudinit_data['meta_data'])
            with open(network_config_file, 'w') as f:
                f.write(cloudinit_data['network_config'])
            
            logger.debug(f"Fichiers cloud-init créés")
            
            # Créer l'ISO seed avec network-config
            subprocess.run([
                "cloud-localds",
                "--network-config", network_config_file,
                seed_iso,
                user_data_file,
                meta_data_file
            ], check=True, timeout=30)
            
            logger.debug(f"ISO seed créé: {seed_iso}")
            
            # Copier l'ISO sur l'hôte distant si nécessaire
            if host_uri.startswith('qemu+ssh://'):
                ssh_host = host_uri.split('@')[1].split('/')[0]
                ssh_user = host_uri.split('//')[1].split('@')[0]
                remote_seed = f"{storage_path}/{vm_name}-seed.iso"
                
                logger.debug(f"Copie ISO vers {ssh_user}@{ssh_host}:{remote_seed}")
                
                subprocess.run([
                    "scp",
                    "-o", "StrictHostKeyChecking=no",
                    seed_iso,
                    f"{ssh_user}@{ssh_host}:{remote_seed}"
                ], check=True, timeout=30)
                
                seed_iso = remote_seed
            
            # Déterminer l'OS variant
            if 'ubuntu' in base_image:
                variant = "ubuntu22.04"
            elif 'debian' in base_image:
                variant = "debian11"
            else:
                variant = "generic"
            
            logger.debug(f"Déploiement avec virt-install: variant={variant}")
            
            # Déployer la VM avec virt-install
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
                f"--network=network={network},model=virtio",
                "--connect", host_uri
            ]
            
            logger.info(f"Commande virt-install: {' '.join(virt_install_cmd)}")
            
            result = subprocess.run(
                virt_install_cmd,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode == 0:
                logger.info(f"VM {vm_name} déployée avec succès")
                return True
            else:
                logger.error(f"Erreur virt-install: {result.stderr}")
                return False
            
        except subprocess.TimeoutExpired as e:
            logger.error(f"Timeout déploiement VM {vm_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Erreur déploiement VM {vm_name}: {e}", exc_info=True)
            return False
    
    @staticmethod
    def deploy_swarm_node(username: str, node_name: str, cluster_name: str,
                         node_type: str, ip_address: str, host_uri: str,
                         storage_path: str, password: str, ssh_key: str) -> bool:
        """Déploie un nœud Docker Swarm avec IP statique correcte"""
        
        full_vm_name = f"{username}_{node_name}"
        network_name = NetworkService.get_swarm_network_name(username, cluster_name)
        base_image = OS_IMAGES['ubuntu']
        
        logger.info(f"Déploiement nœud Swarm {full_vm_name} avec IP {ip_address}")
        
        # Générer cloud-init avec IP STATIQUE
        cloudinit_data = DeploymentService.generate_cloudinit(
            vm_name=full_vm_name,
            hostname=node_name,
            username=username,
            password=password,
            ssh_key=ssh_key,
            static_ip=ip_address  # IMPORTANT: IP statique pour Swarm
        )
        
        # Ajouter l'installation de Docker dans user_data
        docker_setup = f"""
packages:
  - qemu-guest-agent
  - net-tools
  - curl
  - vim
  - apt-transport-https
  - ca-certificates
  - gnupg
  - lsb-release

write_files:
  - path: /usr/local/bin/setup-docker.sh
    content: |
      #!/bin/bash
      set -e
      
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
      echo "Docker installé avec succès" > /var/log/docker-setup.log
    permissions: '0755'

runcmd:
  - systemctl enable qemu-guest-agent
  - systemctl start qemu-guest-agent
  - systemctl restart systemd-networkd
  - sleep 10
  - /usr/local/bin/setup-docker.sh
  - echo "Nœud Swarm prêt" > /var/lib/cloud/instance/boot-finished
"""
        
        # Remplacer {username} et fusionner avec user_data existant
        docker_setup = docker_setup.format(username=username)
        
        # Fusionner avec user_data
        user_data_lines = cloudinit_data['user_data'].split('\n')
        docker_lines = docker_setup.split('\n')
        
        # Trouver où insérer
        insert_idx = -1
        for i, line in enumerate(user_data_lines):
            if line.strip().startswith('package_update:'):
                insert_idx = i + 2
                break
        
        if insert_idx > 0:
            user_data_lines = user_data_lines[:insert_idx] + docker_lines[1:] + user_data_lines[insert_idx:]
        
        cloudinit_data['user_data'] = '\n'.join(user_data_lines)
        
        # Déployer la VM
        success = DeploymentService.deploy_vm(
            vm_name=full_vm_name,
            host_uri=host_uri,
            storage_path=storage_path,
            base_image=base_image,
            disk_size=30,
            vcpu=2,
            ram=4096,
            network=network_name,
            cloudinit_data=cloudinit_data
        )
        
        if success:
            logger.info(f"Nœud Swarm {full_vm_name} déployé avec IP {ip_address}")
        else:
            logger.error(f"Échec déploiement nœud Swarm {full_vm_name}")
        
        return success