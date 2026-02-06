
# ☁️ Mini Cloud PaaS - INF4107

Ce projet est une plateforme de Cloud Computing complète implémentant les couches **IaaS** (Infrastructure as a Service), **CaaS** (Container as a Service via Docker Swarm) et **PaaS** (Platform as a Service).

Développé en **Python/Flask**, il permet d'orchestrer des machines virtuelles KVM, de créer automatiquement des clusters Docker Swarm et de déployer des applications "clé en main" (OwnCloud, PrestaShop, etc.).

## 📋 Fonctionnalités

### 1. IaaS (Infrastructure)
* **Provisioning de VM** : Création de machines virtuelles sur des hôtes KVM (locaux ou distants).
* **Configuration automatique** : Utilisation de `cloud-init` pour l'injection des utilisateurs, clés SSH et pré-installation de Docker.
* **Réseau isolé** : Création automatique de réseaux privés virtuels par utilisateur.
* **Monitoring** : État des VMs (Running, Paused, etc.) et récupération automatique des IP via baux DHCP.

### 2. CaaS & Swarm (Orchestration)
* **Cluster à la demande** : Transformation d'un groupe de VMs en cluster Docker Swarm en un clic.
* **Auto-discovery** : Détection automatique des nœuds Managers et Workers.
* **Réseaux Overlay** : Gestion transparente des réseaux pour la communication inter-conteneurs.

### 3. PaaS (Catalogue d'Apps)
* **Déploiement One-Click** : Catalogue d'applications (OwnCloud, PrestaShop, Odoo, etc.).
* **Génération dynamique** : Création automatique des fichiers `docker-compose.yml` avec gestion des volumes et bases de données.
* **Scaling** : Redimensionnement des services (nombre de réplicas) via l'interface.

---

## 🛠 Prérequis

### Système Hôte (Serveur Flask)
* **OS** : Linux (Ubuntu 20.04/22.04 ou Debian 11/12 recommandé).
* **Virtualisation** : Support CPU pour la virtualisation (VT-x ou AMD-V) activé dans le BIOS.
* **Paquets Système** :
    ```bash
    sudo apt update
    sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils virtinst libvirt-daemon cloud-image-utils python3-pip genisoimage
    ```

### Configuration des Permissions
L'utilisateur qui lance l'application doit avoir accès à Libvirt :
```bash
sudo usermod -aG libvirt $USER
sudo usermod -aG kvm $USER
# Une déconnexion/reconnexion est nécessaire pour appliquer les groupes

```

---

## 🌍 Configuration Multi-Hôtes (Optionnel)

Pour piloter des **hôtes KVM distants**, l'application utilise le protocole `qemu+ssh`. Vous devez configurer une authentification SSH sans mot de passe entre le serveur Flask et les hôtes distants.

