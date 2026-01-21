# routes/iaas.py
from flask import Blueprint, render_template, request, jsonify, session
from functools import wraps
import time
import re
from config import FLAVORS
from models.vm import VMManager
from models.host import HostManager
from services.deployment_service import DeploymentService
from services.network_service import NetworkService
from routes.auth import login_required
import queue, threading

iaas_bp = Blueprint('iaas', __name__)
vm_manager = VMManager()
host_manager = HostManager()

@iaas_bp.route('/')
@login_required
def index():
    """Dashboard principal"""
    username = session['username']
    role = session.get('role', 'user')
    
    # Récupérer les VMs de l'utilisateur
    user_vms = vm_manager.get_user_vms(username)
    
    # Statistiques
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
    """API pour récupérer les VMs"""
    username = session['username']
    role = session.get('role', 'user')
    
    if role == 'admin':
        # L'admin voit toutes les VMs
        vms = list(vm_manager.metadata.values())
    else:
        vms = vm_manager.get_user_vms(username)
    
    return jsonify(vms)

@iaas_bp.route('/api/vm/deploy', methods=['POST'])
@login_required
def deploy_vm():
    """API pour déployer une VM"""
    username = session['username']
    
    try:
        # Récupérer les données du formulaire
        hostname = request.form['hostname']
        password = request.form['password']
        flavor_id = request.form['flavor']
        os_type = request.form.get('os_type', 'ubuntu')
        ssh_key = request.form.get('ssh_key', '')
        
        # Validation
        if not re.match(r'^[a-zA-Z0-9-]+$', hostname):
            return jsonify({'success': False, 'msg': 'Hostname invalide'}), 400
        
        if flavor_id not in FLAVORS:
            return jsonify({'success': False, 'msg': 'Flavor invalide'}), 400
        
        flavor = FLAVORS[flavor_id]
        
        # Sélectionner l'hôte optimal
        best_host = host_manager.select_best_host(flavor['vcpu'], flavor['ram'], flavor['disk'])
        if not best_host:
            return jsonify({'success': False, 'msg': 'Ressources insuffisantes'}), 503
        
        # Créer le réseau utilisateur
        if not NetworkService.create_user_network(best_host['uri'], username):
            return jsonify({'success': False, 'msg': 'Erreur création réseau'}), 500
        
        # Créer les métadonnées
        full_vm_name = vm_manager.create_vm_metadata(
            username, hostname, flavor_id, 
            best_host['uri'], best_host['name']
        )
        
        # Vérifier si la VM existe déjà
        conn = LibvirtService.get_connection(best_host['uri'])
        if conn:
            try:
                conn.lookupByName(full_vm_name)
                conn.close()
                vm_manager.delete_vm_metadata(full_vm_name)
                return jsonify({'success': False, 'msg': 'VM déjà existante'}), 409
            except:
                pass
            finally:
                if conn:
                    conn.close()
        
        # Générer cloud-init
        cloudinit_data = DeploymentService.generate_cloudinit(
            vm_name=full_vm_name,
            hostname=hostname,
            username=username,
            password=password,
            ssh_key=ssh_key
        )
        
        # Déployer la VM
        success = DeploymentService.deploy_vm(
            vm_name=full_vm_name,
            host_uri=best_host['uri'],
            storage_path=best_host.get('storage_path', '/var/lib/libvirt/images'),
            base_image=OS_IMAGES.get(os_type, OS_IMAGES['ubuntu']),
            disk_size=flavor['disk'],
            vcpu=flavor['vcpu'],
            ram=flavor['ram'],
            network=NetworkService.get_user_network_name(username),
            cloudinit_data=cloudinit_data
        )
        
        if success:
            vm_manager.update_vm_metadata(full_vm_name, {'status': 'Running'})
            return jsonify({
                'success': True,
                'msg': f'VM "{hostname}" déployée avec succès',
                'host': best_host['name'],
                'flavor': flavor['name'],
                'vm_name': full_vm_name
            })
        else:
            vm_manager.delete_vm_metadata(full_vm_name)
            return jsonify({'success': False, 'msg': 'Erreur lors du déploiement'}), 500
        
    except Exception as e:
        return jsonify({'success': False, 'msg': str(e)}), 500

@iaas_bp.route('/api/vm/<vm_name>/<action>', methods=['POST'])
@login_required
def control_vm(vm_name, action):
    """API pour contrôler une VM"""
    username = session['username']
    role = session.get('role', 'user')
    
    # Vérifier les permissions
    vm_owner = vm_manager.get_vm_owner(vm_name)
    if role != 'admin' and vm_owner != username:
        return jsonify({'success': False, 'msg': 'Non autorisé'}), 403
    
    # Récupérer les informations de la VM
    vm_info = vm_manager.get_vm_info(vm_name)
    if not vm_info:
        return jsonify({'success': False, 'msg': 'VM non trouvée'}), 404
    
    # Exécuter l'action
    success = LibvirtService.control_domain(vm_info['host'], vm_name, action)
    
    if success and action == 'delete':
        vm_manager.delete_vm_metadata(vm_name)
    
    return jsonify({'success': success})



