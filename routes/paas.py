# routes/paas.py - VERSION CORRIGÉE AVEC MODE MANUEL POUR POOL KVM DISTANT
from flask import Blueprint, render_template, request, jsonify, session
import time
import secrets
from config import PaaS_CATALOG, BILLING_RATES, SWARM_DEPLOYMENT_MODE, SKIP_SWARM_INIT, SWARM_BASTION_HOST
from models.storage import StorageManager
from models.swarm import SwarmManager
from services.docker_compose_generator import DockerComposeGenerator
from services.swarm_deployment_service import SwarmDeploymentService
from routes.auth import login_required
from config_logging import paas_logger as logger

paas_bp = Blueprint('paas', __name__)
storage = StorageManager()
swarm_manager = SwarmManager()
compose_gen = DockerComposeGenerator()
swarm_deploy = SwarmDeploymentService()

@paas_bp.route('/paas')
@login_required
def index():
    """Catalogue d'applications PaaS"""
    username = session['username']
    
    # Récupérer les applications déployées
    apps = storage.load_apps()
    user_apps = [app for app in apps.values() if app.get('owner') == username]
    
    # Récupérer les clusters Swarm de l'utilisateur
    clusters = swarm_manager.get_user_clusters(username)
    
    # Informations de configuration pour l'interface
    deployment_info = {
        'mode': SWARM_DEPLOYMENT_MODE,
        'skip_init': SKIP_SWARM_INIT,
        'bastion': SWARM_BASTION_HOST
    }
    
    return render_template('paas.html', 
                         username=username,
                         catalog=PaaS_CATALOG,
                         apps=user_apps,
                         clusters=clusters,
                         deployment_info=deployment_info)

@paas_bp.route('/api/paas/catalog', methods=['GET'])
@login_required
def get_catalog():
    """API pour récupérer le catalogue d'applications"""
    return jsonify(PaaS_CATALOG)

@paas_bp.route('/api/paas/apps', methods=['GET'])
@login_required
def get_apps():
    """API pour récupérer les applications déployées"""
    username = session['username']
    apps = storage.load_apps()
    user_apps = {k: v for k, v in apps.items() if v.get('owner') == username}
    
    logger.info(f"Récupération apps pour {username}: {len(user_apps)} apps")
    return jsonify(user_apps)

