# routes/swarm.py
from flask import Blueprint, render_template, request, jsonify, session
import time
from config import FLAVORS
from models.swarm import SwarmManager
from models.host import HostManager
from services.deployment_service import DeploymentService
from services.network_service import NetworkService
from routes.auth import login_required

swarm_bp = Blueprint('swarm', __name__)
swarm_manager = SwarmManager()
host_manager = HostManager()

@swarm_bp.route('/swarm')
@login_required
def index():
    """Page des clusters Docker Swarm"""
    username = session['username']
    
    # Récupérer les clusters de l'utilisateur
    clusters = swarm_manager.get_user_clusters(username)
    
    return render_template('swarm.html', 
                         username=username,
                         clusters=clusters,
                         flavors=FLAVORS)

@swarm_bp.route('/api/swarm/clusters', methods=['GET'])
@login_required
def get_clusters():
    """API pour récupérer les clusters"""
    username = session['username']
    clusters = swarm_manager.get_user_clusters(username)
    return jsonify(clusters)

@swarm_bp.route('/api/swarm/deploy', methods=['POST'])
@login_required
def deploy_cluster():
    """API pour déployer un cluster Docker Swarm"""
    username = session['username']
    data = request.json
    
    try:
        cluster_name = data.get('cluster_name', f'swarm-{username}-{int(time.time())}')
        num_managers = int(data.get('num_managers', 1))
        num_workers = int(data.get('num_workers', 2))
        password = data.get('password', 'changeme')
        ssh_key = data.get('ssh_key', '')
        
        # Validation
        if num_managers % 2 == 0:
            return jsonify({'success': False, 'msg': 'Le nombre de managers doit être impair'}), 400
        
        total_nodes = num_managers + num_workers
        if total_nodes > 10:
            return jsonify({'success': False, 'msg': 'Maximum 10 nœuds par cluster'}), 400
        
        # Sélectionner l'hôte optimal
        best_host = host_manager.select_best_host(
            2 * total_nodes,  # 2 vCPU par nœud
            4096 * total_nodes,  # 4GB RAM par nœud
            30 * total_nodes  # 30GB disque par nœud
        )
        
        if not best_host:
            return jsonify({'success': False, 'msg': 'Ressources insuffisantes'}), 503
        
        # Créer le réseau Swarm
        network_name = NetworkService.get_swarm_network_name(username, cluster_name)
        if not NetworkService.create_swarm_network(best_host['uri'], username, cluster_name):
            return jsonify({'success': False, 'msg': 'Erreur création réseau'}), 500
        
        # IP du manager principal
        manager_ip = f"192.168.{abs(hash(cluster_name)) % 240 + 10}.10"
        
        # Créer le cluster dans la base de données
        cluster = swarm_manager.create_cluster(
            cluster_name=cluster_name,
            username=username,
            num_managers=num_managers,
            num_workers=num_workers,
            manager_ip=manager_ip,
            network=network_name,
            host_uri=best_host['uri']
        )
        
        # Déployer les nœuds
        for node in cluster['nodes']:
            success = DeploymentService.deploy_swarm_node(
                username=username,
                node_name=node['name'],
                cluster_name=cluster_name,
                node_type=node['type'],
                ip_address=node['ip'],
                host_uri=best_host['uri'],
                storage_path=best_host.get('storage_path', '/var/lib/libvirt/images'),
                password=password,
                ssh_key=ssh_key
            )
            
            if not success:
                return jsonify({'success': False, 'msg': f'Erreur déploiement nœud {node["name"]}'}), 500
            
            # Mettre à jour le statut du nœud
            swarm_manager.update_node_status(cluster_name, node['name'], 'deployed')
        
        # Mettre à jour le statut du cluster
        swarm_manager.update_cluster(cluster_name, {'status': 'deployed'})
        
        return jsonify({
            'success': True,
            'cluster': cluster,
            'message': f'Cluster {cluster_name} déployé avec succès'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'msg': str(e)}), 500

@swarm_bp.route('/api/swarm/cluster/<cluster_name>', methods=['DELETE'])
@login_required
def delete_cluster(cluster_name):
    """API pour supprimer un cluster"""
    username = session['username']
    
    # Vérifier que l'utilisateur est propriétaire
    cluster = swarm_manager.get_cluster(cluster_name)
    if not cluster or cluster.get('owner') != username:
        return jsonify({'success': False, 'msg': 'Cluster non trouvé ou non autorisé'}), 404
    
    # Supprimer le cluster
    success = swarm_manager.delete_cluster(cluster_name)
    
    if success:
        return jsonify({'success': True, 'msg': f'Cluster {cluster_name} supprimé'})
    else:
        return jsonify({'success': False, 'msg': 'Erreur lors de la suppression'}), 500

@swarm_bp.route('/api/swarm/cluster/<cluster_name>/status', methods=['GET'])
@login_required
def get_cluster_status(cluster_name):
    """API pour récupérer le statut d'un cluster"""
    username = session['username']
    
    # Vérifier que l'utilisateur est propriétaire
    cluster = swarm_manager.get_cluster(cluster_name)
    if not cluster or cluster.get('owner') != username:
        return jsonify({'success': False, 'msg': 'Cluster non trouvé'}), 404
    
    status = swarm_manager.get_cluster_status(cluster_name)
    return jsonify(status)