import os
import subprocess
import libvirt
import uuid
import time
import re
import io
import shutil
import sys
import json
from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
from functools import wraps
import hashlib

app = Flask(__name__)
app.secret_key = 'votre_cle_secrete_a_changer'  # À modifier en production

# --- CONFIGURATION ---
VM_STORAGE_DIR = "/var/lib/libvirt/images"
BASE_IMG_DIR = "/var/lib/libvirt/images/base-images"
GEN_DIR = os.path.join(os.getcwd(), 'generated')
KEYS_DIR = os.path.join(os.getcwd(), 'keys')
METADATA_FILE = os.path.join(os.getcwd(), 'vm_metadata.json')
USERS_FILE = os.path.join(os.getcwd(), 'users.json')
HOSTS_FILE = os.path.join(os.getcwd(), 'kvm_hosts.json')
SWARM_CLUSTERS_FILE = os.path.join(os.getcwd(), 'swarm_clusters.json')

os.makedirs(GEN_DIR, exist_ok=True)
os.makedirs(KEYS_DIR, exist_ok=True)

# --- FLAVORS DEFINITION ---
FLAVORS = {
    'small': {
        'name': 'Small',
        'vcpu': 1,
        'ram': 2048,  # MiB
        'disk': 15,   # GB
        'price': 2500  # FCFA/mois
    },
    'medium': {
        'name': 'Medium',
        'vcpu': 2,
        'ram': 4096,
        'disk': 20,
        'price': 3500
    },
    'large': {
        'name': 'Large',
        'vcpu': 4,
        'ram': 8192,
        'disk': 40,
        'price': 6500
    }
}

# Flavors speciales pour docker swarm
FLAVORS['swarm'] = {'name': 'Docker Swarm Node', 'vcpu': 2, 'ram': 4096, 'disk': 30, 'price': 4000}

OS_IMAGES = {
    'ubuntu': os.path.join(BASE_IMG_DIR, "base-ubuntu.qcow2"),
    'debian': os.path.join(BASE_IMG_DIR, "base-debian.qcow2")
}

