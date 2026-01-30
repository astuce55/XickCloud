# routes/paas.py - VERSION AVEC DÉPLOIEMENT RÉEL
from flask import Blueprint, render_template, request, jsonify, session
import time
import secrets
from config import PaaS_CATALOG, BILLING_RATES
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
    
    return render_template('paas.html', 
                         username=username,
                         catalog=PaaS_CATALOG,
                         apps=user_apps,
                         clusters=clusters)

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
    """API pour déployer une application - VERSION FONCTIONNELLE"""
    username = session['username']
    data = request.json
    
    try:
        app_id = data.get('app_id')
        app_name = data.get('app_name', f"{app_id}-{username}").lower().replace(' ', '-')
        cluster_name = data.get('cluster_name')
        db_password = data.get('db_password', secrets.token_urlsafe(16))
        
        logger.info(f"Déploiement app {app_id} ({app_name}) sur cluster {cluster_name} par {username}")
        
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
            return jsonify({'success': False, 'msg': 'Manager IP non trouvée'}), 500
        
        # Générer un ID unique pour l'application
        app_uuid = f"{app_id}-{username}-{int(time.time())}"
        stack_name = app_name.replace('_', '-')  # Docker Stack ne supporte pas _
        
        # ÉTAPE 1: Vérifier que Swarm est actif
        logger.info(f"Vérification Swarm sur {manager_ip}")
        if not swarm_deploy.check_swarm_ready(manager_ip, username, timeout=30):
            return jsonify({'success': False, 'msg': 'Cluster Swarm non prêt'}), 503
        
        # ÉTAPE 2: Générer le docker-compose.yml
        logger.info(f"Génération docker-compose pour {app_id}")
        compose_file = compose_gen.generate_compose(app_id, stack_name, db_password)
        
        if not compose_file:
            return jsonify({'success': False, 'msg': 'Erreur génération compose'}), 500
        
        # ÉTAPE 3: Déployer sur Swarm
        logger.info(f"Déploiement stack {stack_name} sur Swarm")
        success, message = swarm_deploy.deploy_stack(
            manager_ip=manager_ip,
            username=username,
            stack_name=stack_name,
            compose_file_path=compose_file
        )
        
        if not success:
            return jsonify({'success': False, 'msg': f'Erreur déploiement: {message}'}), 500
        
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
            'url': f"http://{manager_ip}",  # URL d'accès
            'port': app_info.get('port', 80),
            'db_password': db_password,
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
        
        logger.info(f"Application {app_name} déployée avec succès")
        
        return jsonify({
            'success': True,
            'app': apps[app_uuid],
            'message': f'Application {app_info["name"]} déployée avec succès',
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
        success, message = swarm_deploy.remove_stack(manager_ip, username, stack_name)
        if not success:
            logger.warning(f"Erreur suppression stack: {message}")
    
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
    status = swarm_deploy.get_stack_status(manager_ip, username, stack_name)
    
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
        return jsonify({
            'success': True,
            'status': 'unknown',
            'msg': 'Impossible de récupérer le statut'
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
    
    logs = swarm_deploy.get_service_logs(manager_ip, username, service_name)
    
    if logs:
        return jsonify({
            'success': True,
            'logs': logs
        })
    else:
        return jsonify({
            'success': False,
            'msg': 'Logs non disponibles'
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
    
    success, message = swarm_deploy.scale_service(manager_ip, username, service_name, replicas)
    
    if success:
        return jsonify({'success': True, 'msg': message})
    else:
        return jsonify({'success': False, 'msg': message}), 500