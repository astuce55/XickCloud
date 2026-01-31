# routes/iaas.py - VERSION CORRIGÉE
from flask import Blueprint, render_template, request, jsonify, session
from functools import wraps
import time
import re
import queue
import threading
from config import FLAVORS, OS_IMAGES
from models.vm import VMManager
from models.host import HostManager
from services.deployment_service import DeploymentService
from services.network_service import NetworkService
from services.libvirt_service import LibvirtService
from routes.auth import login_required
from config_logging import iaas_logger as logger

iaas_bp = Blueprint('iaas', __name__)
vm_manager = VMManager()
host_manager = HostManager()

@iaas_bp.route('/')
@login_required
def index():
    """Dashboard principal"""
    username = session['username']
    role = session.get('role', 'user')
    
    user_vms = vm_manager.get_user_vms(username)
    
    stats = {
        'total_vms': len(user_vms),
        'running_vms': len([v for v in user_vms if v.get('status') == 'Running']),
        'total_ram': sum([FLAVORS.get(v.get('flavor', 'small'), {}).get('ram', 0) for v in user_vms]) / 1024,
        'monthly_cost': sum([FLAVORS.get(v.get('flavor', 'small'), {}).get('price', 0) for v in user_vms])
    }
    
    return render_template('iaas.html', 
                         username=username,
                         role=role,
                         flavors=FLAVORS,
                         vms=user_vms,
                         stats=stats)

@iaas_bp.route('/api/vms', methods=['GET'])
@login_required
def get_vms():
    """API pour récupérer les VMs avec leurs statuts réels"""
    username = session['username']
    role = session.get('role', 'user')
    
    logger.info(f"Récupération VMs pour {username} (role: {role})")
    
    all_vms = []
    hosts = host_manager.get_enabled_hosts()
    
    metadata = vm_manager.metadata
    
    # Récupérer les VMs des hôtes
    for host in hosts[:2]:
        try:
            domains = LibvirtService.get_all_domains(host['uri'], timeout=5)
            
            for domain in domains:
                full_name = domain['name']
                vm_owner = vm_manager.get_vm_owner(full_name)
                
                if role == 'admin' or vm_owner == username:
                    vm_meta = metadata.get(full_name, {})
                    
                    vm_data = {
                        'name': full_name,
                        'display_name': vm_manager.get_user_vm_name(full_name),
                        'status': domain['status'],
                        'ip': domain.get('ip', 'En attente DHCP'),
                        'vcpu': domain.get('vcpu', 1),
                        'max_mem': domain.get('max_mem', 0),
                        'used_mem': domain.get('used_mem', 0),
                        'host': host['name'],
                        'host_uri': host['uri'],
                        'flavor': vm_meta.get('flavor', 'small'),
                        'created_at': vm_meta.get('created_at', 0),
                        'user': vm_owner
                    }
                    all_vms.append(vm_data)
                    
        except Exception as e:
            logger.error(f"Erreur récupération VMs hôte {host['name']}: {e}")
            continue
    
    logger.info(f"Total VMs trouvées: {len(all_vms)}")
    return jsonify(all_vms)


@iaas_bp.route('/api/vm/<vm_name>/ip', methods=['GET'])
@login_required
def get_vm_ip(vm_name):
    """API pour récupérer l'IP d'une VM spécifique"""
    username = session['username']
    role = session.get('role', 'user')
    
    logger.info(f"Récupération IP pour {vm_name}")
    
    # Vérifier permissions
    vm_owner = vm_manager.get_vm_owner(vm_name)
    if role != 'admin' and vm_owner != username:
        return jsonify({'success': False, 'msg': 'Non autorisé'}), 403
    
    # Chercher l'hôte de la VM
    vm_info = vm_manager.get_vm_info(vm_name)
    host_uri = None
    
    if vm_info:
        host_uri = vm_info.get('host')
    else:
        # Chercher sur tous les hôtes
        hosts = host_manager.get_enabled_hosts()
        host_uris = [h['uri'] for h in hosts]
        host_uri = LibvirtService.get_domain_host_uri(vm_name, host_uris)
    
    if not host_uri:
        return jsonify({'success': False, 'msg': 'VM non trouvée'}), 404
    
    # Récupérer l'IP
    ip_address = LibvirtService.wait_for_vm_ip(vm_name, host_uri, timeout=30)
    
    if ip_address:
        # Mettre à jour les métadonnées
        if vm_manager.vm_exists(vm_name):
            vm_manager.update_vm_metadata(vm_name, {'ip_address': ip_address})
        
        return jsonify({
            'success': True,
            'ip': ip_address,
            'vm_name': vm_name
        })
    else:
        return jsonify({
            'success': False,
            'msg': 'IP non disponible',
            'vm_name': vm_name
        })