@iaas_bp.route('/api/monitor', methods=['GET'])
@login_required
def monitor_api():
    """API pour récupérer toutes les VMs avec monitoring asynchrone"""
    username = session['username']
    role = session.get('role', 'user')
    
    from models.host import HostManager
    from services.libvirt_service import LibvirtService
    from models.vm import VMManager
    
    host_manager = HostManager()
    vm_manager = VMManager()
    
    vms_stats = []
    hosts = host_manager.get_enabled_hosts()
    
    print(f"\n=== API MONITOR APPELÉE ===")
    print(f"Utilisateur: {username}, Role: {role}")
    print(f"Hôtes activés: {len(hosts)}")
    
    # Fonction pour traiter un hôte en parallèle
    def process_host(host, result_queue):
        host_vms = []
        try:
            print(f"\n🔍 Traitement asynchrone hôte: {host['name']}")
            print(f"   URI: {host['uri']}")
            
            # Récupérer les VMs avec timeout
            domains = LibvirtService.get_all_domains(host['uri'], timeout=10)
            print(f"   VMs trouvées sur {host['name']}: {len(domains)}")
            
            for domain in domains:
                full_name = domain['name']
                
                # Extraire le propriétaire
                vm_owner = None
                if '_' in full_name:
                    vm_owner = full_name.split('_', 1)[0]
                
                # Vérifier les métadonnées
                vm_info = vm_manager.get_vm_info(full_name)
                if vm_info:
                    vm_owner = vm_info.get('user', vm_owner)
                
                # Vérifier les permissions
                if role == 'admin' or vm_owner == username:
                    # Récupérer le flavor
                    flavor_id = 'small'
                    if vm_info:
                        flavor_id = vm_info.get('flavor', 'small')
                    elif 'swarm' in full_name.lower():
                        flavor_id = 'swarm'
                    
                    flavor = FLAVORS.get(flavor_id, FLAVORS['small'])
                    
                    vm_data = {
                        'name': full_name,
                        'display_name': vm_manager.get_user_vm_name(full_name) if vm_owner else full_name,
                        'status': domain['status'],
                        'ip': domain.get('ip', 'N/A'),
                        'username': vm_owner or 'unknown',
                        'cpu_time': domain.get('cpu_time', 0),
                        'vcpu': domain.get('vcpu', flavor['vcpu']),
                        'max_mem': domain.get('max_mem', flavor['ram'] / 1024),
                        'used_mem': domain.get('used_mem', 0),
                        'timestamp': time.time(),
                        'flavor': flavor_id,
                        'host': host['name'],
                        'host_uri': host['uri']
                    }
                    
                    host_vms.append(vm_data)
            
            result_queue.put((host['name'], 'success', host_vms))
            
        except Exception as e:
            print(f"❌ Erreur traitement hôte {host.get('name', 'unknown')}: {e}")
            result_queue.put((host.get('name', 'unknown'), 'error', []))
    
    # Traitement parallèle des hôtes
    threads = []
    result_queue = queue.Queue()
    
    start_time = time.time()
    
    for host in hosts:
        thread = threading.Thread(target=process_host, args=(host, result_queue))
        thread.daemon = True
        threads.append(thread)
        thread.start()
    
    # Attendre les résultats avec timeout
    timeout = 30  # Timeout total de 30 secondes
    completed_hosts = set()
    
    while len(completed_hosts) < len(hosts) and (time.time() - start_time) < timeout:
        try:
            host_name, status, host_vms = result_queue.get(timeout=1)
            completed_hosts.add(host_name)
            
            if status == 'success':
                vms_stats.extend(host_vms)
                print(f"✅ Hôte {host_name} traité: {len(host_vms)} VMs")
            else:
                print(f"❌ Hôte {host_name} en erreur")
                
        except queue.Empty:
            # Vérifier si des threads sont encore en cours
            alive_threads = [t for t in threads if t.is_alive()]
            if not alive_threads:
                break
            continue
    
    elapsed = time.time() - start_time
    
    # Nettoyer les threads restants
    for thread in threads:
        if thread.is_alive():
            thread.join(timeout=1)
    
    print(f"\n📊 Résultat final: {len(vms_stats)} VMs récupérées")
    print(f"⏱️  Temps total: {elapsed:.2f}s")
    print(f"=== FIN API MONITOR ===\n")
    
    return jsonify(vms_stats)


@iaas_bp.route('/api/health/hosts', methods=['GET'])
@login_required
def health_hosts():
    """Vérifie la santé de tous les hôtes"""
    from models.host import HostManager
    import socket
    
    host_manager = HostManager()
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
            # Vérifier si c'est une connexion SSH
            if host['uri'].startswith('qemu+ssh://'):
                # Test de connectivité SSH
                parts = host['uri'].split('@')
                if len(parts) >= 2:
                    hostname = parts[1].split('/')[0].split(':')[0]
                    
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3)
                    result = sock.connect_ex((hostname, 22))
                    sock.close()
                    
                    if result == 0:
                        host_info['accessible'] = True
                        host_info['status'] = 'ssh_accessible'
                    else:
                        host_info['status'] = 'ssh_unreachable'
                else:
                    host_info['status'] = 'invalid_uri'
            
            else:
                # Connexion locale ou TCP direct
                from services.libvirt_service import LibvirtService
                conn = LibvirtService.get_connection(host['uri'], timeout=3)
                
                if conn:
                    host_info['accessible'] = True
                    host_info['status'] = 'libvirt_connected'
                    
                    # Essayer de récupérer une info simple
                    try:
                        conn.getInfo()
                        host_info['status'] = 'fully_operational'
                    except:
                        host_info['status'] = 'partial_access'
                    
                    conn.close()
                else:
                    host_info['status'] = 'libvirt_unreachable'
            
        except Exception as e:
            host_info['status'] = f'error: {str(e)[:50]}'
        
        host_info['response_time'] = time.time() - start_time
        health_status.append(host_info)
    
    return jsonify({
        'timestamp': time.time(),
        'total_hosts': len(hosts),
        'hosts': health_status
    })