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
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__)

# --- CONFIGURATION ---
VM_STORAGE_DIR = "/var/lib/libvirt/images"
BASE_IMG_DIR = "/var/lib/libvirt/images/base-images"
GEN_DIR = os.path.join(os.getcwd(), 'generated')
KEYS_DIR = os.path.join(os.getcwd(), 'keys')
METADATA_FILE = os.path.join(os.getcwd(), 'vm_metadata.json') # Base de données légère

os.makedirs(GEN_DIR, exist_ok=True)
os.makedirs(KEYS_DIR, exist_ok=True)

OS_IMAGES = {
    'ubuntu': os.path.join(BASE_IMG_DIR, "base-ubuntu-22.04.qcow2"),
    'debian': os.path.join(BASE_IMG_DIR, "base-debian-12.qcow2")
}

# --- GESTION PERSISTANCE (Username) ---
def load_metadata():
    if os.path.exists(METADATA_FILE):
        try:
            with open(METADATA_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def save_metadata(data):
    with open(METADATA_FILE, 'w') as f: json.dump(data, f)

def get_libvirt_conn():
    try:
        return libvirt.open('qemu:///system')
    except libvirt.libvirtError as e:
        print(f"ERREUR CRITIQUE LIBVIRT: {e}", file=sys.stderr)
        return None

@app.route('/')
def index():
    return render_template('index.html')

# --- API MONITORING ---
@app.route('/api/monitor')
def monitor_api():
    conn = get_libvirt_conn()
    if not conn: return jsonify({"error": "No KVM connection"}), 500
        
    vms_stats = []
    metadata = load_metadata() # On charge les infos utilisateurs

    try:
        domains = conn.listAllDomains()
        for dom in domains:
            try:
                name = dom.name()
                state, maxmem, mem, ncpu, cputime = dom.info()
                
                status_text = "Stopped"
                if state == libvirt.VIR_DOMAIN_RUNNING: status_text = "Running"
                elif state == libvirt.VIR_DOMAIN_PAUSED: status_text = "Paused"
                
                ip_addr = "N/A"
                used_mem_mb = mem / 1024
                
                # Récupération du vrai username (sinon 'root' par défaut)
                vm_user = metadata.get(name, {}).get('user', 'root')

                if state == libvirt.VIR_DOMAIN_RUNNING:
                    # IP via Leases
                    try:
                        ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
                        for _, val in ifaces.items():
                            if val['addrs']:
                                for addr in val['addrs']:
                                    if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                                        ip_addr = addr['addr']
                                        break
                    except: pass
                    
                    # RAM RSS
                    try:
                        mem_stats = dom.memoryStats()
                        if 'rss' in mem_stats: used_mem_mb = mem_stats['rss'] / 1024
                    except: pass

                vms_stats.append({
                    'name': name,
                    'status': status_text,
                    'ip': ip_addr,
                    'username': vm_user, # On envoie le vrai user au frontend
                    'cpu_time': cputime,
                    'vcpu': ncpu,
                    'max_mem': maxmem / 1024,
                    'used_mem': used_mem_mb,
                    'timestamp': time.time()
                })
            except libvirt.libvirtError: continue
                
        return jsonify(vms_stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: conn.close()

# --- API CONTROL ---
@app.route('/api/vm/<name>/<action>', methods=['POST'])
def vm_action(name, action):
    conn = get_libvirt_conn()
    if not conn: return jsonify({'success': False, 'msg': 'KVM Down'}), 500
    
    try:
        dom = conn.lookupByName(name)
        if action == 'start' and not dom.isActive(): dom.create()
        elif action == 'stop' and dom.isActive():
            try: dom.destroy()
            except: pass
        elif action == 'delete':
            if dom.isActive(): dom.destroy()
            dom.undefine()
            try: os.remove(f"{VM_STORAGE_DIR}/{name}.qcow2")
            except: pass
            
            # Nettoyage métadonnées
            meta = load_metadata()
            if name in meta:
                del meta[name]
                save_metadata(meta)
            
        return jsonify({'success': True})
    except Exception as e: return jsonify({'success': False, 'msg': str(e)}), 500
    finally:
        if conn: conn.close()

# --- DEPLOY ---
@app.route('/deploy', methods=['POST'])
def deploy():
    conn = None
    try:
        hostname = request.form['hostname']
        username = request.form['username']
        password = request.form['password']
        vcpu = int(request.form['vcpu'])
        ram = int(request.form['ram'])
        disk_size = int(request.form['disk'])
        os_type = request.form.get('os_type', 'ubuntu')

        if not re.match(r'^[a-zA-Z0-9-]+$', hostname): return "Hostname invalide", 400
        if not re.match(r'^[a-z0-9-]+$', username): return "Username invalide", 400

        # Sauvegarde du propriétaire pour plus tard
        meta = load_metadata()
        meta[hostname] = {'user': username, 'created_at': time.time()}
        save_metadata(meta)

        base_image_path = OS_IMAGES.get(os_type, OS_IMAGES['ubuntu'])

        # SSH Logic
        ssh_method = request.form.get('ssh_method')
        final_ssh_pub_key = ""
        generated_key_path = None

        if ssh_method == 'paste':
            final_ssh_pub_key = request.form.get('ssh_key_paste', '').strip()
        elif ssh_method == 'generate':
            key_name = request.form.get('ssh_key_name', '').strip()
            if not key_name: return "Nom clé manquant", 400
            
            priv_path = os.path.join(KEYS_DIR, key_name)
            pub_path = priv_path + ".pub"
            subprocess.run(['ssh-keygen', '-q', '-t', 'rsa', '-b', '2048', '-N', '', '-f', priv_path], check=True)
            
            real_user = int(os.environ.get('SUDO_UID', os.getuid()))
            real_group = int(os.environ.get('SUDO_GID', os.getgid()))
            os.chown(priv_path, real_user, real_group)
            os.chown(pub_path, real_user, real_group)
            os.chmod(priv_path, 0o600)
            
            with open(pub_path, 'r') as f: final_ssh_pub_key = f.read().strip()
            generated_key_path = key_name

        conn = get_libvirt_conn()
        try:
            conn.lookupByName(hostname)
            conn.close()
            return f"La VM '{hostname}' existe déjà", 409
        except: pass
        finally: 
            if conn: conn.close()

        request_id = str(uuid.uuid4())[:8]
        vm_disk = f"{VM_STORAGE_DIR}/{hostname}.qcow2"
        seed_iso = f"{GEN_DIR}/{hostname}-seed.iso"
        user_data = f"{GEN_DIR}/{hostname}-user-data"
        meta_data = f"{GEN_DIR}/{hostname}-meta-data"
        
        subprocess.run(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", base_image_path, vm_disk, f"{disk_size}G"], check=True)
        
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
        with open(user_data, 'w') as f: f.write(ud_content)
        with open(meta_data, 'w') as f: f.write(f"instance-id: {hostname}\nlocal-hostname: {hostname}")
        
        subprocess.run(["cloud-localds", seed_iso, user_data, meta_data], check=True)

        variant = "ubuntu22.04" if os_type == 'ubuntu' else "debian11"
        subprocess.run([
            "virt-install", f"--name={hostname}", f"--vcpus={vcpu}", f"--memory={ram}",
            f"--disk=path={vm_disk},device=disk,bus=virtio", 
            f"--disk=path={seed_iso},device=cdrom",
            f"--os-variant={variant}", "--import", "--noautoconsole", "--graphics=none",
            "--network", "network=default,model=virtio"
        ], check=True)

        return jsonify({'success': True, 'msg': 'Déploiement initié', 'key_file': generated_key_path})

    except Exception as e: return str(e), 500

@app.route('/download_key/<filename>')
def download_key(filename):
    file_path = os.path.join(KEYS_DIR, filename)
    if not os.path.exists(file_path): return "Erreur", 404
    
    return_data = io.BytesIO()
    with open(file_path, 'rb') as fo: return_data.write(fo.read())
    return_data.seek(0)
    
    os.remove(file_path)
    try: os.remove(file_path + ".pub")
    except: pass
    return send_file(return_data, as_attachment=True, download_name=filename, mimetype='application/x-pem-file')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)