@iaas_bp.route('/api/vms/refresh-ips', methods=['POST'])
@login_required
def refresh_vms_ips():
    """API pour rafraîchir toutes les IPs des VMs"""
    username = session['username']
    role = session.get('role', 'user')
    
    logger.info(f"Rafraîchissement IPs pour {username}")
    
    updated_ips = []
    
    # Récupérer toutes les VMs de l'utilisateur
    vms = vm_manager.get_user_vms(username)
    
    for vm in vms:
        vm_name = vm['name']
        host_uri = vm.get('host')
        
        if host_uri:
            # Récupérer l'IP
            ip_address = LibvirtService.wait_for_vm_ip(vm_name, host_uri, timeout=15)
            
            if ip_address:
                vm_manager.update_vm_metadata(vm_name, {'ip_address': ip_address})
                updated_ips.append({
                    'vm_name': vm_name,
                    'ip': ip_address
                })
    
    return jsonify({
        'success': True,
        'updated': len(updated_ips),
        'ips': updated_ips
    })


@iaas_bp.route('/api/vm/deploy', methods=['POST'])
@login_required
def deploy_vm():
    """API pour déployer une VM - VERSION CORRIGÉE AVEC DHCP"""
    username = session['username']
    
    try:
        data = request.json
        hostname = data.get('hostname', '').strip()
        password = data.get('password', '')
        flavor_id = data.get('flavor', 'small')
        os_type = data.get('os_type', 'ubuntu')
        ssh_key = data.get('ssh_key', '').strip()
        
        # Validation
        if not hostname:
            return jsonify({'success': False, 'msg': 'Hostname requis'}), 400
            
        if not password:
            return jsonify({'success': False, 'msg': 'Mot de passe requis'}), 400
        
        if not re.match(r'^[a-zA-Z0-9-]+$', hostname):
            return jsonify({'success': False, 'msg': 'Hostname invalide'}), 400
        
        if len(hostname) > 50:
            return jsonify({'success': False, 'msg': 'Hostname trop long'}), 400
        
        if flavor_id not in FLAVORS:
            return jsonify({'success': False, 'msg': 'Flavor invalide'}), 400
        
        flavor = FLAVORS[flavor_id]
        
        # Vérifier quotas
        user_vms = vm_manager.get_user_vms(username)
        total_vcpu = sum([FLAVORS.get(v.get('flavor', 'small'), {}).get('vcpu', 0) for v in user_vms])
        total_ram = sum([FLAVORS.get(v.get('flavor', 'small'), {}).get('ram', 0) for v in user_vms])
        
        user_quota = {'vcpu': 8, 'ram': 16384, 'disk': 200}
        
        if total_vcpu + flavor['vcpu'] > user_quota['vcpu']:
            return jsonify({'success': False, 'msg': f'Quota vCPU dépassé'}), 400
        
        if total_ram + flavor['ram'] > user_quota['ram']:
            return jsonify({'success': False, 'msg': f'Quota RAM dépassé'}), 400
        
        # Sélectionner hôte
        logger.info(f"Déploiement VM {hostname} pour {username}")
        best_host = host_manager.select_best_host(
            flavor['vcpu'], 
            flavor['ram'], 
            flavor['disk'],
            timeout_per_host=5
        )
        
        if not best_host:
            return jsonify({'success': False, 'msg': 'Ressources insuffisantes'}), 503
        
        logger.info(f"Hôte sélectionné: {best_host['name']}")
        
        # Créer réseau
        network_name = NetworkService.get_user_network_name(username)
        if not NetworkService.create_user_network(best_host['uri'], username):
            return jsonify({'success': False, 'msg': 'Erreur création réseau'}), 500
        
        # Créer métadonnées
        full_vm_name = vm_manager.create_vm_metadata(
            username, hostname, flavor_id, 
            best_host['uri'], best_host['name']
        )
        
        # Vérifier VM existante
        conn = LibvirtService.get_connection(best_host['uri'], timeout=5)
        if conn:
            try:
                existing_vm = conn.lookupByName(full_vm_name)
                conn.close()
                vm_manager.delete_vm_metadata(full_vm_name)
                return jsonify({'success': False, 'msg': f'VM "{hostname}" existe déjà'}), 409
            except:
                pass
            finally:
                if conn:
                    conn.close()
        
        # Cloud-init avec DHCP
        cloudinit_data = DeploymentService.generate_cloudinit(
            vm_name=full_vm_name,
            hostname=hostname,
            username=username,
            password=password,
            ssh_key=ssh_key
        )
        
        # Déployer
        base_image = OS_IMAGES.get(os_type, OS_IMAGES['ubuntu'])
        
        success = DeploymentService.deploy_vm(
            vm_name=full_vm_name,
            host_uri=best_host['uri'],
            storage_path=best_host.get('storage_path', '/var/lib/libvirt/images'),
            base_image=base_image,
            disk_size=flavor['disk'],
            vcpu=flavor['vcpu'],
            ram=flavor['ram'],
            network=network_name,
            cloudinit_data=cloudinit_data
        )
        
        if success:
            # Récupérer l'IP via DHCP (avec délai plus long)
            def get_vm_ip_async():
                try:
                    # Attendre plus longtemps pour que l'agent démarre
                    time.sleep(30)  # Attendre 30s que l'agent démarre
                    ip_address = LibvirtService.wait_for_vm_ip(full_vm_name, best_host['uri'], timeout=300)  # 5 minutes
                    
                    if ip_address:
                        vm_manager.update_vm_metadata(full_vm_name, {
                            'ip_address': ip_address,
                            'qemu_agent': 'active'
                        })
                        logger.info(f"IP attribuée à {full_vm_name}: {ip_address}")
                    else:
                        # Si pas d'IP, marquer comme sans agent mais fonctionnel
                        logger.warning(f"Impossible de récupérer IP pour {full_vm_name}, l'agent QEMU peut être indisponible")
                        vm_manager.update_vm_metadata(full_vm_name, {
                            'ip_address': 'DHCP (agent indisponible)',
                            'qemu_agent': 'unavailable'
                        })
                except Exception as e:
                    logger.error(f"Erreur récupération IP: {e}")
            
            # Lancer la récupération d'IP en arrière-plan
            ip_thread = threading.Thread(target=get_vm_ip_async)
            ip_thread.daemon = True
            ip_thread.start()
            
            vm_manager.update_vm_metadata(full_vm_name, {
                'status': 'Running',
                'os_type': os_type,
                'deployed_at': time.time(),
                'note': 'L\'agent QEMU peut prendre quelques minutes pour démarrer'
            })
            
            logger.info(f"VM {full_vm_name} déployée avec succès")
            
            return jsonify({
                'success': True,
                'msg': f'VM "{hostname}" déployée avec succès',
                'vm_name': full_vm_name,
                'host': best_host['name'],
                'flavor': flavor['name'],
                'message': 'Attribution IP en cours via DHCP... L\'agent QEMU peut prendre 1-2 minutes pour démarrer',
                'warning': 'L\'agent QEMU Guest peut prendre quelques minutes pour être pleinement opérationnel'
            })
        else:
            vm_manager.delete_vm_metadata(full_vm_name)
            return jsonify({'success': False, 'msg': 'Erreur déploiement'}), 500
        
    except Exception as e:
        logger.error(f"Erreur déploiement VM: {e}", exc_info=True)
        return jsonify({'success': False, 'msg': f'Erreur: {str(e)}'}), 500