@paas_bp.route('/api/paas/deploy', methods=['POST'])
@login_required
def deploy_app():
    """
    API pour déployer une application - VERSION AVEC MODE MANUEL
    
    IMPORTANT: Cette version utilise les paramètres de config.py:
    - SWARM_DEPLOYMENT_MODE: 'auto', 'manual', ou 'bastion'
    - SKIP_SWARM_INIT: True pour pool KVM distant
    - SWARM_BASTION_HOST: IP du bastion si mode 'bastion'
    """
    username = session['username']
    data = request.json
    
    try:
        app_id = data.get('app_id')
        app_name = data.get('app_name', f"{app_id}-{username}").lower().replace(' ', '-')
        cluster_name = data.get('cluster_name')
        db_password = data.get('db_password', secrets.token_urlsafe(16))
        
        logger.info(f"═══════════════════════════════════════════")
        logger.info(f"DÉPLOIEMENT APPLICATION PaaS")
        logger.info(f"App: {app_id} ({app_name})")
        logger.info(f"Cluster: {cluster_name}")
        logger.info(f"User: {username}")
        logger.info(f"Mode: {SWARM_DEPLOYMENT_MODE}")
        logger.info(f"Skip Init: {SKIP_SWARM_INIT}")
        logger.info(f"═══════════════════════════════════════════")
        
        # Validation
        if not app_id or app_id not in PaaS_CATALOG:
            return jsonify({'success': False, 'msg': 'Application invalide'}), 400
        
        if not cluster_name:
            return jsonify({'success': False, 'msg': 'Cluster requis'}), 400
        
        # Vérifier que le cluster existe et appartient à l'utilisateur
        cluster = swarm_manager.get_cluster(cluster_name)
        if not cluster:
            return jsonify({'success': False, 'msg': 'Cluster non trouvé'}), 404
        
        if cluster.get('owner') != username:
            return jsonify({'success': False, 'msg': 'Cluster non autorisé'}), 403
        
        # Vérifier que le cluster est prêt
        if cluster.get('status') != 'ready' and cluster.get('status') != 'deployed':
            return jsonify({'success': False, 'msg': 'Cluster non prêt'}), 400
        
        app_info = PaaS_CATALOG[app_id]
        manager_ip = cluster.get('manager_ip')
        
        if not manager_ip:
            return jsonify({
                'success': False, 
                'msg': 'Manager IP non trouvée. Veuillez rafraîchir les IPs du cluster.'
            }), 500
        
        # Générer un ID unique pour l'application
        app_uuid = f"{app_id}-{username}-{int(time.time())}"
        stack_name = app_name.replace('_', '-')  # Docker Stack ne supporte pas _
        
        # ÉTAPE 1: Vérifier Swarm (avec config depuis config.py)
        logger.info(f"Vérification Swarm sur {manager_ip} (mode: {SWARM_DEPLOYMENT_MODE})")
        
        if SWARM_DEPLOYMENT_MODE == 'manual' or SKIP_SWARM_INIT:
            logger.info(f"⚠️  MODE MANUEL: Skip vérification Swarm (assumé initialisé)")
            logger.info(f"")
            logger.info(f"RAPPEL: Vous devez avoir initialisé Swarm manuellement avec:")
            logger.info(f"  1. Se connecter à la VM manager: ssh {username}@{manager_ip}")
            logger.info(f"  2. Initialiser Swarm: sudo docker swarm init --advertise-addr {manager_ip}")
            logger.info(f"")
        else:
            # Mode auto ou bastion: vérifier Swarm
            bastion = SWARM_BASTION_HOST if SWARM_DEPLOYMENT_MODE == 'bastion' else None
            
            if not swarm_deploy.check_swarm_ready(
                manager_ip, username, timeout=30,
                skip_init=SKIP_SWARM_INIT,
                bastion=bastion
            ):
                error_msg = 'Cluster Swarm non prêt'
                
                if SWARM_DEPLOYMENT_MODE == 'auto':
                    error_msg += '\n\nAssurez-vous que:\n'
                    error_msg += f'- La VM {manager_ip} est accessible en SSH\n'
                    error_msg += f'- Docker est installé sur la VM\n'
                    error_msg += f'- Les clés SSH sont configurées\n'
                
                return jsonify({'success': False, 'msg': error_msg}), 503
        
        # ÉTAPE 2: Générer le docker-compose.yml
        logger.info(f"Génération docker-compose pour {app_id}")
        compose_file = compose_gen.generate_compose(app_id, stack_name, db_password)
        
        if not compose_file:
            return jsonify({'success': False, 'msg': 'Erreur génération compose'}), 500
        
        # ÉTAPE 3: Déployer sur Swarm (avec config depuis config.py)
        logger.info(f"Déploiement stack {stack_name} sur Swarm")
        
        bastion = SWARM_BASTION_HOST if SWARM_DEPLOYMENT_MODE == 'bastion' else None
        
        success, message = swarm_deploy.deploy_stack(
            manager_ip=manager_ip,
            username=username,
            stack_name=stack_name,
            compose_file_path=compose_file,
            skip_swarm_check=SKIP_SWARM_INIT,  # Mode manuel = skip checks
            bastion=bastion
        )
        
        if not success:
            logger.error(f"Échec déploiement: {message}")
            
            # Message d'aide en cas d'erreur
            help_message = f"\n\n{message}"
            
            if "SSH" in message or "Connection reset" in message:
                help_message += "\n\n💡 SOLUTIONS:\n"
                help_message += "1. Vérifiez que vous avez bien initialisé Swarm manuellement\n"
                help_message += f"2. Connectez-vous à la VM: ssh {username}@{manager_ip}\n"
                help_message += f"3. Exécutez: sudo docker swarm init --advertise-addr {manager_ip}\n"
                help_message += "4. Vérifiez que Docker est actif: sudo docker info\n"
            
            return jsonify({'success': False, 'msg': help_message}), 500
        
        # ÉTAPE 4: Enregistrer l'application
        apps = storage.load_apps()
        apps[app_uuid] = {
            'id': app_uuid,
            'app_id': app_id,
            'name': app_name,
            'stack_name': stack_name,
            'owner': username,
            'deployed_at': time.time(),
            'status': 'deployed',
            'cluster': cluster_name,
            'manager_ip': manager_ip,
            'info': app_info,
            'url': f"http://{manager_ip}",
            'port': app_info.get('port', 80),
            'db_password': db_password,
            'deployment_mode': SWARM_DEPLOYMENT_MODE,
            'billing': {
                'rate': BILLING_RATES['app_deployment'],
                'start_time': time.time()
            }
        }
        
        storage.save_apps(apps)
        
        # ÉTAPE 5: Enregistrer la facturation
        billing = storage.load_billing()
        if username not in billing:
            billing[username] = {'apps': []}
        
        billing[username]['apps'].append({
            'app_id': app_uuid,
            'name': app_name,
            'start_time': time.time(),
            'rate': BILLING_RATES['app_deployment']
        })
        
        storage.save_billing(billing)
        
        logger.info(f"✓ Application {app_name} déployée avec succès")
        logger.info(f"═══════════════════════════════════════════")
        
        # Message de succès avec instructions
        success_msg = f'Application {app_info["name"]} déployée avec succès'
        
        if SWARM_DEPLOYMENT_MODE == 'manual':
            success_msg += f'\n\nPour vérifier le déploiement:\n'
            success_msg += f'  ssh {username}@{manager_ip}\n'
            success_msg += f'  sudo docker stack services {stack_name}\n'
        
        return jsonify({
            'success': True,
            'app': apps[app_uuid],
            'message': success_msg,
            'access_url': f'http://{manager_ip}:{app_info.get("port", 80)}',
            'credentials': {
                'db_password': db_password
            } if 'db_type' in app_info and app_info['db_type'] != 'none' else {}
        })
        
    except Exception as e:
        logger.error(f"Erreur déploiement app: {e}", exc_info=True)
        return jsonify({'success': False, 'msg': f'Erreur: {str(e)}'}), 500

