# routes/swarm.py - VERSION COMPLÈTE AVEC TOUTES LES FONCTIONNALITÉS
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
    """API pour récupérer les clusters avec IPs à jour"""
    username = session['username']
    clusters = swarm_manager.get_user_clusters(username)
    
    # Pour chaque cluster, récupérer les IPs à jour
    for cluster_name, cluster in clusters.items():
        host_uri = cluster.get('host')
        
        if host_uri:
            # Mettre à jour les IPs des nœuds
            for node in cluster.get('nodes', []):
                full_name = node.get('full_name')
                current_ip = node.get('ip', '')
                
                # Si pas d'IP ou IP vide, essayer de la récupérer
                if not current_ip or current_ip == '':
                    logger.debug(f"Tentative récupération IP pour {full_name}")
                    
                    # Essai rapide (timeout court)
                    ip = LibvirtService.wait_for_vm_ip(full_name, host_uri, timeout=5)
                    
                    if ip:
                        node['ip'] = ip
                        # Mettre à jour dans la base
                        swarm_manager.update_node_ip(cluster_name, node['name'], ip)
                        logger.info(f"IP mise à jour pour {node['name']}: {ip}")
    
    logger.info(f"Récupération clusters pour {username}: {len(clusters)} trouvés")
    
    return jsonify(clusters)

@swarm_bp.route('/api/swarm/deploy', methods=['POST'])
@login_required
def deploy_cluster():
    """API pour déployer un cluster Docker Swarm"""
    username = session['username']
    data = request.json
    
    try:
        cluster_name = data.get('cluster_name', '').strip()
        num_managers = int(data.get('num_managers', 1))
        num_workers = int(data.get('num_workers', 2))
        password = data.get('password', '').strip()
        ssh_key = data.get('ssh_key', '').strip()
        
        logger.info(f"Déploiement cluster {cluster_name}: {num_managers}M + {num_workers}W par {username}")
        
        # Validation
        if not cluster_name:
            return jsonify({'success': False, 'msg': 'Nom du cluster requis'}), 400
        
        if not password:
            return jsonify({'success': False, 'msg': 'Mot de passe requis'}), 400
        
        if num_managers < 1:
            return jsonify({'success': False, 'msg': 'Au moins 1 manager requis'}), 400
        
        if num_managers % 2 == 0:
            return jsonify({'success': False, 'msg': 'Le nombre de managers doit être impair (1, 3, 5...)'}), 400
        
        total_nodes = num_managers + num_workers
        if total_nodes > 10:
            return jsonify({'success': False, 'msg': 'Maximum 10 nœuds par cluster'}), 400
        
        # Vérifier si le cluster existe déjà
        if swarm_manager.get_cluster(cluster_name):
            return jsonify({'success': False, 'msg': 'Un cluster avec ce nom existe déjà'}), 400
        
        # Sélectionner l'hôte optimal
        flavor = FLAVORS['swarm']
        required_vcpu = flavor['vcpu'] * total_nodes
        required_ram = flavor['ram'] * total_nodes
        required_disk = flavor['disk'] * total_nodes
        
        logger.debug(f"Ressources requises: {required_vcpu}vCPU, {required_ram}MB RAM, {required_disk}GB Disk")
        
        best_host = host_manager.select_best_host(
            required_vcpu=required_vcpu,
            required_ram=required_ram,
            required_disk=required_disk,
            timeout_per_host=8
        )
        
        if not best_host:
            return jsonify({'success': False, 'msg': 'Ressources insuffisantes sur les hôtes disponibles'}), 503
        
        logger.info(f"Hôte sélectionné: {best_host['name']}")
        
        # Créer le réseau Swarm
        network_name = NetworkService.get_swarm_network_name(username, cluster_name)
        logger.info(f"Création réseau: {network_name}")
        
        if not NetworkService.create_swarm_network(best_host['uri'], username, cluster_name):
            return jsonify({'success': False, 'msg': 'Erreur création réseau Swarm'}), 500
        
        # Créer le cluster dans la base (sans IPs pour l'instant)
        cluster = swarm_manager.create_cluster(
            cluster_name=cluster_name,
            username=username,
            num_managers=num_managers,
            num_workers=num_workers,
            manager_ip="",  # Sera rempli après
            network=network_name,
            host_uri=best_host['uri']
        )
        
        logger.info(f"Cluster {cluster_name} créé en base de données")
        
        # Déployer les nœuds
        deployment_errors = []
        deployed_nodes = []
        
        for node in cluster['nodes']:
            logger.info(f"Déploiement nœud: {node['name']} ({node['type']})")
            
            try:
                success = DeploymentService.deploy_swarm_node(
                    username=username,
                    node_name=node['name'],
                    cluster_name=cluster_name,
                    node_type=node['type'],
                    host_uri=best_host['uri'],
                    storage_path=best_host.get('storage_path', '/var/lib/libvirt/images'),
                    password=password,
                    ssh_key=ssh_key
                )
                
                if success:
                    deployed_nodes.append(node['name'])
                    swarm_manager.update_node_status(cluster_name, node['name'], 'deployed')
                    logger.info(f"✓ Nœud {node['name']} déployé")
                else:
                    deployment_errors.append(f"Échec déploiement {node['name']}")
                    logger.error(f"✗ Échec déploiement {node['name']}")
                    
            except Exception as e:
                error_msg = f"Erreur {node['name']}: {str(e)}"
                deployment_errors.append(error_msg)
                logger.error(error_msg, exc_info=True)
        
        # Mettre à jour le statut du cluster
        if len(deployed_nodes) == total_nodes:
            swarm_manager.update_cluster(cluster_name, {'status': 'deployed'})
            
            return jsonify({
                'success': True,
                'cluster': cluster,
                'message': f'Cluster {cluster_name} déployé avec succès ({total_nodes} nœuds)',
                'note': 'Les adresses IP seront récupérées automatiquement dans quelques instants.'
            })
        elif len(deployed_nodes) > 0:
            swarm_manager.update_cluster(cluster_name, {'status': 'partial'})
            
            return jsonify({
                'success': False,
                'cluster': cluster,
                'msg': f'Déploiement partiel: {len(deployed_nodes)}/{total_nodes} nœuds déployés',
                'errors': deployment_errors
            }), 500
        else:
            swarm_manager.delete_cluster(cluster_name)
            
            return jsonify({
                'success': False,
                'msg': 'Échec complet du déploiement',
                'errors': deployment_errors
            }), 500
        
    except ValueError as e:
        logger.error(f"Erreur validation: {e}")
        return jsonify({'success': False, 'msg': 'Valeurs invalides'}), 400
    except Exception as e:
        logger.error(f"Erreur déploiement cluster: {e}", exc_info=True)
        return jsonify({'success': False, 'msg': f'Erreur: {str(e)}'}), 500