@iaas_bp.route('/api/vm/<vm_name>/<action>', methods=['POST'])
@login_required
def control_vm(vm_name, action):
    """API pour contrôler une VM (start/stop/delete/restart)"""
    username = session['username']
    role = session.get('role', 'user')
    
    # Actions autorisées
    allowed_actions = ['start', 'stop', 'delete', 'restart']
    if action not in allowed_actions:
        return jsonify({'success': False, 'msg': f'Action invalide: {action}'}), 400
    
    logger.info(f"Action {action} sur VM {vm_name} par {username}")
    
    # Vérifier permissions
    vm_owner = vm_manager.get_vm_owner(vm_name)
    
    # Si pas de métadonnées, extraire owner du nom de la VM
    if not vm_owner and '_' in vm_name:
        vm_owner = vm_name.split('_', 1)[0]
    
    if role != 'admin' and vm_owner != username:
        logger.warning(f"Accès refusé: {username} tente {action} sur VM de {vm_owner}")
        return jsonify({'success': False, 'msg': 'Non autorisé'}), 403
    
    # Chercher l'hôte de la VM
    vm_info = vm_manager.get_vm_info(vm_name)
    host_uri = None
    
    if vm_info:
        # VM dans les métadonnées
        host_uri = vm_info.get('host')
        logger.debug(f"VM {vm_name} trouvée dans métadonnées, hôte: {host_uri}")
    else:
        # VM pas dans métadonnées, chercher sur tous les hôtes
        logger.warning(f"VM {vm_name} non trouvée dans métadonnées, recherche sur hôtes...")
        hosts = host_manager.get_enabled_hosts()
        host_uris = [h['uri'] for h in hosts]
        
        host_uri = LibvirtService.get_domain_host_uri(vm_name, host_uris)
        
        if host_uri:
            logger.info(f"VM {vm_name} trouvée sur hôte: {host_uri}")
        else:
            logger.error(f"VM {vm_name} introuvable sur tous les hôtes")
            return jsonify({'success': False, 'msg': 'VM non trouvée sur les hôtes'}), 404
    
    # Exécuter l'action
    try:
        success = LibvirtService.control_domain(host_uri, vm_name, action)
        
        if success:
            # Mettre à jour métadonnées si elles existent
            if action == 'delete':
                if vm_manager.vm_exists(vm_name):
                    vm_manager.delete_vm_metadata(vm_name)
                msg = f'VM "{vm_name}" supprimée'
            elif action == 'start':
                if vm_manager.vm_exists(vm_name):
                    vm_manager.update_vm_metadata(vm_name, {'status': 'Running'})
                msg = f'VM "{vm_name}" démarrée'
            elif action == 'stop':
                if vm_manager.vm_exists(vm_name):
                    vm_manager.update_vm_metadata(vm_name, {'status': 'Shutoff'})
                msg = f'VM "{vm_name}" arrêtée'
            else:
                msg = f'Action "{action}" exécutée sur VM "{vm_name}"'
            
            logger.info(f"Action {action} réussie sur {vm_name}")
            return jsonify({'success': True, 'msg': msg})
        else:
            logger.error(f"Échec action {action} sur {vm_name}")
            return jsonify({'success': False, 'msg': f'Échec de l\'action "{action}"'}), 500
            
    except Exception as e:
        logger.error(f"Erreur contrôle VM {vm_name}: {e}", exc_info=True)
        return jsonify({'success': False, 'msg': f'Erreur: {str(e)}'}), 500

