# routes/swarm.py - VERSION CORRIGÉE AVEC DHCP ET RÉCUPÉRATION AUTO DES IPs
from flask import Blueprint, render_template, request, jsonify, session
import time
from config import FLAVORS
from models.swarm import SwarmManager
from models.host import HostManager
from services.deployment_service import DeploymentService
from services.network_service import NetworkService
from services.libvirt_service import LibvirtService
from routes.auth import login_required
from config_logging import swarm_logger as logger

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
    """API pour déployer un cluster Docker Swarm - VERSION CORRIGÉE"""
    username = session['username']
    data = request.json
    
    try:
        cluster_name = data.get('cluster_name', f'swarm-{username}-{int(time.time())}')
        num_managers = int(data.get('num_managers', 1))
        num_workers = int(data.get('num_workers', 2))
        password = data.get('password', 'changeme')
        ssh_key = data.get('ssh_key', '')
        
        logger.info(f"Déploiement cluster {cluster_name}: {num_managers} managers, {num_workers} workers")
        
        # Validation
        if num_managers % 2 == 0:
            return jsonify({'success': False, 'msg': 'Le nombre de managers doit être impair'}), 400
        
        total_nodes = num_managers + num_workers
        if total_nodes > 10:
            return jsonify({'success': False, 'msg': 'Maximum 10 nœuds par cluster'}), 400
        
        # Sélectionner l'hôte optimal
        best_host = host_manager.select_best_host(
            2 * total_nodes,      # 2 vCPU par nœud
            4096 * total_nodes,   # 4GB RAM par nœud
            30 * total_nodes      # 30GB disque par nœud
        )
        
        if not best_host:
            return jsonify({'success': False, 'msg': 'Ressources insuffisantes'}), 503
        
        logger.info(f"Hôte sélectionné: {best_host['name']}")
        
        # Créer le réseau Swarm
        network_name = NetworkService.get_swarm_network_name(username, cluster_name)
        if not NetworkService.create_swarm_network(best_host['uri'], username, cluster_name):
            return jsonify({'success': False, 'msg': 'Erreur création réseau'}), 500
        
        logger.info(f"Réseau créé: {network_name}")
        
        # CORRECTION: Ne pas générer d'IP manuellement
        # L'IP du manager sera récupérée après déploiement via DHCP
        
        # Créer le cluster dans la base de données (sans manager_ip pour l'instant)
        cluster = swarm_manager.create_cluster(
            cluster_name=cluster_name,
            username=username,
            num_managers=num_managers,
            num_workers=num_workers,
            manager_ip=None,  # CORRECTION: Sera mis à jour après boot
            network=network_name,
            host_uri=best_host['uri']
        )
        
        logger.info(f"Cluster créé dans la DB: {cluster_name}")
        
        # Déployer les nœuds
        deployed_nodes = []
        for node in cluster['nodes']:
            logger.info(f"Déploiement nœud {node['name']}...")
            
            success = DeploymentService.deploy_swarm_node(
                username=username,
                node_name=node['name'],
                cluster_name=cluster_name,
                node_type=node['type'],
                ip_address=None,  # CORRECTION: DHCP au lieu d'IP statique
                host_uri=best_host['uri'],
                storage_path=best_host.get('storage_path', '/var/lib/libvirt/images'),
                password=password,
                ssh_key=ssh_key
            )
            
            if not success:
                logger.error(f"Échec déploiement {node['name']}")
                return jsonify({'success': False, 'msg': f'Erreur déploiement nœud {node["name"]}'}), 500
            
            # Mettre à jour le statut du nœud
            swarm_manager.update_node_status(cluster_name, node['name'], 'booting')
            deployed_nodes.append(node['name'])
        
        # Mettre à jour le statut du cluster
        swarm_manager.update_cluster(cluster_name, {'status': 'booting'})
        
        logger.info(f"Cluster {cluster_name} déployé, attente des IPs DHCP...")
        
        return jsonify({
            'success': True,
            'cluster': cluster,
            'message': f'Cluster {cluster_name} déployé. Récupération des IPs en cours...',
            'next_step': 'wait_for_ips'
        })
        
    except Exception as e:
        logger.error(f"Erreur déploiement cluster: {e}", exc_info=True)
        return jsonify({'success': False, 'msg': str(e)}), 500