1. **Générer une clé SSH sur le serveur Flask** (si ce n'est pas déjà fait) :
```bash
ssh-keygen -t rsa -b 4096
# Appuyez sur Entrée pour laisser la passphrase vide

```


2. **Copier la clé publique vers l'hôte distant** :
Remplacez `user` et `ip_remote` par les infos de votre hôte distant.
```bash
ssh-copy-id user@ip_remote

```


3. **Vérifier la connexion** :
Vous devez pouvoir vous connecter sans mot de passe :
```bash
ssh user@ip_remote "virsh list --all"

```


*Si la commande renvoie la liste des VMs (même vide), la connexion est opérationnelle.*
4. **Ajouter l'hôte dans l'interface** :
Connectez-vous en **Admin**, allez dans l'onglet **Administration > Hôtes**, et ajoutez l'hôte avec l'URI suivante :
`qemu+ssh://user@ip_remote/system`

---

## 🚀 Installation

1. **Cloner le dépôt**
```bash
git clone [https://github.com/astuce55/XickCloud.git](https://github.com/astuce55/XickCloud.git)
cd XickCloud

```


2. **Installer les dépendances Python**
Créez un environnement virtuel (recommandé) :
```bash
python3 -m venv venv
source venv/bin/activate
pip install flask libvirt-python requests paramiko

```


3. **Préparer les répertoires de stockage**
Le projet utilise par défaut `/var/lib/libvirt/images`. Assurez-vous que les dossiers existent et sont accessibles :
```bash
# Création des dossiers pour les images de base
sudo mkdir -p /var/lib/libvirt/images/base-images

# Téléchargement d'une image Cloud (Ex: Ubuntu 22.04)
cd /var/lib/libvirt/images/base-images
sudo wget [https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img](https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img)
sudo mv jammy-server-cloudimg-amd64.img ubuntu22.qcow2

```


*Note : Le nom de l'image doit correspondre à ce qui est défini dans `config.py` (variable `OS_IMAGES`).*

---

## ▶️ Démarrage

Lancez l'application Flask (avec `sudo` si nécessaire pour accéder aux sockets libvirt système, sinon assurez-vous que votre utilisateur a les droits) :

```bash
# Activer l'environnement virtuel si ce n'est pas fait
source venv/bin/activate

# Lancer l'app
python3 app.py

```

Accédez à l'interface via : **`http://localhost:5000`**

### 🔐 Identifiants par défaut

Le système est initialisé avec les utilisateurs suivants (définis dans `models/user.py`) :

| Rôle | Identifiant | Mot de passe |
| --- | --- | --- |
| **Admin** | `admin` | `admin123` |
| **Utilisateur** | `user1` | `user123` |
| **Utilisateur** | `user2` | `user123` |

---

## 📂 Structure du Projet

```
.
├── app.py                      # Point d'entrée de l'application Flask
├── config.py                   # Configuration (chemins, prix, images)
├── config_logging.py           # Configuration des logs rotatifs
├── requirements.txt            # Liste des dépendances
├── generated/                  # Fichiers générés (cloud-init ISOs, compose files)
├── data/                       # Base de données JSON (utilisateurs, VMs, clusters)
├── keys/                       # Clés SSH générées pour les VMs
├── routes/                     # Contrôleurs (Blueprints Flask)
│   ├── auth.py                 # Authentification
│   ├── iaas.py                 # Routes gestion VMs
│   ├── swarm.py                # Routes gestion Clusters
│   ├── paas.py                 # Routes Catalogue Apps
│   └── admin.py                # Routes Administration
├── models/                     # Modèles de données (Persistance JSON)
│   ├── host.py                 # Gestion hôtes KVM
│   ├── user.py                 # Gestion utilisateurs
│   ├── vm.py                   # Logique métier VMs
│   ├── swarm.py                # Logique métier Clusters
│   └── storage.py              # I/O Fichiers JSON
└── services/                   # Services métier
    ├── libvirt_service.py      # Wrapper API Libvirt (connexion, IP lease)
    ├── network_service.py      # Gestion réseaux virtuels & XML
    ├── deployment_service.py   # Génération Cloud-init & Provisioning
    ├── swarm_deployment_service.py # Commandes SSH pour Docker Swarm
    └── docker_compose_generator.py # Générateur de stacks applicatives

```

---

## 📖 Guide d'Utilisation

### 1. Création d'une VM (IaaS)

1. Connectez-vous en tant que `user1`.
2. Allez dans le dashboard **IaaS**.
3. Cliquez sur **"Nouvelle Instance"**.
4. Choisissez un nom, un OS (Ubuntu) et un gabarit (Small/Medium).
5. Validez. Le système va :
* Cloner l'image de base.
* Générer une ISO cloud-init (avec votre clé SSH et configuration Docker).
* Démarrer la VM.
* Attendre l'attribution d'une IP DHCP.



### 2. Création d'un Cluster Swarm

1. Une fois que vous avez au moins 2 VMs "Running".
2. Allez dans l'onglet **Swarm**.
3. Cliquez sur **"Créer un Cluster"**.
4. Sélectionnez les VMs à inclure (au moins 1 Manager).
5. Le système va configurer le nœud Manager et joindre les Workers automatiquement via SSH.

### 3. Déploiement d'Application (PaaS)

1. Une fois le cluster actif (Statut: Ready).
2. Allez dans l'onglet **PaaS (Catalogue)**.
3. Choisissez une application (ex: **OwnCloud**).
4. Cliquez sur **Déployer**.
5. L'application sera accessible via l'IP du Manager sur le port indiqué.

---

## ⚠️ Dépannage Courant

* **Erreur "Permission Denied" sur `/var/lib/libvirt/images`** :
Vérifiez que l'utilisateur exécutant Flask a les droits d'écriture dans ce dossier, ou lancez avec `sudo`.
* **IP non trouvée (Status: Deploying infini)** :
Assurez-vous que le service `qemu-guest-agent` est bien installé dans l'image de base, ou que le réseau virtuel KVM attribue bien les baux DHCP.
* **Erreur SSH lors de l'init Swarm** :
Les VMs peuvent mettre du temps à démarrer le service SSH lors du premier boot (génération des clés host). Attendez 1 à 2 minutes après le démarrage de la VM avant de lancer le cluster.

---

## 👥 Auteurs

Projet réalisé dans le cadre de l'UE **INF4107 - Virtualisation et Cloud Computing**.

* WABO POKAM RICK JUNIOR
* WATO MABOU PAUL
