import os
import subprocess
import libvirt
import uuid
import time
import re
import io
import shutil
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__)

# --- CONFIGURATION (MODE LOCAL / TOUT-EN-UN) ---
# Chemins vers le stockage KVM de ton PC
VM_STORAGE_DIR = "/var/lib/libvirt/images"
BASE_IMG_DIR = "/var/lib/libvirt/images/base-images"

# Chemins des fichiers temporaires (Générés par le script)
GEN_DIR = os.path.join(os.getcwd(), 'generated')
KEYS_DIR = os.path.join(os.getcwd(), 'keys')

# Création des dossiers si absents
os.makedirs(GEN_DIR, exist_ok=True)
os.makedirs(KEYS_DIR, exist_ok=True)

# Dictionnaire des images (Doivent être présentes sur ton PC via setup.sh)
OS_IMAGES = {
    'ubuntu': os.path.join(BASE_IMG_DIR, "ubuntu-22.04-server-cloudimg-amd64.img"),
    'debian': os.path.join(BASE_IMG_DIR, "debian-12-generic-amd64.qcow2")
}

def get_libvirt_conn():
    """Ouvre une connexion locale au démon système KVM"""
    # qemu:///system = Droits root, accès réseau complet
    return libvirt.open('qemu:///system')

@app.route('/')
def index():
    return render_template('index.html')

# --- API MONITORING (TEMPS RÉEL) ---
@app.route('/api/monitor')
def monitor_api():
    conn = None
    vms_stats = []
    try:
        conn = get_libvirt_conn()
        # On récupère TOUTES les VMs (actives et inactives)
        domains = conn.listAllDomains()
        
        for dom in domains:
            try:
                name = dom.name()
                state, maxmem, mem, ncpu, cputime = dom.info()
                
                status_text = "Stopped"
                if state == libvirt.VIR_DOMAIN_RUNNING: status_text = "Running"
                elif state == libvirt.VIR_DOMAIN_PAUSED: status_text = "Paused"
                
                ip_addr = "N/A"
                used_mem_mb = mem / 1024 # Valeur par défaut

                if state == libvirt.VIR_DOMAIN_RUNNING:
                    # 1. Récupération IP via les baux DHCP (Leases)
                    try:
                        ifaces = dom.interfaceAddresses(libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE)
                        for _, val in ifaces.items():
                            if val['addrs']:
                                for addr in val['addrs']:
                                    if addr['type'] == libvirt.VIR_IP_ADDR_TYPE_IPV4:
                                        ip_addr = addr['addr']
                                        break
                    except: pass
                    
                    # 2. Récupération RAM Réelle (RSS via Guest Agent)
                    try:
                        mem_stats = dom.memoryStats()
                        if 'rss' in mem_stats:
                            used_mem_mb = mem_stats['rss'] / 1024
                    except: pass

                vms_stats.append({
                    'name': name,
                    'status': status_text,
                    'ip': ip_addr,
                    'cpu_time': cputime, # Nanosecondes brutes pour calcul différentiel JS
                    'vcpu': ncpu,
                    'max_mem': maxmem / 1024,
                    'used_mem': used_mem_mb,
                    'timestamp': time.time()
                })
            except libvirt.libvirtError:
                continue # La VM a peut-être été supprimée pendant la boucle
                
        return jsonify(vms_stats)
    except Exception as e:
        return jsonify([])
    finally:
        if conn: conn.close()

# --- API CONTROL (START/STOP/DELETE) ---
@app.route('/api/vm/<name>/<action>', methods=['POST'])
def vm_action(name, action):
    conn = get_libvirt_conn()
    try:
        dom = conn.lookupByName(name)
        
        if action == 'start' and not dom.isActive():
            dom.create()
            
        elif action == 'stop' and dom.isActive():
            try:
                dom.destroy() # Arrêt forcé (plus fiable pour un lab)
            except: pass
            
        elif action == 'delete':
            if dom.isActive():
                dom.destroy()
            dom.undefine()
            # Nettoyage optionnel du disque local
            try: os.remove(f"{VM_STORAGE_DIR}/{name}.qcow2")
            except: pass
            
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'msg': str(e)}), 500
    finally:
        conn.close()