@iaas_bp.route('/api/monitor', methods=['GET'])
@login_required
def monitor_api():
    """API monitoring optimisée"""
    username = session['username']
    role = session.get('role', 'user')
    
    vms_stats = []
    hosts = host_manager.get_enabled_hosts()
    
    def process_host(host, result_queue):
        host_vms = []
        try:
            domains = LibvirtService.get_all_domains(host['uri'], timeout=8)
            
            for domain in domains:
                full_name = domain['name']
                vm_owner = vm_manager.get_vm_owner(full_name)
                
                if role == 'admin' or vm_owner == username:
                    vm_info = vm_manager.get_vm_info(full_name)
                    flavor_id = vm_info.get('flavor', 'small') if vm_info else 'small'
                    flavor = FLAVORS.get(flavor_id, FLAVORS['small'])
                    
                    vm_data = {
                        'name': full_name,
                        'display_name': vm_manager.get_user_vm_name(full_name),
                        'status': domain['status'],
                        'ip': domain.get('ip', 'En attente DHCP'),
                        'username': vm_owner or 'unknown',
                        'vcpu': domain.get('vcpu', flavor['vcpu']),
                        'max_mem': domain.get('max_mem', flavor['ram'] / 1024),
                        'used_mem': domain.get('used_mem', 0),
                        'flavor': flavor_id,
                        'host': host['name'],
                        'host_uri': host['uri'],
                        'timestamp': time.time()
                    }
                    host_vms.append(vm_data)
            
            result_queue.put((host['name'], 'success', host_vms))
            
        except Exception as e:
            logger.error(f"Erreur monitoring hôte {host.get('name')}: {e}")
            result_queue.put((host.get('name', 'unknown'), 'error', []))
    
    # Traitement parallèle
    threads = []
    result_queue = queue.Queue()
    start_time = time.time()
    timeout = 20
    
    for host in hosts:
        thread = threading.Thread(target=process_host, args=(host, result_queue))
        thread.daemon = True
        threads.append(thread)
        thread.start()
    
    # Attendre résultats
    completed_hosts = set()
    
    while len(completed_hosts) < len(hosts) and (time.time() - start_time) < timeout:
        try:
            host_name, status, host_vms = result_queue.get(timeout=1)
            completed_hosts.add(host_name)
            
            if status == 'success':
                vms_stats.extend(host_vms)
        except queue.Empty:
            alive_threads = [t for t in threads if t.is_alive()]
            if not alive_threads:
                break
    
    logger.info(f"Monitoring: {len(vms_stats)} VMs en {time.time() - start_time:.2f}s")
    
    return jsonify(vms_stats)

