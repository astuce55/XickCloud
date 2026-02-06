# services/swarm_deployment_service.py - VERSION CORRIGÉE AVEC MEILLEURE GESTION SSH
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
    def test_ssh_connection(manager_ip: str, username: str, timeout: int = 10) -> Tuple[bool, str]:
        """
        Teste la connexion SSH avant toute opération
        Retourne (success, message)
        """
        logger.info(f"Test connexion SSH vers {username}@{manager_ip}")
        
        try:
            ssh_test_cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "BatchMode=yes",  # Pas de prompt interactif
                "-o", f"ConnectTimeout={timeout}",
                f"{username}@{manager_ip}",
                "echo 'SSH_OK'"
            ]
            
            result = subprocess.run(
                ssh_test_cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 5
            )
            
            if result.returncode == 0 and "SSH_OK" in result.stdout:
                logger.info(f"✓ Connexion SSH OK vers {manager_ip}")
                return True, "Connexion SSH réussie"
            else:
                error_msg = result.stderr.strip()
                logger.error(f"Connexion SSH échouée: {error_msg}")
                
                # Messages d'erreur spécifiques
                if "Permission denied" in error_msg:
                    return False, "❌ Erreur SSH: Permission refusée. Les clés SSH ne sont pas configurées. Veuillez vous assurer que la clé publique du serveur est dans ~/.ssh/authorized_keys de la VM."
                elif "Connection refused" in error_msg:
                    return False, "❌ Erreur SSH: Connexion refusée. Le serveur SSH n'est peut-être pas démarré sur la VM."
                elif "No route to host" in error_msg:
                    return False, f"❌ Erreur SSH: Impossible de joindre {manager_ip}. Vérifiez l'IP et le réseau."
                elif "Host key verification failed" in error_msg:
                    return False, "❌ Erreur SSH: Vérification de clé d'hôte échouée."
                else:
                    return False, f"❌ Erreur SSH: {error_msg}"
                    
        except subprocess.TimeoutExpired:
            error = f"❌ Timeout connexion SSH ({timeout}s)"
            logger.error(error)
            return False, error
        except Exception as e:
            error = f"❌ Erreur test SSH: {str(e)}"
            logger.error(error, exc_info=True)
            return False, error
    
    @staticmethod
    def init_swarm_if_needed(manager_ip: str, username: str) -> Tuple[bool, str]:
        """
        Initialise Docker Swarm si nécessaire
        Retourne (success, message)
        """
        logger.info(f"Vérification/Initialisation Swarm sur {manager_ip}")
        
        try:
            # D'ABORD: Tester SSH
            ssh_ok, ssh_msg = SwarmDeploymentService.test_ssh_connection(manager_ip, username, timeout=10)
            if not ssh_ok:
                return False, ssh_msg
            
            # Vérifier si Swarm est déjà actif
            check_cmd = [
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
                f"{username}@{manager_ip}",
                "docker info --format '{{.Swarm.LocalNodeState}}'"
            ]
            
            result = subprocess.run(
                check_cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                state = result.stdout.strip()
                logger.debug(f"État Swarm actuel: {state}")
                
                if state == "active":
                    logger.info("✓ Swarm déjà actif")
                    return True, "Swarm actif"
                
                # Swarm pas actif, initialiser
                logger.info("Initialisation de Docker Swarm...")
                init_cmd = [
                    "ssh", "-o", "StrictHostKeyChecking=no",
                    f"{username}@{manager_ip}",
                    f"sudo docker swarm init --advertise-addr {manager_ip}"
                ]
                
                result = subprocess.run(
                    init_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    logger.info("✓ Swarm initialisé avec succès")
                    return True, "Swarm initialisé"
                else:
                    # Peut-être déjà dans un swarm
                    if "already part of a swarm" in result.stderr.lower():
                        logger.info("Swarm déjà configuré (était dans un cluster)")
                        return True, "Swarm déjà configuré"
                    
                    error = f"Erreur init Swarm: {result.stderr}"
                    logger.error(error)
                    return False, error
            else:
                error = f"Impossible de vérifier l'état Docker: {result.stderr}"
                logger.error(error)
                return False, error
        
        except subprocess.TimeoutExpired:
            error = "Timeout lors de l'initialisation Swarm"
            logger.error(error)
            return False, error
        except Exception as e:
            error = f"Erreur inattendue: {str(e)}"
            logger.error(error, exc_info=True)
            return False, error
    
    @staticmethod
    def check_swarm_ready(manager_ip: str, username: str, timeout: int = 30) -> bool:
        """
        Vérifie que Docker Swarm est prêt - avec auto-initialisation
        """
        logger.info(f"Vérification Swarm sur {manager_ip}")
        
        # ÉTAPE 1: Initialiser si nécessaire
        success, msg = SwarmDeploymentService.init_swarm_if_needed(manager_ip, username)
        
        if not success:
            logger.error(f"Impossible d'initialiser Swarm: {msg}")
            return False
        
        # ÉTAPE 2: Vérifier que c'est bien actif
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
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
                        logger.info(f"✓ Swarm actif sur {manager_ip}")
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
        Déploie une stack Docker Swarm - VERSION AVEC MEILLEURE GESTION SSH
        Retourne (success, message/error)
        """
        logger.info(f"═══════════════════════════════════════════")
        logger.info(f"DÉPLOIEMENT STACK: {stack_name}")
        logger.info(f"Manager: {manager_ip}")
        logger.info(f"User: {username}")
        logger.info(f"Compose: {compose_file_path}")
        logger.info(f"═══════════════════════════════════════════")
        
        try:
            # ÉTAPE 0: TESTER SSH EN PREMIER
            logger.info(f"[0/5] Test connexion SSH...")
            ssh_ok, ssh_msg = SwarmDeploymentService.test_ssh_connection(manager_ip, username, timeout=15)
            
            if not ssh_ok:
                logger.error(f"Test SSH échoué: {ssh_msg}")
                return False, ssh_msg
            
            logger.info(f"[0/5] ✓ Connexion SSH OK")
            
            # ÉTAPE 1: Vérifier que le fichier compose existe
            if not os.path.exists(compose_file_path):
                error = f"Fichier compose introuvable: {compose_file_path}"
                logger.error(error)
                return False, error
            
            logger.info(f"[1/5] ✓ Fichier compose existe")
            
            # Lire et afficher le contenu pour debug
            with open(compose_file_path, 'r') as f:
                compose_content = f.read()
                logger.debug(f"Contenu du compose ({len(compose_content)} chars):\n{compose_content[:500]}...")
            
            # ÉTAPE 2: Copier le compose sur le manager
            remote_compose = f"/tmp/{stack_name}-compose.yml"
            
            scp_cmd = [
                "scp",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=15",
                compose_file_path,
                f"{username}@{manager_ip}:{remote_compose}"
            ]
            
            logger.info(f"[2/5] Copie compose vers {manager_ip}:{remote_compose}")
            logger.debug(f"Commande SCP: {' '.join(scp_cmd)}")
            
            result = subprocess.run(
                scp_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip()
                logger.error(f"Erreur copie compose (SCP): {error_msg}")
                
                # Analyser l'erreur SCP
                if "Permission denied" in error_msg:
                    return False, "❌ SCP échoué: Permission refusée. Vérifiez les clés SSH."
                elif "No such file or directory" in error_msg:
                    return False, f"❌ SCP échoué: Impossible de créer {remote_compose} sur la VM."
                else:
                    return False, f"❌ Erreur SCP: {error_msg}"
            
            logger.info(f"[2/5] ✓ Compose copié")
            
            # ÉTAPE 3: Vérifier que le fichier a bien été copié
            verify_cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                f"{username}@{manager_ip}",
                f"test -f {remote_compose} && echo 'OK' || echo 'NOT FOUND'"
            ]
            
            result = subprocess.run(
                verify_cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if "OK" not in result.stdout:
                error = f"Fichier non trouvé sur le serveur distant après copie"
                logger.error(error)
                return False, error
            
            logger.info(f"[3/5] ✓ Fichier vérifié sur le serveur")
            
            # ÉTAPE 4: Déployer la stack
            deploy_cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
                f"{username}@{manager_ip}",
                f"docker stack deploy -c {remote_compose} {stack_name}"
            ]
            
            logger.info(f"[4/5] Déploiement de la stack...")
            logger.debug(f"Commande: {' '.join(deploy_cmd)}")
            
            result = subprocess.run(
                deploy_cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                logger.info(f"[4/5] ✓ Stack {stack_name} déployée avec succès")
                logger.info(f"Output Docker Stack:\n{result.stdout}")
                
                # ÉTAPE 5: Vérifier les services déployés
                logger.info(f"[5/5] Vérification des services...")
                
                check_cmd = [
                    "ssh",
                    "-o", "StrictHostKeyChecking=no",
                    f"{username}@{manager_ip}",
                    f"docker stack services {stack_name}"
                ]
                
                check_result = subprocess.run(
                    check_cmd,
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                
                if check_result.returncode == 0:
                    logger.info(f"Services de la stack:\n{check_result.stdout}")
                else:
                    logger.warning(f"Impossible de lister les services: {check_result.stderr}")
                
                logger.info(f"[5/5] ✓ Déploiement terminé")
                return True, f"Stack {stack_name} déployée avec succès"
            else:
                error = f"❌ Erreur déploiement Docker Stack:\n{result.stderr}"
                logger.error(error)
                return False, error
            
        except subprocess.TimeoutExpired:
            error = "❌ Timeout lors du déploiement (>60s)"
            logger.error(error)
            return False, error
        except Exception as e:
            error = f"❌ Erreur inattendue: {str(e)}"
            logger.error(error, exc_info=True)
            return False, error
        finally:
            logger.info(f"═══════════════════════════════════════════")
    
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
                logger.info(f"✓ Stack {stack_name} supprimée")
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
                logger.info(f"✓ Service {service_name} scalé à {replicas}")
                return True, f"Service scalé à {replicas} replicas"
            else:
                error = f"Erreur scale: {result.stderr}"
                logger.error(error)
                return False, error
            
        except Exception as e:
            error = f"Erreur: {str(e)}"
            logger.error(error)
            return False, error