@swarm_bp.route('/api/swarm/cluster/<cluster_name>/update-ips', methods=['POST'])
@login_required
def update_cluster_ips(cluster_name):
    """
    Met à jour les IPs des nœuds d'un cluster après déploiement
    NOUVELLE ROUTE pour récupération automatique des IPs DHCP
    """
    username = session['username']
    
    # Vérifier propriété
    cluster = swarm_manager.get_cluster(cluster_name)
    if not cluster or cluster.get('owner') != username:
        return jsonify({'success': False, 'msg': 'Cluster non trouvé ou non autorisé'}), 404
    
    logger.info(f"Mise à jour IPs cluster {cluster_name}")
    
    host_uri = cluster.get('host')
    updated_nodes = []
    errors = []
    
    # Récupérer l'IP de chaque nœud
    for node in cluster.get('nodes', []):
        full_vm_name = node.get('full_name')
        node_name = node.get('name')
        
        logger.debug(f"Récupération IP pour {node_name} ({full_vm_name})...")
        
        # Récupérer l'IP depuis libvirt DHCP
        ip = LibvirtService.get_vm_ip_address(full_vm_name, host_uri, timeout=45)
        
        if ip:
            # Mettre à jour dans le cluster
            for n in cluster['nodes']:
                if n['name'] == node_name:
                    n['ip'] = ip
                    n['status'] = 'ready'
            
            updated_nodes.append({'node': node_name, 'ip': ip})
            logger.info(f"✓ IP mise à jour pour {node_name}: {ip}")
        else:
            errors.append({'node': node_name, 'error': 'IP non récupérée après timeout'})
            logger.warning(f"⚠ Impossible de récupérer IP pour {node_name}")
    
    # Mettre à jour le manager_ip (prendre l'IP du premier manager)
    if updated_nodes:
        manager_nodes = [n for n in cluster['nodes'] if n['type'] == 'manager']
        if manager_nodes and 'ip' in manager_nodes[0]:
            cluster['manager_ip'] = manager_nodes[0]['ip']
            logger.info(f"Manager IP définie: {cluster['manager_ip']}")
    
    # Générer les commandes Swarm
    if cluster.get('manager_ip'):
        cluster['init_commands'] = {
            'init_swarm': f"ssh {username}@{cluster['manager_ip']} 'sudo docker swarm init --advertise-addr {cluster['manager_ip']}'",
            'get_manager_token': f"ssh {username}@{cluster['manager_ip']} 'sudo docker swarm join-token manager -q'",
            'get_worker_token': f"ssh {username}@{cluster['manager_ip']} 'sudo docker swarm join-token worker -q'"
        }
    
    # Sauvegarder les changements
    swarm_manager.update_cluster(cluster_name, cluster)
    
    # Mettre à jour le statut global
    if not errors:
        swarm_manager.update_cluster(cluster_name, {'status': 'ready'})
        logger.info(f"✓ Cluster {cluster_name} prêt avec {len(updated_nodes)} nœuds")
    else:
        swarm_manager.update_cluster(cluster_name, {'status': 'partial'})
        logger.warning(f"Cluster {cluster_name} partiellement prêt: {len(errors)} erreurs")
    
    return jsonify({
        'success': len(errors) == 0,
        'updated': updated_nodes,
        'errors': errors,
        'cluster': cluster,
        'manager_ip': cluster.get('manager_ip')
    })

@swarm_bp.route('/api/swarm/cluster/<cluster_name>', methods=['DELETE'])
@login_required
def delete_cluster(cluster_name):
    """API pour supprimer un cluster"""
    username = session['username']
    
    # Vérifier que l'utilisateur est propriétaire
    cluster = swarm_manager.get_cluster(cluster_name)
    if not cluster or cluster.get('owner') != username:
        return jsonify({'success': False, 'msg': 'Cluster non trouvé ou non autorisé'}), 404
    
    logger.info(f"Suppression cluster {cluster_name} par {username}")
    
    # Supprimer le cluster et toutes ses VMs
    success = swarm_manager.delete_cluster(cluster_name)
    
    if success:
        logger.info(f"✓ Cluster {cluster_name} supprimé")
        return jsonify({'success': True, 'msg': f'Cluster {cluster_name} supprimé'})
    else:
        logger.error(f"Échec suppression cluster {cluster_name}")
        return jsonify({'success': False, 'msg': 'Erreur lors de la suppression'}), 500

@swarm_bp.route('/api/swarm/cluster/<cluster_name>/status', methods=['GET'])
@login_required
def get_cluster_status(cluster_name):
    """API pour récupérer le statut détaillé d'un cluster"""
    username = session['username']
    
    # Vérifier que l'utilisateur est propriétaire
    cluster = swarm_manager.get_cluster(cluster_name)
    if not cluster or cluster.get('owner') != username:
        return jsonify({'success': False, 'msg': 'Cluster non trouvé'}), 404
    
    status = swarm_manager.get_cluster_status(cluster_name)
    return jsonify(status)

@swarm_bp.route('/api/swarm/cluster/<cluster_name>/nodes', methods=['GET'])
@login_required
def get_cluster_nodes(cluster_name):
    """API pour récupérer la liste des nœuds d'un cluster"""
    username = session['username']
    
    cluster = swarm_manager.get_cluster(cluster_name)
    if not cluster or cluster.get('owner') != username:
        return jsonify({'success': False, 'msg': 'Cluster non trouvé'}), 404
    
    nodes_info = []
    host_uri = cluster.get('host')
    
    for node in cluster.get('nodes', []):
        full_vm_name = node.get('full_name')
        
        # Récupérer l'état en temps réel depuis libvirt
        try:
            conn = LibvirtService.get_connection(host_uri, timeout=3)
            if conn:
                try:
                    dom = conn.lookupByName(full_vm_name)
                    is_active = dom.isActive() == 1
                    
                    node_data = {
                        'name': node.get('name'),
                        'type': node.get('type'),
                        'ip': node.get('ip', 'N/A'),
                        'status': 'running' if is_active else 'stopped',
                        'vm_name': full_vm_name
                    }
                    nodes_info.append(node_data)
                except:
                    nodes_info.append({
                        'name': node.get('name'),
                        'type': node.get('type'),
                        'ip': node.get('ip', 'N/A'),
                        'status': 'unknown',
                        'vm_name': full_vm_name
                    })
                finally:
                    conn.close()
        except:
            nodes_info.append({
                'name': node.get('name'),
                'type': node.get('type'),
                'ip': node.get('ip', 'N/A'),
                'status': 'error',
                'vm_name': full_vm_name
            })
    
    return jsonify({
        'cluster': cluster_name,
        'nodes': nodes_info,
        'total': len(nodes_info)
    })