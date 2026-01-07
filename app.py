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

OS_IMAGES = {
    'ubuntu': os.path.join(BASE_IMG_DIR, "base-ubuntu.qcow2"),
    'debian': os.path.join(BASE_IMG_DIR, "base-debian.qcow2")
}

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
    if os.path.exists(HOSTS_FILE):
        try:
            with open(HOSTS_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    # Configuration par défaut avec l'hôte local
    return [{
        'id': 'local',
        'name': 'Local KVM',
        'uri': 'qemu:///system',
        'enabled': True
    }]

def save_hosts(hosts):
    with open(HOSTS_FILE, 'w') as f:
        json.dump(hosts, f, indent=2)

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
    try:
        return libvirt.open(host_uri)
    except libvirt.libvirtError as e:
        print(f"ERREUR CRITIQUE LIBVIRT: {e}", file=sys.stderr)
        return None

# --- GESTION RÉSEAU ---
def get_user_network_name(username):
    """Génère le nom du réseau pour un utilisateur"""
    return f"net_{username}"

def create_user_network(username, host_uri='qemu:///system'):
    """Crée un réseau isolé pour l'utilisateur"""
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

# --- SÉLECTION HÔTE (LEAST USED) ---
def get_host_resources(host_uri):
    """Récupère les ressources utilisées et disponibles sur un hôte"""
    conn = get_libvirt_conn(host_uri)
    if not conn:
        return None
    
    try:
        # Capacités totales
        nodeinfo = conn.getInfo()
        total_memory = nodeinfo[1]  # MiB
        total_cpus = nodeinfo[2]
        
        # Ressources utilisées
        used_memory = 0
        used_cpus = 0
        
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
            'available_memory': total_memory - used_memory,
            'available_cpus': total_cpus - used_cpus
        }
    except Exception as e:
        print(f"Erreur récupération ressources: {e}", file=sys.stderr)
        return None
    finally:
        if conn:
            conn.close()

def select_best_host(required_vcpu, required_ram):
    """Sélectionne l'hôte le moins chargé avec ressources suffisantes"""
    hosts = load_hosts()
    best_host = None
    min_load = float('inf')
    
    for host in hosts:
        if not host.get('enabled', True):
            continue
        
        resources = get_host_resources(host['uri'])
        if not resources:
            continue
        
        # Vérifier si l'hôte a assez de ressources
        if (resources['available_cpus'] >= required_vcpu and 
            resources['available_memory'] >= required_ram):
            
            # Calculer le taux de charge (moyenne CPU et RAM)
            cpu_load = resources['used_cpus'] / resources['total_cpus']
            mem_load = resources['used_memory'] / resources['total_memory']
            avg_load = (cpu_load + mem_load) / 2
            
            if avg_load < min_load:
                min_load = avg_load
                best_host = host
    
    return best_host

# --- DÉCORATEURS AUTHENTIFICATION ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
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
                         flavors=FLAVORS)

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
                    name = dom.name()
                    
                    # Filtrer par utilisateur (sauf admin qui voit tout)
                    vm_owner = metadata.get(name, {}).get('user', 'root')
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
                    
                    vm_meta = metadata.get(name, {})
                    
                    vms_stats.append({
                        'name': name,
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
            
            return jsonify(vms_stats)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
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
    
    # Vérifier que l'utilisateur est propriétaire (sauf admin)
    vm_owner = metadata.get(name, {}).get('user')
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
            try:
                os.remove(f"{VM_STORAGE_DIR}/{name}.qcow2")
            except:
                pass
            
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
            return "Hostname invalide", 400
        
        # Vérifier que le flavor existe
        if flavor_id not in FLAVORS:
            return "Flavor invalide", 400
        
        flavor = FLAVORS[flavor_id]
        vcpu = flavor['vcpu']
        ram = flavor['ram']
        disk_size = flavor['disk']
        
        # Sélectionner l'hôte optimal
        best_host = select_best_host(vcpu, ram)
        if not best_host:
            return "Ressources insuffisantes sur tous les hôtes", 503
        
        # Créer le réseau utilisateur si nécessaire
        if not create_user_network(username, best_host['uri']):
            return "Erreur création réseau utilisateur", 500
        
        # Sauvegarder les métadonnées
        meta = load_metadata()
        meta[hostname] = {
            'user': username,
            'created_at': time.time(),
            'flavor': flavor_id,
            'host': best_host['uri']
        }
        save_metadata(meta)
        
        base_image_path = OS_IMAGES.get(os_type, OS_IMAGES['ubuntu'])
        
        # Gestion SSH
        ssh_method = request.form.get('ssh_method')
        final_ssh_pub_key = ""
        generated_key_path = None
        
        if ssh_method == 'paste':
            final_ssh_pub_key = request.form.get('ssh_key_paste', '').strip()
        
        # Vérifier si VM existe déjà
        conn = get_libvirt_conn(best_host['uri'])
        try:
            conn.lookupByName(hostname)
            conn.close()
            return f"La VM '{hostname}' existe déjà", 409
        except:
            pass
        finally:
            if conn:
                conn.close()
        
        # Création VM
        vm_disk = f"{VM_STORAGE_DIR}/{hostname}.qcow2"
        seed_iso = f"{GEN_DIR}/{hostname}-seed.iso"
        user_data = f"{GEN_DIR}/{hostname}-user-data"
        meta_data = f"{GEN_DIR}/{hostname}-meta-data"
        
        subprocess.run([
            "qemu-img", "create", "-f", "qcow2", "-F", "qcow2",
            "-b", base_image_path, vm_disk, f"{disk_size}G"
        ], check=True)
        
        ssh_block = f"\n      - {final_ssh_pub_key}" if final_ssh_pub_key else ""
        
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
            f.write(f"instance-id: {hostname}\nlocal-hostname: {hostname}")
        
        subprocess.run(["cloud-localds", seed_iso, user_data, meta_data], check=True)
        
        variant = "ubuntu22.04" if os_type == 'ubuntu' else "debian11"
        network_name = get_user_network_name(username)
        
        subprocess.run([
            "virt-install",
            f"--name={hostname}",
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
            'msg': 'Déploiement initié',
            'host': best_host['name'],
            'flavor': flavor['name']
        })
    
    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