@paas_bp.route('/api/paas/app/<app_id>', methods=['DELETE'])
@login_required
def delete_app(app_id):
    """API pour supprimer une application"""
    username = session['username']
    apps = storage.load_apps()
    
    if app_id not in apps:
        return jsonify({'success': False, 'msg': 'Application non trouvée'}), 404
    
    app = apps[app_id]
    
    if app.get('owner') != username:
        return jsonify({'success': False, 'msg': 'Non autorisé'}), 403
    
    logger.info(f"Suppression app {app_id} par {username}")
    
    # Supprimer la stack sur Swarm
    manager_ip = app.get('manager_ip')
    stack_name = app.get('stack_name')
    
    if manager_ip and stack_name:
        bastion = SWARM_BASTION_HOST if SWARM_DEPLOYMENT_MODE == 'bastion' else None
        
        success, message = swarm_deploy.remove_stack(
            manager_ip, username, stack_name, bastion=bastion
        )
        
        if not success:
            logger.warning(f"Erreur suppression stack: {message}")
            
            # En mode manuel, proposer la commande
            if SWARM_DEPLOYMENT_MODE == 'manual':
                manual_cmd = f"ssh {username}@{manager_ip} 'sudo docker stack rm {stack_name}'"
                return jsonify({
                    'success': False,
                    'msg': f'Erreur suppression stack.\n\nSupprimez manuellement:\n{manual_cmd}'
                }), 500
    
    # Supprimer de la base
    del apps[app_id]
    storage.save_apps(apps)
    
    logger.info(f"Application {app_id} supprimée")
    
    return jsonify({'success': True, 'msg': 'Application supprimée'})

