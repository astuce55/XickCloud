# routes/paas.py
from flask import Blueprint, render_template, request, jsonify, session
import time
import json
from config import PaaS_CATALOG, BILLING_RATES
from models.storage import StorageManager
from routes.auth import login_required

paas_bp = Blueprint('paas', __name__)
storage = StorageManager()

@paas_bp.route('/paas')
@login_required
def index():
    """Catalogue d'applications PaaS"""
    username = session['username']
    
    # Récupérer les applications déployées
    apps = storage.load_apps()
    user_apps = [app for app in apps.values() if app.get('owner') == username]
    
    return render_template('paas.html', 
                         username=username,
                         catalog=PaaS_CATALOG,
                         apps=user_apps)

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
    return jsonify(user_apps)

@paas_bp.route('/api/paas/deploy', methods=['POST'])
@login_required
def deploy_app():
    """API pour déployer une application"""
    username = session['username']
    data = request.json
    
    try:
        app_id = data.get('app_id')
        app_name = data.get('app_name', f"{app_id}-{username}")
        cluster_name = data.get('cluster_name')
        
        if app_id not in PaaS_CATALOG:
            return jsonify({'success': False, 'msg': 'Application non trouvée dans le catalogue'}), 404
        
        app_info = PaaS_CATALOG[app_id]
        
        # Générer un ID unique pour l'application
        app_uuid = f"{app_id}-{username}-{int(time.time())}"
        
        # Enregistrer l'application
        apps = storage.load_apps()
        apps[app_uuid] = {
            'id': app_uuid,
            'app_id': app_id,
            'name': app_name,
            'owner': username,
            'deployed_at': time.time(),
            'status': 'deploying',
            'cluster': cluster_name,
            'info': app_info,
            'url': f"http://{app_uuid}.paas.xick.cloud",  # URL fictive
            'billing': {
                'rate': BILLING_RATES['app_deployment'],
                'start_time': time.time()
            }
        }
        
        storage.save_apps(apps)
        
        # Enregistrer la facturation
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
        
        return jsonify({
            'success': True,
            'app': apps[app_uuid],
            'message': f'Application {app_info["name"]} en cours de déploiement'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'msg': str(e)}), 500

@paas_bp.route('/api/paas/app/<app_id>', methods=['DELETE'])
@login_required
def delete_app(app_id):
    """API pour supprimer une application"""
    username = session['username']
    apps = storage.load_apps()
    
    if app_id not in apps or apps[app_id].get('owner') != username:
        return jsonify({'success': False, 'msg': 'Application non trouvée'}), 404
    
    # Mettre à jour le statut
    apps[app_id]['status'] = 'deleting'
    storage.save_apps(apps)
    
    # Ici, vous devriez implémenter la suppression réelle de l'application
    # via Docker Swarm ou Kubernetes
    
    return jsonify({'success': True, 'msg': 'Application en cours de suppression'})