# --- GESTION SWARM CLUSTERS ---
def load_swarm_clusters():
    if os.path.exists(SWARM_CLUSTERS_FILE):
        try:
            with open(SWARM_CLUSTERS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_swarm_clusters(clusters):
    with open(SWARM_CLUSTERS_FILE, 'w') as f:
        json.dump(clusters, f, indent=2)



# --- HELPER FUNCTIONS POUR NOMS DE VMs ---
def get_full_vm_name(username, hostname):
    """
    Génère le nom complet de la VM avec préfixe utilisateur
    Format: username_hostname
    """
    return f"{username}_{hostname}"

def get_user_vm_name(full_vm_name):
    """
    Extrait le nom court (sans préfixe utilisateur) d'un nom complet de VM
    """
    if '_' in full_vm_name:
        parts = full_vm_name.split('_', 1)
        return parts[1] if len(parts) > 1 else full_vm_name
    return full_vm_name

def get_vm_owner(full_vm_name):
    """
    Extrait le propriétaire d'une VM depuis son nom complet
    """
    if '_' in full_vm_name:
        return full_vm_name.split('_', 1)[0]
    return None

# --- GESTION UTILISATEURS ---
def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_default_users():
    users = load_users()
    if not users:
        users = {
            'admin': {
                'password': hash_password('admin123'),
                'role': 'admin',
                'quota': {'vcpu': 100, 'ram': 102400, 'disk': 1000}
            },
            'user1': {
                'password': hash_password('user123'),
                'role': 'user',
                'quota': {'vcpu': 8, 'ram': 16384, 'disk': 200}
            },
            'user2': {
                'password': hash_password('user123'),
                'role': 'user',
                'quota': {'vcpu': 8, 'ram': 16384, 'disk': 200}
            }
        }
        save_users(users)

init_default_users()

# --- GESTION HÔTES KVM ---
def load_hosts():
    """Charge la configuration des hôtes KVM"""
    if os.path.exists(HOSTS_FILE):
        try:
            with open(HOSTS_FILE, 'r') as f:
                return json.load(f)
        except:
            return get_default_hosts()
    return get_default_hosts()

def get_default_hosts():
    """Configuration par défaut avec hôte distant prioritaire"""
    return [
        {
            'id': 'remote-kvm-1',
            'name': 'KVM Distant Principal',
            'uri': 'qemu+ssh://kvmadmin@192.168.1.132/system',  # À ADAPTER
            'enabled': True,
            'priority': 1,  # Priorité haute (1 = première machine à utiliser)
            'storage_path': '/var/lib/libvirt/images',
            'quotas': {
                'max_vcpu': 8,      # Maximum 8 vCPUs
                'max_ram': 16384,   # Maximum 16GB RAM (en MiB)
                'max_disk': 200     # Maximum 200GB stockage
            },
            'description': 'Serveur distant principal'
        },
        {
            'id': 'local',
            'name': 'KVM Local (Fallback)',
            'uri': 'qemu:///system',
            'enabled': True,
            'priority': 2,  # Priorité basse (utilisé en second)
            'storage_path': '/var/lib/libvirt/images',
            'quotas': {
                'max_vcpu': 16,
                'max_ram': 32768,
                'max_disk': 500
            },
            'description': 'Serveur local de secours'
        }
    ]

def save_hosts(hosts):
    with open(HOSTS_FILE, 'w') as f:
        json.dump(hosts, f, indent=2)

def init_hosts():
    """Initialise les hôtes si le fichier n'existe pas"""
    if not os.path.exists(HOSTS_FILE):
        save_hosts(get_default_hosts())

init_hosts()

# --- GESTION PERSISTANCE (VMs) ---
def load_metadata():
    if os.path.exists(METADATA_FILE):
        try:
            with open(METADATA_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_metadata(data):
    with open(METADATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

# --- CONNEXION LIBVIRT ---
def get_libvirt_conn(host_uri='qemu:///system'):
    """Établit une connexion libvirt vers un hôte"""
    try:
        return libvirt.open(host_uri)
    except libvirt.libvirtError as e:
        print(f"ERREUR CONNEXION LIBVIRT [{host_uri}]: {e}", file=sys.stderr)
        return None

# --- GESTION RÉSEAU ---
def get_user_network_name(username):
    """Génère le nom du réseau pour un utilisateur"""
    return f"net_{username}"

def create_user_network(username, host_uri='qemu:///system'):
    """Crée un réseau isolé pour l'utilisateur sur l'hôte spécifié"""
    conn = get_libvirt_conn(host_uri)
    if not conn:
        return False
    
    network_name = get_user_network_name(username)
    
    try:
        # Vérifier si le réseau existe déjà
        try:
            net = conn.networkLookupByName(network_name)
            if net.isActive():
                return True
            net.create()
            return True
        except libvirt.libvirtError:
            pass  # Le réseau n'existe pas, on le crée
        
        # Générer une plage IP unique basée sur le hash du username
        ip_suffix = abs(hash(username)) % 240 + 10
        network_ip = f"192.168.{ip_suffix}"
        
        network_xml = f"""
<network>
  <name>{network_name}</name>
  <forward mode='nat'/>
  <bridge name='virbr_{ip_suffix}' stp='on' delay='0'/>
  <ip address='{network_ip}.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='{network_ip}.10' end='{network_ip}.200'/>
    </dhcp>
  </ip>
</network>
"""
        net = conn.networkDefineXML(network_xml)
        net.setAutostart(1)
        net.create()
        return True
    except Exception as e:
        print(f"Erreur création réseau: {e}", file=sys.stderr)
        return False
    finally:
        if conn:
            conn.close()

# --- RÉCUPÉRATION RESSOURCES HÔTE ---
def get_host_resources(host_uri):
    """Récupère les ressources utilisées et disponibles sur un hôte"""
    conn = get_libvirt_conn(host_uri)
    if not conn:
        return None
    
    try:
        # Capacités totales physiques
        nodeinfo = conn.getInfo()
        total_memory = nodeinfo[1]  # MiB
        total_cpus = nodeinfo[2]
        
        # Ressources actuellement utilisées
        used_memory = 0
        used_cpus = 0
        used_disk = 0
        
        for dom in conn.listAllDomains():
            if dom.isActive():
                info = dom.info()
                used_memory += info[2] / 1024  # Convertir en MiB
                used_cpus += info[3]
        
        return {
            'total_memory': total_memory,
            'total_cpus': total_cpus,
            'used_memory': used_memory,
            'used_cpus': used_cpus,
            'used_disk': used_disk,
            'available_memory': total_memory - used_memory,
            'available_cpus': total_cpus - used_cpus
        }
    except Exception as e:
        print(f"Erreur récupération ressources: {e}", file=sys.stderr)
        return None
    finally:
        if conn:
            conn.close()

def get_host_usage(host):
    """Calcule l'utilisation actuelle d'un hôte par rapport à ses quotas"""
    resources = get_host_resources(host['uri'])
    if not resources:
        return None
    
    quotas = host.get('quotas', {})
    max_vcpu = quotas.get('max_vcpu', resources['total_cpus'])
    max_ram = quotas.get('max_ram', resources['total_memory'])
    max_disk = quotas.get('max_disk', 1000)
    
    return {
        'used_vcpu': resources['used_cpus'],
        'max_vcpu': max_vcpu,
        'available_vcpu': max_vcpu - resources['used_cpus'],
        'used_ram': resources['used_memory'],
        'max_ram': max_ram,
        'available_ram': max_ram - resources['used_memory'],
        'used_disk': resources['used_disk'],
        'max_disk': max_disk,
        'available_disk': max_disk - resources['used_disk'],
        'vcpu_percent': (resources['used_cpus'] / max_vcpu * 100) if max_vcpu > 0 else 0,
        'ram_percent': (resources['used_memory'] / max_ram * 100) if max_ram > 0 else 0
    }

# --- SÉLECTION HÔTE OPTIMAL ---
def select_best_host(required_vcpu, required_ram, required_disk=0):
    """
    Sélectionne l'hôte optimal selon la stratégie:
    1. Priorité (du plus faible au plus élevé)
    2. Ressources disponibles suffisantes (par rapport aux quotas)
    3. Si plusieurs hôtes de même priorité, choisir le moins chargé
    """
    hosts = load_hosts()
    
    # Filtrer les hôtes actifs et les trier par priorité
    active_hosts = [h for h in hosts if h.get('enabled', True)]
    active_hosts.sort(key=lambda h: h.get('priority', 999))
    
    for host in active_hosts:
        usage = get_host_usage(host)
        if not usage:
            print(f"Hôte {host['name']} non accessible", file=sys.stderr)
            continue
        
        # Vérifier si l'hôte a assez de ressources disponibles
        has_cpu = usage['available_vcpu'] >= required_vcpu
        has_ram = usage['available_ram'] >= required_ram
        has_disk = usage['available_disk'] >= required_disk
        
        if has_cpu and has_ram and has_disk:
            print(f"Hôte sélectionné: {host['name']} (priorité {host.get('priority', 999)})")
            return host
        else:
            print(f"Hôte {host['name']} ressources insuffisantes: "
                  f"CPU {usage['available_vcpu']}/{required_vcpu}, "
                  f"RAM {usage['available_ram']}/{required_ram}, "
                  f"DISK {usage['available_disk']}/{required_disk}")
    
    return None

# --- DÉCORATEURS AUTHENTIFICATION ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session or session.get('role') != 'admin':
            return jsonify({'error': 'Accès interdit'}), 403
        return f(*args, **kwargs)
    return decorated_function

# --- ROUTES AUTHENTIFICATION ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        users = load_users()
        
        if username in users:
            if users[username]['password'] == hash_password(password):
                session['username'] = username
                session['role'] = users[username].get('role', 'user')
                return redirect(url_for('index'))
        
        return render_template('login.html', error="Identifiants incorrects")
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- ROUTES PRINCIPALES ---
@app.route('/')
@login_required
def index():
    return render_template('index.html', 
                         username=session['username'],
                         role=session.get('role', 'user'),
                         flavors=FLAVORS)

# --- ROUTES ADMIN HOSTS ---
@app.route('/admin/hosts')
@login_required
@admin_required
def admin_hosts():
    return render_template('admin_hosts.html')

@app.route('/api/admin/hosts', methods=['GET'])
@login_required
@admin_required
def get_hosts():
    """Liste tous les hôtes avec leurs statistiques"""
    hosts = load_hosts()
    hosts_with_stats = []
    
    for host in hosts:
        host_info = host.copy()
        usage = get_host_usage(host)
        host_info['usage'] = usage
        host_info['status'] = 'online' if usage else 'offline'
        hosts_with_stats.append(host_info)
    
    return jsonify(hosts_with_stats)

@app.route('/api/admin/hosts', methods=['POST'])
@login_required
@admin_required
def add_host():
    """Ajoute un nouveau hôte KVM"""
    data = request.json
    
    hosts = load_hosts()
    
    # Générer un ID unique
    host_id = data.get('id', f"host-{int(time.time())}")
    
    new_host = {
        'id': host_id,
        'name': data.get('name', 'Nouvel hôte'),
        'uri': data.get('uri', 'qemu:///system'),
        'enabled': data.get('enabled', True),
        'priority': data.get('priority', len(hosts) + 1),
        'storage_path': data.get('storage_path', '/var/lib/libvirt/images'),
        'quotas': {
            'max_vcpu': data.get('max_vcpu', 8),
            'max_ram': data.get('max_ram', 16384),
            'max_disk': data.get('max_disk', 200)
        },
        'description': data.get('description', '')
    }
    
    hosts.append(new_host)
    save_hosts(hosts)
    
    return jsonify({'success': True, 'host': new_host})

@app.route('/api/admin/hosts/<host_id>', methods=['PUT'])
@login_required
@admin_required
def update_host(host_id):
    """Modifie un hôte existant"""
    data = request.json
    hosts = load_hosts()
    
    for i, host in enumerate(hosts):
        if host['id'] == host_id:
            hosts[i].update({
                'name': data.get('name', host['name']),
                'uri': data.get('uri', host['uri']),
                'enabled': data.get('enabled', host.get('enabled', True)),
                'priority': data.get('priority', host.get('priority', 999)),
                'storage_path': data.get('storage_path', host.get('storage_path', '/var/lib/libvirt/images')),
                'quotas': {
                    'max_vcpu': data.get('max_vcpu', host.get('quotas', {}).get('max_vcpu', 8)),
                    'max_ram': data.get('max_ram', host.get('quotas', {}).get('max_ram', 16384)),
                    'max_disk': data.get('max_disk', host.get('quotas', {}).get('max_disk', 200))
                },
                'description': data.get('description', host.get('description', ''))
            })
            save_hosts(hosts)
            return jsonify({'success': True, 'host': hosts[i]})
    
    return jsonify({'success': False, 'error': 'Hôte non trouvé'}), 404

@app.route('/api/admin/hosts/<host_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_host(host_id):
    """Supprime un hôte"""
    hosts = load_hosts()
    hosts = [h for h in hosts if h['id'] != host_id]
    save_hosts(hosts)
    return jsonify({'success': True})

# --- API MONITORING ---
@app.route('/api/monitor')
@login_required
def monitor_api():
    username = session['username']
    hosts = load_hosts()
    vms_stats = []
    metadata = load_metadata()
    
    for host in hosts:
        if not host.get('enabled', True):
            continue
            
        conn = get_libvirt_conn(host['uri'])
        if not conn:
            continue
        
        try:
            domains = conn.listAllDomains()
            for dom in domains:
                try:
                    full_name = dom.name()
                    
                    # Extraire le propriétaire depuis le nom de la VM
                    vm_owner = get_vm_owner(full_name)
                    if not vm_owner:
                        # Fallback: chercher dans les métadonnées
                        vm_owner = metadata.get(full_name, {}).get('user', 'unknown')
                    
                    # Filtrer par utilisateur (sauf admin qui voit tout)
                    if session['role'] != 'admin' and vm_owner != username:
                        continue
                    
                    state, maxmem, mem, ncpu, cputime = dom.info()
                    
                    status_text = "Stopped"
                    if state == libvirt.VIR_DOMAIN_RUNNING:
                        status_text = "Running"
                    elif state == libvirt.VIR_DOMAIN_PAUSED:
                        status_text = "Paused"
                    
                    ip_addr = "N/A"
                    used_mem_mb = mem / 1024
                    
                    if state == libvirt.VIR_DOMAIN_RUNNING:
                        try:
                            ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
                            for _, val in ifaces.items():
                                if val['addrs']:
                                    for addr in val['addrs']:
                                        if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                                            ip_addr = addr['addr']
                                            break
                        except:
                            pass
                        
                        try:
                            mem_stats = dom.memoryStats()
                            if 'rss' in mem_stats:
                                used_mem_mb = mem_stats['rss'] / 1024
                        except:
                            pass
                    
                    vm_meta = metadata.get(full_name, {})
                    # Afficher le nom court (sans préfixe utilisateur)
                    display_name = get_user_vm_name(full_name)
                    
                    vms_stats.append({
                        'name': full_name,  # Nom complet pour les actions
                        'display_name': display_name,  # Nom court pour l'affichage
                        'status': status_text,
                        'ip': ip_addr,
                        'username': vm_owner,
                        'cpu_time': cputime,
                        'vcpu': ncpu,
                        'max_mem': maxmem / 1024,
                        'used_mem': used_mem_mb,
                        'timestamp': time.time(),
                        'flavor': vm_meta.get('flavor', 'unknown'),
                        'host': host['name']
                    })
                except libvirt.libvirtError:
                    continue
        except Exception as e:
            print(f"Erreur monitoring hôte {host['name']}: {e}", file=sys.stderr)
        finally:
            if conn:
                conn.close()
    
    return jsonify(vms_stats)

# --- API CONTROL ---
@app.route('/api/vm/<name>/<action>', methods=['POST'])
@login_required
def vm_action(name, action):
    username = session['username']
    metadata = load_metadata()
    
    # Extraire le propriétaire depuis le nom complet
    vm_owner = get_vm_owner(name)
    if not vm_owner:
        # Fallback: chercher dans les métadonnées
        vm_owner = metadata.get(name, {}).get('user')
    
    # Vérifier que l'utilisateur est propriétaire (sauf admin)
    if session['role'] != 'admin' and vm_owner != username:
        return jsonify({'success': False, 'msg': 'Non autorisé'}), 403
    
    # Trouver l'hôte de la VM
    vm_host = metadata.get(name, {}).get('host', 'qemu:///system')
    
    conn = get_libvirt_conn(vm_host)
    if not conn:
        return jsonify({'success': False, 'msg': 'KVM Down'}), 500
    
    try:
        dom = conn.lookupByName(name)
        if action == 'start' and not dom.isActive():
            dom.create()
        elif action == 'stop' and dom.isActive():
            try:
                dom.destroy()
            except:
                pass
        elif action == 'delete':
            if dom.isActive():
                dom.destroy()
            dom.undefine()
            
            # Nettoyage métadonnées
            if name in metadata:
                del metadata[name]
                save_metadata(metadata)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'msg': str(e)}), 500
    finally:
        if conn:
            conn.close()

# --- DEPLOY ---
@app.route('/deploy', methods=['POST'])
@login_required
def deploy():
    username = session['username']
    
    try:
        hostname = request.form['hostname']
        password = request.form['password']
        flavor_id = request.form['flavor']
        os_type = request.form.get('os_type', 'ubuntu')
        
        if not re.match(r'^[a-zA-Z0-9-]+$', hostname):
            return jsonify({'success': False, 'msg': 'Hostname invalide'}), 400
        
        # Vérifier que le flavor existe
        if flavor_id not in FLAVORS:
            return jsonify({'success': False, 'msg': 'Flavor invalide'}), 400
        
        flavor = FLAVORS[flavor_id]
        vcpu = flavor['vcpu']
        ram = flavor['ram']
        disk_size = flavor['disk']
        
        # Générer le nom complet unique avec préfixe utilisateur
        full_vm_name = get_full_vm_name(username, hostname)
        
        # Sélectionner l'hôte optimal selon priorité et ressources
        best_host = select_best_host(vcpu, ram, disk_size)
        if not best_host:
            return jsonify({
                'success': False, 
                'msg': 'Ressources insuffisantes sur tous les hôtes KVM'
            }), 503
        
        print(f"Déploiement de '{full_vm_name}' sur {best_host['name']} (URI: {best_host['uri']})")
        
        # Créer le réseau utilisateur si nécessaire
        if not create_user_network(username, best_host['uri']):
            return jsonify({'success': False, 'msg': 'Erreur création réseau utilisateur'}), 500
        
        # Vérifier si VM existe déjà (avec le nom complet)
        conn = get_libvirt_conn(best_host['uri'])
        if not conn:
            return jsonify({'success': False, 'msg': 'Impossible de se connecter à l\'hôte'}), 500
        
        try:
            conn.lookupByName(full_vm_name)
            conn.close()
            return jsonify({
                'success': False, 
                'msg': f'Une VM nommée "{hostname}" existe déjà dans votre espace'
            }), 409
        except:
            pass
        finally:
            if conn:
                conn.close()
        
        # Sauvegarder les métadonnées avec le nom complet
        meta = load_metadata()
        meta[full_vm_name] = {
            'user': username,
            'created_at': time.time(),
            'flavor': flavor_id,
            'host': best_host['uri'],
            'host_name': best_host['name'],
            'display_name': hostname  # Nom court original
        }
        save_metadata(meta)
        
        # Récupérer le chemin de stockage de l'hôte
        storage_path = best_host.get('storage_path', VM_STORAGE_DIR)
        base_image_path = OS_IMAGES.get(os_type, OS_IMAGES['ubuntu'])
        
        # Gestion SSH
        ssh_method = request.form.get('ssh_method')
        final_ssh_pub_key = ""
        
        if ssh_method == 'paste':
            final_ssh_pub_key = request.form.get('ssh_key_paste', '').strip()
        
        # Création VM avec nom complet unique
        vm_disk = f"{storage_path}/{full_vm_name}.qcow2"
        seed_iso = f"{GEN_DIR}/{full_vm_name}-seed.iso"
        user_data = f"{GEN_DIR}/{full_vm_name}-user-data"
        meta_data = f"{GEN_DIR}/{full_vm_name}-meta-data"
        
        # Créer le disque (sur l'hôte distant si nécessaire)
        if best_host['uri'].startswith('qemu+ssh://'):
            # Extraction du host SSH
            ssh_host = best_host['uri'].split('@')[1].split('/')[0]
            ssh_user = best_host['uri'].split('//')[1].split('@')[0]
            
            # Créer le disque via SSH
            subprocess.run([
                "ssh", f"{ssh_user}@{ssh_host}",
                f"qemu-img create -f qcow2 -F qcow2 -b {base_image_path} {vm_disk} {disk_size}G"
            ], check=True)
        else:
            # Hôte local
            subprocess.run([
                "qemu-img", "create", "-f", "qcow2", "-F", "qcow2",
                "-b", base_image_path, vm_disk, f"{disk_size}G"
            ], check=True)
        
        ssh_block = f"\n      - {final_ssh_pub_key}" if final_ssh_pub_key else ""
        
        # Utiliser le hostname original (sans préfixe) pour le hostname interne de la VM
        ud_content = f"""#cloud-config
hostname: {hostname}
manage_etc_hosts: true
users:
  - default
  - name: {username}
    groups: sudo
    shell: /bin/bash
    lock_passwd: false
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:{ssh_block}
chpasswd:
  list: |
    {username}:{password}
  expire: true
ssh_pwauth: true
package_update: false
package_upgrade: false
write_files:
  - path: /etc/netplan/99-custom.yaml
    content: |
      network:
        version: 2
        ethernets:
          main: {{match: {{name: "e*"}}, dhcp4: true}}
    permissions: '0600'
runcmd:
  - netplan apply
  - systemctl start qemu-guest-agent
"""
        with open(user_data, 'w') as f:
            f.write(ud_content)
        with open(meta_data, 'w') as f:
            f.write(f"instance-id: {full_vm_name}\nlocal-hostname: {hostname}")
        
        subprocess.run(["cloud-localds", seed_iso, user_data, meta_data], check=True)
        
        # Copier le seed.iso sur l'hôte distant si nécessaire
        if best_host['uri'].startswith('qemu+ssh://'):
            ssh_host = best_host['uri'].split('@')[1].split('/')[0]
            ssh_user = best_host['uri'].split('//')[1].split('@')[0]
            remote_seed = f"{storage_path}/{full_vm_name}-seed.iso"
            
            subprocess.run([
                "scp", seed_iso, f"{ssh_user}@{ssh_host}:{remote_seed}"
            ], check=True)
            
            seed_iso = remote_seed
        
        variant = "ubuntu22.04" if os_type == 'ubuntu' else "debian11"
        network_name = get_user_network_name(username)
        
        # Déployer avec le nom complet unique
        subprocess.run([
            "virt-install",
            f"--name={full_vm_name}",
            f"--vcpus={vcpu}",
            f"--memory={ram}",
            f"--disk=path={vm_disk},device=disk,bus=virtio",
            f"--disk=path={seed_iso},device=cdrom",
            f"--os-variant={variant}",
            "--import",
            "--noautoconsole",
            "--graphics=none",
            "--network", f"network={network_name},model=virtio",
            "--connect", best_host['uri']
        ], check=True)
        
        return jsonify({
            'success': True,
            'msg': f'VM "{hostname}" déployée avec succès sur {best_host["name"]}',
            'host': best_host['name'],
            'flavor': flavor['name'],
            'vm_name': full_vm_name
        })
    
    except Exception as e:
        print(f"Erreur déploiement: {e}", file=sys.stderr)
        return jsonify({'success': False, 'msg': str(e)}), 500


##  Modification pour docker swarm

@app.route('/swarm')
@login_required
def swarm_page():
    return render_template('swarm.html', username=session['username'])

@app.route('/api/swarm/clusters', methods=['GET'])
@login_required
def get_user_clusters():
    """Récupère les clusters Swarm de l'utilisateur"""
    username = session['username']
    clusters = load_swarm_clusters()
    user_clusters = {k: v for k, v in clusters.items() if v['owner'] == username}
    return jsonify(user_clusters)


def create_swarm_network(network_name, host_uri='qemu:///system'):
    """Crée un réseau dédié pour un cluster Swarm"""
    conn = get_libvirt_conn(host_uri)
    if not conn:
        print(f"Impossible de se connecter à {host_uri}", file=sys.stderr)
        return False
    
    try:
        # Vérifier si le réseau existe déjà
        try:
            net = conn.networkLookupByName(network_name)
            if net.isActive():
                print(f"Réseau {network_name} déjà actif")
                return True
            net.create()
            print(f"Réseau {network_name} démarré")
            return True
        except libvirt.libvirtError:
            pass  # Le réseau n'existe pas, on le crée
        
        # Générer une plage IP unique
        ip_suffix = abs(hash(network_name)) % 240 + 10
        network_ip = f"192.168.{ip_suffix}"
        
        network_xml = f"""
<network>
  <name>{network_name}</name>
  <forward mode='nat'/>
  <bridge name='virbr_{ip_suffix}' stp='on' delay='0'/>
  <ip address='{network_ip}.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='{network_ip}.10' end='{network_ip}.200'/>
    </dhcp>
  </ip>
</network>
"""
        print(f"Création réseau {network_name} sur {host_uri}")
        net = conn.networkDefineXML(network_xml)
        net.setAutostart(1)
        net.create()
        print(f"Réseau {network_name} créé avec succès")
        return True
    except Exception as e:
        print(f"Erreur création réseau {network_name}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False
    finally:
        if conn:
            conn.close()


@app.route('/api/swarm/deploy', methods=['POST'])
@login_required
def deploy_swarm_cluster():
    """Déploie un nouveau cluster Docker Swarm"""
    username = session['username']
    data = request.json
    
    try:
        cluster_name = data.get('cluster_name', f'swarm-{username}-{int(time.time())}')
        num_managers = int(data.get('num_managers', 1))
        num_workers = int(data.get('num_workers', 2))
        
        # Validation: nombre de managers doit être impair
        if num_managers % 2 == 0:
            return jsonify({'success': False, 'msg': 'Le nombre de managers doit être impair (1, 3, 5...)'}), 400
        
        total_nodes = num_managers + num_workers
        if total_nodes > 10:
            return jsonify({'success': False, 'msg': 'Maximum 10 nœuds par cluster'}), 400
        
        # 1. Sélectionner l'hôte optimal
        best_host = select_best_host(2 * total_nodes, 4096 * total_nodes, 15 * total_nodes) 
        if not best_host:
            return jsonify({'success': False, 'msg': 'Ressources insuffisantes sur les hôtes KVM'}), 503
        
        # 2. CORRECTION: Créer le réseau avec un nom fixe
        cluster_network = f"swarm_{username}_{cluster_name}"
        
        # 3. Créer le réseau sur l'hôte sélectionné
        if not create_swarm_network(cluster_network, best_host['uri']):
            return jsonify({'success': False, 'msg': f"Erreur création réseau sur {best_host['name']}"}), 500
        
        # Déployer les nœuds
        nodes = []
        cluster_ip_base = f"192.168.{abs(hash(cluster_network)) % 240 + 10}"
        
        # Générer le cloud-init pour Docker Swarm
        def generate_swarm_cloudinit(node_name, node_type, ip_address):
            return f"""#cloud-config
hostname: {node_name}
manage_etc_hosts: true
users:
  - default
  - name: {username}
    groups: sudo, docker
    shell: /bin/bash
    lock_passwd: false
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - {data.get('ssh_key', '')}
chpasswd:
  list: |
    {username}:{data.get('password', 'changeme')}
  expire: false
ssh_pwauth: true
package_update: true
package_upgrade: true
packages:
  - apt-transport-https
  - ca-certificates
  - curl
  - gnupg
  - lsb-release
write_files:
  - path: /etc/netplan/99-custom.yaml
    content: |
      network:
        version: 2
        ethernets:
          main: {{match: {{name: "e*"}}, dhcp4: false, addresses: [{ip_address}/24], gateway4: {cluster_ip_base}.1, nameservers: {{addresses: [8.8.8.8, 8.8.4.4]}}}}
    permissions: '0600'
  - path: /usr/local/bin/setup-docker.sh
    content: |
      #!/bin/bash
      # Installation Docker
      curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
      echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
      apt-get update
      apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
      systemctl enable docker
      systemctl start docker
      usermod -aG docker {username}
      
      # Configuration Firewall pour Swarm
      ufw allow 2377/tcp  # Cluster management
      ufw allow 7946/tcp  # Node communication
      ufw allow 7946/udp  # Node communication
      ufw allow 4789/udp  # Overlay network
      ufw allow 22/tcp    # SSH
      echo "y" | ufw enable
      
      # Marquer comme prêt
      touch /var/lib/cloud/docker-ready
    permissions: '0755'
runcmd:
  - netplan apply
  - /usr/local/bin/setup-docker.sh
  - systemctl start qemu-guest-agent
"""
        
        # Déployer les managers
        for i in range(num_managers):
            node_name = f"{cluster_name}-manager-{i+1}"
            full_vm_name = get_full_vm_name(username, node_name)
            ip_address = f"{cluster_ip_base}.{10 + i}"
            
            # Créer la VM - PASSER LE HOST ET LE NETWORK
            result = deploy_swarm_node(
                username=username,
                node_name=node_name,
                full_vm_name=full_vm_name,
                cluster_network=cluster_network,
                cloud_init=generate_swarm_cloudinit(node_name, 'manager', ip_address),
                ip_address=ip_address,
                best_host=best_host  # AJOUT: passer l'hôte
            )
            
            if not result['success']:
                return jsonify({'success': False, 'msg': f'Erreur déploiement {node_name}: {result.get("msg", "")}'}), 500

            nodes.append({
                'name': node_name,
                'full_name': full_vm_name,
                'type': 'manager',
                'ip': ip_address,
                'status': 'deploying'
            })
        
        # Déployer les workers
        for i in range(num_workers):
            node_name = f"{cluster_name}-worker-{i+1}"
            full_vm_name = get_full_vm_name(username, node_name)
            ip_address = f"{cluster_ip_base}.{20 + i}"
            
            result = deploy_swarm_node(
                username=username,
                node_name=node_name,
                full_vm_name=full_vm_name,
                cluster_network=cluster_network,
                cloud_init=generate_swarm_cloudinit(node_name, 'worker', ip_address),
                ip_address=ip_address,
                best_host=best_host  # AJOUT: passer l'hôte
            )
            
            if not result['success']:
                return jsonify({'success': False, 'msg': f'Erreur déploiement {node_name}: {result.get("msg", "")}'}), 500
            
            nodes.append({
                'name': node_name,
                'full_name': full_vm_name,
                'type': 'worker',
                'ip': ip_address,
                'status': 'deploying'
            })
        
        # Sauvegarder les informations du cluster
        clusters = load_swarm_clusters()
        manager_ip = nodes[0]['ip']
        
        clusters[cluster_name] = {
            'owner': username,
            'created_at': time.time(),
            'network': cluster_network,
            'nodes': nodes,
            'status': 'deploying',
            'manager_ip': manager_ip,
            'host': best_host['uri'],  # AJOUT: sauvegarder l'hôte
            'init_commands': {
                'init_swarm': f"ssh {username}@{manager_ip} 'sudo docker swarm init --advertise-addr {manager_ip}'",
                'get_manager_token': f"ssh {username}@{manager_ip} 'sudo docker swarm join-token manager -q'",
                'get_worker_token': f"ssh {username}@{manager_ip} 'sudo docker swarm join-token worker -q'"
            }
        }
        
        save_swarm_clusters(clusters)
        
        return jsonify({
            'success': True,
            'cluster_name': cluster_name,
            'nodes': nodes,
            'manager_ip': manager_ip,
            'message': f'Cluster {cluster_name} en cours de déploiement'
        })
        
    except Exception as e:
        print(f"Erreur déploiement Swarm: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'msg': str(e)}), 500

def deploy_swarm_node(username, node_name, full_vm_name, cluster_network, cloud_init, ip_address, best_host):
    """Déploie un nœud individuel du cluster Swarm"""
    try:
        # NE PAS resélectionner l'hôte, utiliser celui passé en paramètre
        storage_path = best_host.get('storage_path', VM_STORAGE_DIR)
        base_image_path = OS_IMAGES['ubuntu']
        
        # Créer le disque
        vm_disk = f"{storage_path}/{full_vm_name}.qcow2"
        seed_iso = f"{GEN_DIR}/{full_vm_name}-seed.iso"
        user_data = f"{GEN_DIR}/{full_vm_name}-user-data"
        meta_data = f"{GEN_DIR}/{full_vm_name}-meta-data"
        
        # Créer le disque (local ou distant)
        if best_host['uri'].startswith('qemu+ssh://'):
            ssh_host = best_host['uri'].split('@')[1].split('/')[0]
            ssh_user = best_host['uri'].split('//')[1].split('@')[0]
            subprocess.run([
                "ssh", f"{ssh_user}@{ssh_host}",
                f"qemu-img create -f qcow2 -F qcow2 -b {base_image_path} {vm_disk} 30G"
            ], check=True)
        else:
            subprocess.run([
                "qemu-img", "create", "-f", "qcow2", "-F", "qcow2",
                "-b", base_image_path, vm_disk, "30G"
            ], check=True)
        
        # Écrire cloud-init
        with open(user_data, 'w') as f:
            f.write(cloud_init)
        with open(meta_data, 'w') as f:
            f.write(f"instance-id: {full_vm_name}\nlocal-hostname: {node_name}")
        
        subprocess.run(["cloud-localds", seed_iso, user_data, meta_data], check=True)
        
        # Copier seed.iso si distant
        if best_host['uri'].startswith('qemu+ssh://'):
            ssh_host = best_host['uri'].split('@')[1].split('/')[0]
            ssh_user = best_host['uri'].split('//')[1].split('@')[0]
            remote_seed = f"{storage_path}/{full_vm_name}-seed.iso"
            subprocess.run(["scp", seed_iso, f"{ssh_user}@{ssh_host}:{remote_seed}"], check=True)
            seed_iso = remote_seed
        
        # Déployer la VM
        print(f"Déploiement de {full_vm_name} sur réseau {cluster_network}")
        subprocess.run([
            "virt-install",
            f"--name={full_vm_name}",
            f"--vcpus=2",
            f"--memory=4096",
            f"--disk=path={vm_disk},device=disk,bus=virtio",
            f"--disk=path={seed_iso},device=cdrom",
            f"--os-variant=ubuntu22.04",
            "--import",
            "--noautoconsole",
            "--graphics=none",
            "--network", f"network={cluster_network},model=virtio",
            "--connect", best_host['uri']
        ], check=True)
        
        # Sauvegarder métadonnées
        meta = load_metadata()
        meta[full_vm_name] = {
            'user': username,
            'created_at': time.time(),
            'flavor': 'swarm',
            'host': best_host['uri'],
            'host_name': best_host['name'],
            'display_name': node_name,
            'cluster_node': True,
            'node_ip': ip_address,
            'network': cluster_network
        }
        save_metadata(meta)
        
        return {'success': True}
        
    except Exception as e:
        print(f"Erreur déploiement nœud: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {'success': False, 'msg': str(e)}

@app.route('/api/swarm/cluster/<cluster_name>/status', methods=['GET'])
@login_required
def get_cluster_status(cluster_name):
    """Récupère le statut d'un cluster"""
    username = session['username']
    clusters = load_swarm_clusters()
    
    if cluster_name not in clusters or clusters[cluster_name]['owner'] != username:
        return jsonify({'success': False, 'msg': 'Cluster non trouvé'}), 404
    
    cluster = clusters[cluster_name]
    
    # Vérifier si les nœuds sont prêts
    all_ready = True
    for node in cluster['nodes']:
        # Ici vous pouvez vérifier si Docker est installé via SSH
        pass
    
    return jsonify({
        'success': True,
        'cluster': cluster,
        'ready': all_ready
    })

@app.route('/api/swarm/cluster/<cluster_name>', methods=['DELETE'])
@login_required
def delete_cluster(cluster_name):
    """Supprime un cluster complet"""
    username = session['username']
    clusters = load_swarm_clusters()
    
    if cluster_name not in clusters or clusters[cluster_name]['owner'] != username:
        return jsonify({'success': False, 'msg': 'Cluster non trouvé'}), 404
    
    cluster = clusters[cluster_name]
    
    # Supprimer toutes les VMs du cluster
    for node in cluster['nodes']:
        # Code de suppression VM existant
        pass
    
    # Supprimer le cluster de la base
    del clusters[cluster_name]
    save_swarm_clusters(clusters)
    
    return jsonify({'success': True, 'msg': f'Cluster {cluster_name} supprimé'})


##  Fin modification pour docker swarm

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)