# --- DEPLOY (PIPELINE DE CRÉATION) ---
@app.route('/deploy', methods=['POST'])
def deploy():
    conn = None
    try:
        # 1. Récupération & Validation
        hostname = request.form['hostname']
        username = request.form['username']
        password = request.form['password']
        vcpu = int(request.form['vcpu'])
        ram = int(request.form['ram'])
        disk_size = int(request.form['disk'])
        os_type = request.form.get('os_type', 'ubuntu')

        # Sécurité (Sanitization)
        if not re.match(r'^[a-zA-Z0-9-]+$', hostname): return "Hostname invalide", 400
        if not re.match(r'^[a-z0-9-]+$', username): return "Username invalide", 400

        # Vérification espace disque
        total, used, free = shutil.disk_usage(VM_STORAGE_DIR)
        needed = disk_size * 1024**3
        if free < needed: return "Espace disque insuffisant sur le serveur", 507

        base_image_path = OS_IMAGES.get(os_type, OS_IMAGES['ubuntu'])

        # 2. Gestion SSH (AWS Style)
        ssh_method = request.form.get('ssh_method')
        final_ssh_pub_key = ""
        generated_key_path = None

        if ssh_method == 'paste':
            final_ssh_pub_key = request.form.get('ssh_key_paste', '').strip()
            
        elif ssh_method == 'generate':
            key_name = request.form.get('ssh_key_name', '').strip()
            if not key_name: return "Nom de clé manquant", 400
            
            priv_path = os.path.join(KEYS_DIR, key_name)
            pub_path = priv_path + ".pub"
            
            # Génération
            subprocess.run(['ssh-keygen', '-q', '-t', 'rsa', '-b', '2048', '-N', '', '-f', priv_path], check=True)
            
            # Correction des droits (pour que l'utilisateur non-root puisse télécharger plus tard)
            real_user = int(os.environ.get('SUDO_UID', os.getuid()))
            real_group = int(os.environ.get('SUDO_GID', os.getgid()))
            os.chown(priv_path, real_user, real_group)
            os.chown(pub_path, real_user, real_group)
            os.chmod(priv_path, 0o600) # Sécurité SSH
            
            with open(pub_path, 'r') as f: final_ssh_pub_key = f.read().strip()
            generated_key_path = key_name # Signal pour le frontend

        # 3. Check Anti-Conflit
        conn = get_libvirt_conn()
        try:
            conn.lookupByName(hostname)
            conn.close()
            return f"La VM '{hostname}' existe déjà", 409
        except: pass
        finally: 
            if conn: conn.close()

        # 4. Cloud-init & Fichiers
        request_id = str(uuid.uuid4())[:8]
        vm_disk = f"{VM_STORAGE_DIR}/{hostname}.qcow2"
        seed_iso = f"{GEN_DIR}/{hostname}-seed.iso"
        user_data = f"{GEN_DIR}/{hostname}-user-data"
        meta_data = f"{GEN_DIR}/{hostname}-meta-data"
        
        # Création du disque (Copy-On-Write)
        subprocess.run(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", base_image_path, vm_disk, f"{disk_size}G"], check=True)
        
        ssh_block = f"\n      - {final_ssh_pub_key}" if final_ssh_pub_key else ""
        
        # Configuration Cloud-init TURBO
        ud_content = f"""#cloud-config
hostname: {hostname}
manage_etc_hosts: true
users:
  - default
  - name: {username}
    passwd: {password}
    groups: sudo
    shell: /bin/bash
    lock_passwd: false
    ssh_authorized_keys:{ssh_block}

# Sécurité & Accès
ssh_pwauth: true
chpasswd: {{ expire: true }}

# OPTIMISATIONS (Mode Turbo)
package_update: false
package_upgrade: false

# Forçage Réseau (Netplan V2)
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
        
        # Création de l'ISO Seed
        subprocess.run(["cloud-localds", seed_iso, user_data, meta_data], check=True)

        # 5. Lancement VM
        variant = "ubuntu22.04" if os_type == 'ubuntu' else "debian11"
        subprocess.run([
            "virt-install", f"--name={hostname}", f"--vcpus={vcpu}", f"--memory={ram}",
            f"--disk=path={vm_disk},device=disk,bus=virtio", 
            f"--disk=path={seed_iso},device=cdrom",
            f"--os-variant={variant}", "--import", "--noautoconsole", "--graphics=none",
            "--network", "network=default,model=virtio"
        ], check=True)

        return render_template('success.html', hostname=hostname, key_download=generated_key_path)

    except Exception as e: return str(e), 500

# --- TÉLÉCHARGEMENT CLÉ (AWS STYLE : SUPPRESSION APRÈS ENVOI) ---
@app.route('/download_key/<filename>')
def download_key(filename):
    file_path = os.path.join(KEYS_DIR, filename)
    
    if not os.path.exists(file_path):
        return "Erreur : La clé a déjà été téléchargée (Sécurité One-Shot) ou n'existe pas.", 404

    # Lecture en RAM
    return_data = io.BytesIO()
    with open(file_path, 'rb') as fo:
        return_data.write(fo.read())
    return_data.seek(0)

    # Suppression du disque (C'est ici qu'on respecte le modèle AWS)
    os.remove(file_path)
    try: os.remove(file_path + ".pub") # On nettoie aussi la publique
    except: pass

    return send_file(
        return_data,
        as_attachment=True,
        download_name=filename,
        mimetype='application/x-pem-file'
    )

if __name__ == '__main__':
    # 0.0.0.0 = Accessible par tout le monde sur le réseau
    app.run(host='0.0.0.0', port=5000, debug=True)

### Comment préparer ta Démo en Classe :
"""
1.  **Connecte ton PC** au réseau de la salle (Wifi ou Câble).
2.  **Trouve ton IP locale** :
    ```bash
    ip a | grep inet
    ```
    *(Note l'adresse qui ressemble à 192.168.x.x ou 10.x.x.x)*.
3.  **Lance le serveur** :
    ```bash
    sudo python3 app.py
    ```
4.  **Invite le jury** à se connecter depuis leur propre PC :
    * URL : `http://<TON_IP>:5000`
5.  **Fais le show !** Ils cliquent sur leur écran, et la VM apparaît sur le tien (et dans leur liste).

C'est simple, efficace, et ça marche à tous les coups. Bonne chance ! 🚀
""" 