@swarm_bp.route('/api/swarm/cluster/<cluster_name>', methods=['DELETE'])
@login_required
def delete_cluster(cluster_name):
    """API pour supprimer un cluster"""
    username = session['username']
    
    logger.info(f"Suppression cluster {cluster_name} par {username}")
    
    # Vérifier que l'utilisateur est propriétaire
    cluster = swarm_manager.get_cluster(cluster_name)
    if not cluster:
        return jsonify({'success': False, 'msg': 'Cluster non trouvé'}), 404
    
    if cluster.get('owner') != username:
        return jsonify({'success': False, 'msg': 'Non autorisé'}), 403
    
    # Supprimer le cluster (et toutes les VMs associées)
    success = swarm_manager.delete_cluster(cluster_name)
    
    if success:
        logger.info(f"Cluster {cluster_name} supprimé")
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
    if not cluster:
        return jsonify({'success': False, 'msg': 'Cluster non trouvé'}), 404
    
    if cluster.get('owner') != username:
        return jsonify({'success': False, 'msg': 'Non autorisé'}), 403
    
    # Récupérer le statut détaillé avec IPs
    host_uri = cluster.get('host')
    nodes_with_ips = []
    
    for node in cluster.get('nodes', []):
        full_name = node.get('full_name')
        node_data = {
            'name': node.get('name'),
            'full_name': full_name,
            'type': node.get('type'),
            'ip': node.get('ip', 'Attente...'),
            'status': node.get('status', 'unknown')
        }
        
        # Essayer de récupérer l'IP si elle n'existe pas
        if not node_data['ip'] or node_data['ip'] == '':
            if host_uri:
                ip = LibvirtService.wait_for_vm_ip(full_name, host_uri, timeout=5)
                if ip:
                    node_data['ip'] = ip
                    # Mettre à jour dans la base
                    swarm_manager.update_node_ip(cluster_name, node['name'], ip)
        
        nodes_with_ips.append(node_data)
    
    # Mettre à jour le premier manager IP
    manager_ip = cluster.get('manager_ip', '')
    if not manager_ip:
        # Chercher le premier manager avec une IP
        for node in nodes_with_ips:
            if node['type'] == 'manager' and node['ip'] and node['ip'] != 'Attente...':
                manager_ip = node['ip']
                swarm_manager.update_cluster(cluster_name, {'manager_ip': manager_ip})
                break
    
    logger.info(f"Statut cluster {cluster_name} récupéré")
    
    return jsonify({
        'success': True,
        'cluster': {
            'cluster_name': cluster_name,
            'owner': cluster.get('owner'),
            'status': cluster.get('status', 'deploying'),
            'manager_ip': manager_ip,
            'num_managers': cluster.get('num_managers'),
            'num_workers': cluster.get('num_workers'),
            'nodes': nodes_with_ips,
            'network': cluster.get('network'),
            'host': cluster.get('host'),
            'created_at': cluster.get('created_at'),
            'init_commands': cluster.get('init_commands', {})
        }
    })

@swarm_bp.route('/api/swarm/cluster/<cluster_name>/refresh-ips', methods=['POST'])
@login_required
def refresh_cluster_ips(cluster_name):
    """API pour rafraîchir les IPs d'un cluster"""
    username = session['username']
    
    cluster = swarm_manager.get_cluster(cluster_name)
    if not cluster or cluster.get('owner') != username:
        return jsonify({'success': False, 'msg': 'Cluster non trouvé'}), 404
    
    logger.info(f"Rafraîchissement IPs cluster {cluster_name}")
    
    host_uri = cluster.get('host')
    updated_ips = []
    
    for node in cluster.get('nodes', []):
        full_name = node.get('full_name')
        if full_name and host_uri:
            # Essayer de récupérer l'IP
            ip = LibvirtService.wait_for_vm_ip(full_name, host_uri, timeout=10)
            if ip:
                # Mettre à jour dans le cluster
                swarm_manager.update_node_ip(cluster_name, node['name'], ip)
                updated_ips.append({
                    'node': node['name'],
                    'ip': ip
                })
                logger.info(f"IP mise à jour pour {node['name']}: {ip}")
    
    # Mettre à jour le manager IP si nécessaire
    if not cluster.get('manager_ip') and updated_ips:
        for update in updated_ips:
            # Chercher le premier manager
            for node in cluster['nodes']:
                if node['name'] == update['node'] and node['type'] == 'manager':
                    swarm_manager.update_cluster(cluster_name, {'manager_ip': update['ip']})
                    break
    
    return jsonify({
        'success': True,
        'updated': len(updated_ips),
        'ips': updated_ips
    })