@iaas_bp.route('/api/health/hosts', methods=['GET'])
@login_required
def health_hosts():
    """Vérifie la santé des hôtes"""
    import socket
    
    hosts = host_manager.get_enabled_hosts()
    health_status = []
    
    for host in hosts:
        host_info = {
            'name': host['name'],
            'uri': host['uri'],
            'priority': host.get('priority', 999),
            'enabled': host.get('enabled', True),
            'status': 'unknown',
            'response_time': 0,
            'accessible': False
        }
        
        start_time = time.time()
        
        try:
            if host['uri'].startswith('qemu+ssh://'):
                parts = host['uri'].split('@')
                if len(parts) >= 2:
                    hostname = parts[1].split('/')[0].split(':')[0]
                    
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3)
                    result = sock.connect_ex((hostname, 22))
                    sock.close()
                    
                    host_info['accessible'] = (result == 0)
                    host_info['status'] = 'ssh_accessible' if result == 0 else 'ssh_unreachable'
            else:
                conn = LibvirtService.get_connection(host['uri'], timeout=3)
                if conn:
                    host_info['accessible'] = True
                    host_info['status'] = 'fully_operational'
                    conn.close()
                else:
                    host_info['status'] = 'libvirt_unreachable'
        except Exception as e:
            host_info['status'] = f'error'
            logger.debug(f"Health check error {host['name']}: {e}")
        
        host_info['response_time'] = time.time() - start_time
        health_status.append(host_info)
    
    return jsonify({
        'timestamp': time.time(),
        'total_hosts': len(hosts),
        'hosts': health_status
    })