@paas_bp.route('/api/paas/app/<app_id>/status', methods=['GET'])
@login_required
def get_app_status(app_id):
    """Récupère le statut d'une application"""
    username = session['username']
    apps = storage.load_apps()
    
    if app_id not in apps:
        return jsonify({'success': False, 'msg': 'Application non trouvée'}), 404
    
    app = apps[app_id]
    
    if app.get('owner') != username:
        return jsonify({'success': False, 'msg': 'Non autorisé'}), 403
    
    manager_ip = app.get('manager_ip')
    stack_name = app.get('stack_name')
    
    if not manager_ip or not stack_name:
        return jsonify({
            'success': True,
            'status': app.get('status', 'unknown')
        })
    
    # Récupérer le statut réel depuis Swarm
    bastion = SWARM_BASTION_HOST if SWARM_DEPLOYMENT_MODE == 'bastion' else None
    
    status = swarm_deploy.get_stack_status(manager_ip, username, stack_name, bastion=bastion)
    
    if status:
        # Mettre à jour le statut dans la base
        apps[app_id]['status'] = status['status']
        apps[app_id]['services'] = status['services']
        storage.save_apps(apps)
        
        return jsonify({
            'success': True,
            'status': status['status'],
            'services': status['services'],
            'total_services': status['total_services'],
            'running_services': status['running_services']
        })
    else:
        # En mode manuel, proposer la commande
        manual_note = ""
        if SWARM_DEPLOYMENT_MODE == 'manual':
            manual_note = f"\n\nVérifiez manuellement:\nssh {username}@{manager_ip} 'sudo docker stack services {stack_name}'"
        
        return jsonify({
            'success': True,
            'status': 'unknown',
            'msg': f'Impossible de récupérer le statut{manual_note}'
        })

@paas_bp.route('/api/paas/app/<app_id>/logs', methods=['GET'])
@login_required
def get_app_logs(app_id):
    """Récupère les logs d'une application"""
    username = session['username']
    apps = storage.load_apps()
    
    if app_id not in apps:
        return jsonify({'success': False, 'msg': 'Application non trouvée'}), 404
    
    app = apps[app_id]
    
    if app.get('owner') != username:
        return jsonify({'success': False, 'msg': 'Non autorisé'}), 403
    
    manager_ip = app.get('manager_ip')
    stack_name = app.get('stack_name')
    service_name = request.args.get('service', f"{stack_name}_{app.get('app_id', 'app')}")
    
    if not manager_ip:
        return jsonify({'success': False, 'msg': 'Manager IP non trouvée'}), 500
    
    bastion = SWARM_BASTION_HOST if SWARM_DEPLOYMENT_MODE == 'bastion' else None
    
    logs = swarm_deploy.get_service_logs(manager_ip, username, service_name, bastion=bastion)
    
    if logs:
        return jsonify({
            'success': True,
            'logs': logs
        })
    else:
        manual_cmd = f"ssh {username}@{manager_ip} 'sudo docker service logs {service_name}'"
        
        return jsonify({
            'success': False,
            'msg': f'Logs non disponibles\n\nVérifiez manuellement:\n{manual_cmd}'
        })

@paas_bp.route('/api/paas/app/<app_id>/scale', methods=['POST'])
@login_required
def scale_app(app_id):
    """Scale une application"""
    username = session['username']
    apps = storage.load_apps()
    data = request.json
    
    if app_id not in apps:
        return jsonify({'success': False, 'msg': 'Application non trouvée'}), 404
    
    app = apps[app_id]
    
    if app.get('owner') != username:
        return jsonify({'success': False, 'msg': 'Non autorisé'}), 403
    
    replicas = data.get('replicas', 1)
    service_name = data.get('service')
    
    if not service_name:
        return jsonify({'success': False, 'msg': 'Service requis'}), 400
    
    manager_ip = app.get('manager_ip')
    
    if not manager_ip:
        return jsonify({'success': False, 'msg': 'Manager IP non trouvée'}), 500
    
    bastion = SWARM_BASTION_HOST if SWARM_DEPLOYMENT_MODE == 'bastion' else None
    
    success, message = swarm_deploy.scale_service(
        manager_ip, username, service_name, replicas, bastion=bastion
    )
    
    if success:
        return jsonify({'success': True, 'msg': message})
    else:
        manual_cmd = f"ssh {username}@{manager_ip} 'sudo docker service scale {service_name}={replicas}'"
        
        return jsonify({
            'success': False,
            'msg': f'{message}\n\nÉchelle manuellement:\n{manual_cmd}'
        }), 500