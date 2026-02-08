# services/swarm_deployment_service.py - VERSION CORRIGÉE AVEC MODE MANUEL
import subprocess
import time
import os
from typing import Dict, Optional, Tuple
from config_logging import deployment_logger as logger

class SwarmDeploymentService:
    """
    Service pour déployer des applications sur Docker Swarm
    
    MODES DE FONCTIONNEMENT:
    1. MODE AUTO (par défaut) : Tente SSH + initialisation automatique
    2. MODE MANUEL : Assume que Swarm est déjà initialisé, skip la vérification SSH
    3. MODE PROXY : Utilise un proxy/bastion pour accéder aux VMs distantes
    """
    
    def __init__(self, mode='auto'):
        """
        Args:
            mode: 'auto', 'manual', ou 'proxy'
        """
        self.mode = mode
        self.ssh_bastion = None  # Pour le mode proxy
    
    @staticmethod
    def test_ssh_connection(manager_ip: str, username: str, timeout: int = 10, 
                           bastion: str = None) -> Tuple[bool, str]:
        """
        Teste la connexion SSH avant toute opération
        
        Args:
            manager_ip: IP du manager Swarm
            username: Utilisateur SSH
            timeout: Timeout en secondes
            bastion: IP du serveur bastion (optionnel) format "user@bastion_ip"
        
        Retourne (success, message)
        """
        logger.info(f"Test connexion SSH vers {username}@{manager_ip}")
        
        try:
            # Construire la commande SSH
            if bastion:
                # Mode bastion/proxy : ssh via ProxyJump
                logger.info(f"Utilisation du bastion: {bastion}")
                ssh_test_cmd = [
                    "ssh",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "BatchMode=yes",
                    "-o", f"ConnectTimeout={timeout}",
                    "-J", bastion,  # ProxyJump via le bastion
                    f"{username}@{manager_ip}",
                    "echo 'SSH_OK'"
                ]
            else:
                # Mode direct
                ssh_test_cmd = [
                    "ssh",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "BatchMode=yes",
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
                    return False, "❌ Erreur SSH: Permission refusée. Vérifiez les clés SSH."
                elif "Connection refused" in error_msg:
                    return False, "❌ Erreur SSH: Connexion refusée. SSH non démarré sur la VM."
                elif "No route to host" in error_msg:
                    return False, f"❌ Erreur réseau: Impossible de joindre {manager_ip}."
                elif "Connection reset" in error_msg or "kex_exchange" in error_msg:
                    return False, f"❌ Erreur SSH: Connexion réinitialisée. Le réseau {manager_ip} n'est probablement pas accessible depuis ce serveur."
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
    def init_swarm_if_needed(manager_ip: str, username: str, skip_check: bool = False,
                            bastion: str = None) -> Tuple[bool, str]:
        """
        Initialise Docker Swarm si nécessaire
        
        Args:
            skip_check: Si True, assume que Swarm est déjà initialisé (MODE MANUEL)
            bastion: Serveur bastion pour accès SSH (optionnel)
        
        Retourne (success, message)
        """
        if skip_check:
            logger.info(f"⚠️  MODE MANUEL: Skip vérification Swarm (assumé initialisé)")
            return True, "Swarm assumé actif (mode manuel)"
        
        logger.info(f"Vérification/Initialisation Swarm sur {manager_ip}")
        
        try:
            # D'ABORD: Tester SSH
            ssh_ok, ssh_msg = SwarmDeploymentService.test_ssh_connection(
                manager_ip, username, timeout=10, bastion=bastion
            )
            if not ssh_ok:
                return False, ssh_msg
            
            # Construire la commande de vérification
            check_cmd = [
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
            ]
            
            if bastion:
                check_cmd.extend(["-J", bastion])
            
            check_cmd.extend([
                f"{username}@{manager_ip}",
                "docker info --format '{{.Swarm.LocalNodeState}}'"
            ])
            
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
                ]
                
                if bastion:
                    init_cmd.extend(["-J", bastion])
                
                init_cmd.extend([
                    f"{username}@{manager_ip}",
                    f"sudo docker swarm init --advertise-addr {manager_ip}"
                ])
                
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
                        logger.info("Swarm déjà configuré")
                        return True, "Swarm déjà configuré"
                    
                    error = f"Erreur init Swarm: {result.stderr}"
                    logger.error(error)
                    return False, error
            else:
                error = f"Impossible de vérifier Docker: {result.stderr}"
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
    def check_swarm_ready(manager_ip: str, username: str, timeout: int = 30,
                         skip_init: bool = False, bastion: str = None) -> bool:
        """
        Vérifie que Docker Swarm est prêt
        
        Args:
            skip_init: Si True, ne tente PAS d'initialiser Swarm (MODE MANUEL)
            bastion: Serveur bastion pour accès SSH
        """
        logger.info(f"Vérification Swarm sur {manager_ip} (skip_init={skip_init})")
        
        # ÉTAPE 1: Initialiser si nécessaire (sauf en mode manuel)
        success, msg = SwarmDeploymentService.init_swarm_if_needed(
            manager_ip, username, skip_check=skip_init, bastion=bastion
        )
        
        if not success:
            logger.error(f"Impossible d'initialiser Swarm: {msg}")
            return False
        
        # Si mode manuel, on fait confiance
        if skip_init:
            logger.info("✓ Mode manuel: Swarm considéré comme prêt")
            return True
        
        # ÉTAPE 2: Vérifier que c'est bien actif
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                check_cmd = [
                    "ssh", "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=5",
                ]
                
                if bastion:
                    check_cmd.extend(["-J", bastion])
                
                check_cmd.extend([
                    f"{username}@{manager_ip}",
                    "docker info --format '{{.Swarm.LocalNodeState}}'"
                ])
                
                result = subprocess.run(
                    check_cmd,
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
                    compose_file_path: str, skip_swarm_check: bool = False,
                    bastion: str = None) -> Tuple[bool, str]:
        """
        Déploie une stack Docker Swarm
        
        Args:
            skip_swarm_check: Si True, ne vérifie PAS l'état Swarm (MODE MANUEL)
            bastion: Serveur bastion pour accès SSH
        
        Retourne (success, message/error)
        """
        logger.info(f"═══════════════════════════════════════════")
        logger.info(f"DÉPLOIEMENT STACK: {stack_name}")
        logger.info(f"Manager: {manager_ip}")
        logger.info(f"User: {username}")
        logger.info(f"Compose: {compose_file_path}")
        logger.info(f"Mode: {'MANUEL (skip checks)' if skip_swarm_check else 'AUTO'}")
        logger.info(f"Bastion: {bastion if bastion else 'Aucun'}")
        logger.info(f"═══════════════════════════════════════════")
        
        try:
            # ÉTAPE 0: TESTER SSH (sauf en mode manuel)
            if not skip_swarm_check:
                logger.info(f"[0/5] Test connexion SSH...")
                ssh_ok, ssh_msg = SwarmDeploymentService.test_ssh_connection(
                    manager_ip, username, timeout=10, bastion=bastion
                )
                
                if not ssh_ok:
                    logger.error(f"[0/5] ✗ {ssh_msg}")
                    
                    # Message d'aide spécifique
                    help_msg = f"""
┌─────────────────────────────────────────────────────────────┐
│ ❌ CONNEXION SSH IMPOSSIBLE                                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ L'IP {manager_ip} n'est pas accessible depuis ce serveur.  │
│                                                             │
│ SOLUTIONS POSSIBLES:                                        │
│                                                             │
│ 1️⃣  MODE MANUEL (recommandé pour pool KVM distant)         │
│    → Activer skip_swarm_check=True                         │
│    → Initialiser Swarm manuellement sur la VM              │
│    → Les stacks seront déployées en mode "confiance"       │
│                                                             │
│ 2️⃣  MODE BASTION (si vous avez accès via un serveur)       │
│    → Configurer un serveur bastion/jumphost                │
│    → Utiliser bastion="user@bastion_ip"                    │
│                                                             │
│ 3️⃣  TUNNEL SSH (pour accès temporaire)                     │
│    → Créer un tunnel: ssh -L 2222:{manager_ip}:22 bastion  │
│    → Utiliser localhost:2222 comme manager_ip              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
"""
                    logger.info(help_msg)
                    return False, f"{ssh_msg}\n\nVoir les logs pour les solutions possibles."
                
                logger.info(f"[0/5] ✓ SSH OK")
            else:
                logger.info(f"[0/5] ⚠️  MODE MANUEL: Skip test SSH")
            
            # ÉTAPE 1: Vérifier le fichier compose existe
            logger.info(f"[1/5] Vérification fichier compose...")
            
            if not os.path.exists(compose_file_path):
                error = f"❌ Fichier compose non trouvé: {compose_file_path}"
                logger.error(error)
                return False, error
            
            logger.info(f"[1/5] ✓ Fichier compose trouvé")
            
            # ÉTAPE 2: Copier le fichier sur le manager (avec bastion si nécessaire)
            logger.info(f"[2/5] Copie du fichier compose sur le manager...")
            remote_compose_path = f"/tmp/{stack_name}-compose.yml"
            
            if bastion:
                # Copie via bastion en 2 étapes
                logger.info(f"Copie via bastion {bastion}")
                
                # Étape 1: Copier sur le bastion
                scp_to_bastion = [
                    "scp",
                    "-o", "StrictHostKeyChecking=no",
                    compose_file_path,
                    f"{bastion}:/tmp/{stack_name}-compose.yml"
                ]
                
                result = subprocess.run(
                    scp_to_bastion,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode != 0:
                    error = f"❌ Erreur copie vers bastion: {result.stderr}"
                    logger.error(error)
                    return False, error
                
                # Étape 2: Copier du bastion vers le manager
                scp_to_manager = [
                    "ssh",
                    "-o", "StrictHostKeyChecking=no",
                    bastion,
                    f"scp /tmp/{stack_name}-compose.yml {username}@{manager_ip}:{remote_compose_path}"
                ]
                
                result = subprocess.run(
                    scp_to_manager,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
            else:
                # Copie directe
                scp_cmd = [
                    "scp",
                    "-o", "StrictHostKeyChecking=no",
                    compose_file_path,
                    f"{username}@{manager_ip}:{remote_compose_path}"
                ]
                
                result = subprocess.run(
                    scp_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
            
            if result.returncode != 0:
                error = f"❌ Erreur copie fichier compose: {result.stderr}"
                logger.error(error)
                return False, error
            
            logger.info(f"[2/5] ✓ Fichier copié sur le manager")
            
            # ÉTAPE 3: Vérifier que Swarm est actif (sauf en mode manuel)
            if not skip_swarm_check:
                logger.info(f"[3/5] Vérification Swarm...")
                
                swarm_ok = SwarmDeploymentService.check_swarm_ready(
                    manager_ip, username, timeout=30,
                    skip_init=False, bastion=bastion
                )
                
                if not swarm_ok:
                    error = "❌ Swarm non prêt"
                    logger.error(error)
                    return False, error
                
                logger.info(f"[3/5] ✓ Swarm actif")
            else:
                logger.info(f"[3/5] ⚠️  MODE MANUEL: Skip vérification Swarm")
            
            # ÉTAPE 4: Déployer la stack
            logger.info(f"[4/5] Déploiement de la stack...")
            
            deploy_cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
            ]
            
            if bastion:
                deploy_cmd.extend(["-J", bastion])
            
            deploy_cmd.extend([
                f"{username}@{manager_ip}",
                f"docker stack deploy -c {remote_compose_path} {stack_name}"
            ])
            
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
                
                # ÉTAPE 5: Vérifier les services déployés (optionnel en mode manuel)
                logger.info(f"[5/5] Vérification des services...")
                
                check_cmd = [
                    "ssh",
                    "-o", "StrictHostKeyChecking=no",
                ]
                
                if bastion:
                    check_cmd.extend(["-J", bastion])
                
                check_cmd.extend([
                    f"{username}@{manager_ip}",
                    f"docker stack services {stack_name}"
                ])
                
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
    def get_stack_status(manager_ip: str, username: str, stack_name: str,
                        bastion: str = None) -> Optional[Dict]:
        """Récupère le statut d'une stack"""
        logger.debug(f"Récupération statut stack {stack_name}")
        
        try:
            cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
            ]
            
            if bastion:
                cmd.extend(["-J", bastion])
            
            cmd.extend([
                f"{username}@{manager_ip}",
                f"docker stack services {stack_name} --format '{{{{.Name}}}}|{{{{.Replicas}}}}|{{{{.Image}}}}'"
            ])
            
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
    def remove_stack(manager_ip: str, username: str, stack_name: str,
                    bastion: str = None) -> Tuple[bool, str]:
        """Supprime une stack Docker Swarm"""
        logger.info(f"Suppression stack {stack_name} sur {manager_ip}")
        
        try:
            cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
            ]
            
            if bastion:
                cmd.extend(["-J", bastion])
            
            cmd.extend([
                f"{username}@{manager_ip}",
                f"docker stack rm {stack_name}"
            ])
            
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
                        lines: int = 50, bastion: str = None) -> Optional[str]:
        """Récupère les logs d'un service"""
        try:
            cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
            ]
            
            if bastion:
                cmd.extend(["-J", bastion])
            
            cmd.extend([
                f"{username}@{manager_ip}",
                f"docker service logs {service_name} --tail {lines}"
            ])
            
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
                     replicas: int, bastion: str = None) -> Tuple[bool, str]:
        """Scale un service"""
        logger.info(f"Scale service {service_name} à {replicas} replicas")
        
        try:
            cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
            ]
            
            if bastion:
                cmd.extend(["-J", bastion])
            
            cmd.extend([
                f"{username}@{manager_ip}",
                f"docker service scale {service_name}={replicas}"
            ])
            
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