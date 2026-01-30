# services/swarm_deployment_service.py - NOUVEAU FICHIER
import subprocess
import time
import os
from typing import Dict, Optional, Tuple
from config_logging import deployment_logger as logger

class SwarmDeploymentService:
    """Service pour déployer des applications sur Docker Swarm"""
    
    def __init__(self):
        pass
    
    @staticmethod
    def check_swarm_ready(manager_ip: str, username: str, timeout: int = 30) -> bool:
        """Vérifie que le cluster Swarm est prêt"""
        logger.info(f"Vérification Swarm sur {manager_ip}")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Vérifier si Docker est accessible
                cmd = f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 {username}@{manager_ip} 'docker info --format \"{{{{.Swarm.LocalNodeState}}}}\"'"
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    state = result.stdout.strip()
                    if state == "active":
                        logger.info(f"Swarm actif sur {manager_ip}")
                        return True
                    else:
                        logger.debug(f"Swarm state: {state}, attente...")
                
            except subprocess.TimeoutExpired:
                logger.debug(f"Timeout vérification Swarm, retry...")
            except Exception as e:
                logger.debug(f"Erreur vérification Swarm: {e}")
            
            time.sleep(5)
        
        logger.warning(f"Swarm non prêt après {timeout}s")
        return False
    
    @staticmethod
    def deploy_stack(manager_ip: str, username: str, stack_name: str, 
                    compose_file_path: str) -> Tuple[bool, str]:
        """
        Déploie une stack Docker Swarm
        Retourne (success, message/error)
        """
        logger.info(f"Déploiement stack {stack_name} sur {manager_ip}")
        
        try:
            # Vérifier que le fichier compose existe
            if not os.path.exists(compose_file_path):
                error = f"Fichier compose introuvable: {compose_file_path}"
                logger.error(error)
                return False, error
            
            # Lire le contenu du compose
            with open(compose_file_path, 'r') as f:
                compose_content = f.read()
            
            # Copier le compose sur le manager
            remote_compose = f"/tmp/{stack_name}-compose.yml"
            
            # Utiliser scp pour copier le fichier
            scp_cmd = [
                "scp",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
                compose_file_path,
                f"{username}@{manager_ip}:{remote_compose}"
            ]
            
            logger.debug(f"Copie compose vers {manager_ip}:{remote_compose}")
            result = subprocess.run(
                scp_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                error = f"Erreur copie compose: {result.stderr}"
                logger.error(error)
                return False, error
            
            # Déployer la stack
            deploy_cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
                f"{username}@{manager_ip}",
                f"docker stack deploy -c {remote_compose} {stack_name}"
            ]
            
            logger.debug(f"Déploiement stack: {' '.join(deploy_cmd)}")
            result = subprocess.run(
                deploy_cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                logger.info(f"Stack {stack_name} déployée avec succès")
                return True, result.stdout
            else:
                error = f"Erreur déploiement: {result.stderr}"
                logger.error(error)
                return False, error
            
        except subprocess.TimeoutExpired:
            error = "Timeout lors du déploiement"
            logger.error(error)
            return False, error
        except Exception as e:
            error = f"Erreur inattendue: {str(e)}"
            logger.error(error, exc_info=True)
            return False, error
    
    @staticmethod
    def get_stack_status(manager_ip: str, username: str, stack_name: str) -> Optional[Dict]:
        """Récupère le statut d'une stack"""
        logger.debug(f"Récupération statut stack {stack_name}")
        
        try:
            # Lister les services de la stack
            cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
                f"{username}@{manager_ip}",
                f"docker stack services {stack_name} --format '{{{{.Name}}}}|{{{{.Replicas}}}}|{{{{.Image}}}}'"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode != 0:
                logger.warning(f"Impossible de récupérer statut stack {stack_name}")
                return None
            
            services = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split('|')
                    if len(parts) == 3:
                        name, replicas, image = parts
                        services.append({
                            'name': name,
                            'replicas': replicas,
                            'image': image
                        })
            
            # Compter les services running
            total_services = len(services)
            running_services = sum(1 for s in services if '/' in s['replicas'] and 
                                  s['replicas'].split('/')[0] == s['replicas'].split('/')[1])
            
            return {
                'stack_name': stack_name,
                'total_services': total_services,
                'running_services': running_services,
                'services': services,
                'status': 'running' if running_services == total_services else 'partial'
            }
            
        except Exception as e:
            logger.error(f"Erreur récupération statut: {e}", exc_info=True)
            return None
    
    @staticmethod
    def remove_stack(manager_ip: str, username: str, stack_name: str) -> Tuple[bool, str]:
        """Supprime une stack Docker Swarm"""
        logger.info(f"Suppression stack {stack_name} sur {manager_ip}")
        
        try:
            cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
                f"{username}@{manager_ip}",
                f"docker stack rm {stack_name}"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                logger.info(f"Stack {stack_name} supprimée")
                return True, "Stack supprimée avec succès"
            else:
                error = f"Erreur suppression: {result.stderr}"
                logger.error(error)
                return False, error
            
        except Exception as e:
            error = f"Erreur: {str(e)}"
            logger.error(error, exc_info=True)
            return False, error
    
    @staticmethod
    def get_stack_services(manager_ip: str, username: str, stack_name: str) -> list:
        """Liste les services d'une stack"""
        try:
            cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
                f"{username}@{manager_ip}",
                f"docker stack ps {stack_name} --format '{{{{.Name}}}}|{{{{.CurrentState}}}}|{{{{.Node}}}}'"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode != 0:
                return []
            
            tasks = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split('|')
                    if len(parts) == 3:
                        tasks.append({
                            'name': parts[0],
                            'state': parts[1],
                            'node': parts[2]
                        })
            
            return tasks
            
        except Exception as e:
            logger.error(f"Erreur liste services: {e}")
            return []
    
    @staticmethod
    def get_service_logs(manager_ip: str, username: str, service_name: str, 
                        lines: int = 50) -> Optional[str]:
        """Récupère les logs d'un service"""
        try:
            cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
                f"{username}@{manager_ip}",
                f"docker service logs {service_name} --tail {lines}"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=20
            )
            
            if result.returncode == 0:
                return result.stdout
            else:
                return None
            
        except Exception as e:
            logger.error(f"Erreur récupération logs: {e}")
            return None
    
    @staticmethod
    def scale_service(manager_ip: str, username: str, service_name: str, 
                     replicas: int) -> Tuple[bool, str]:
        """Scale un service"""
        logger.info(f"Scale service {service_name} à {replicas} replicas")
        
        try:
            cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
                f"{username}@{manager_ip}",
                f"docker service scale {service_name}={replicas}"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                logger.info(f"Service {service_name} scalé à {replicas}")
                return True, f"Service scalé à {replicas} replicas"
            else:
                error = f"Erreur scale: {result.stderr}"
                logger.error(error)
                return False, error
            
        except Exception as e:
            error = f"Erreur: {str(e)}"
            logger.error(error)
            return False, error