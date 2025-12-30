# ☁️ NEXUS CLOUD - Orchestrateur IaaS

Un mini-cloud privé complet permettant de déployer, gérer et monitorer des instances virtuelles (Ubuntu/Debian) en quelques secondes.

---

## ✨ Points Forts

* 🚀 **Provisioning Turbo** : Déploiement en ~30 secondes (Optimisation Cloud-init & Netplan).
* 🔒 **Sécurité Avancée** : Gestion automatique des clés SSH et expiration forcée des mots de passe.
* 📊 **Monitoring Réel** : Tableau de bord temps réel (CPU Différentiel, RAM RSS).
* 🎨 **Interface Moderne** : Design Glassmorphism, entièrement responsive.
* 🔌 **Mode Offline** : Toutes les librairies (Bootstrap, Chart.js) sont incluses. Aucune connexion internet requise pour l'interface.

---

## 🛠️ Installation

Ce projet nécessite une machine Linux (Ubuntu/Debian) avec l'hyperviseur KVM.

### 1. Cloner le dépôt

```bash
git clone https://github.com/schawil/nexus-cloud.git
cd nexus-cloud
```

### 2. Lancer l'installation automatique

Ce script installe KVM, configure le réseau et télécharge les images Cloud officielles (Ubuntu & Debian).

```bash
chmod +x setup.sh  
sudo ./setup.sh
```

> **Note** : Une fois l'installation terminée, il est conseillé de redémarrer votre session pour appliquer les droits de groupe.

### 3. Démarrer le serveur

```bash
sudo python3 app.py
```

L'application est accessible localement sur : **`http://localhost:5000`**

---

## 📱 Accès Distant & Démonstration

Pour présenter le projet au jury ou accéder à l'interface depuis un autre appareil (Smartphone, Laptop), suivez cette procédure :

### 1. Connecte ton PC au réseau de la salle

Wifi ou Câble.

### 2. Trouve ton IP locale

Ouvrez un terminal et identifiez votre adresse IPv4 (ex: `192.168.x.x`) :

```bash
hostname -I
```

> Note l'adresse qui ressemble à `192.168.x.x` ou `10.x.x.x`.

### 3. Lance le serveur

```bash
sudo python3 app.py
```

### 4. Invite le jury à se connecter depuis leur propre PC

Sur l'appareil distant, ouvrez le navigateur et tapez : **`http://<TON_IP>:5000`**

### 5. Fais le show ! 🚀

Ils cliquent sur leur écran, et la VM apparaît sur le tien (et dans leur liste). C'est simple, efficace, et ça marche à tous les coups.

---

## 🔑 Guide de Connexion SSH

NEXUS Cloud génère les clés SSH côté serveur pour garantir la sécurité.

1. Lors de la création d'une VM, choisissez **"Générer une clé"**.
2. Votre navigateur va télécharger un fichier (ex: `ma-cle-projet`).
3. Ce fichier se trouve dans votre dossier **Téléchargements** (`~/Downloads`).

### Pour vous connecter :

Ouvrez un terminal et tapez :

#### 1. Sécuriser la clé (Obligatoire)

SSH refusera la clé si les permissions sont trop ouvertes.

```bash
chmod 600 ~/Downloads/ma-cle-projet
```

#### 2. Connexion

```bash
ssh -i ~/Downloads/ma-cle-projet admin@ADRESSE_IP
```

> L'adresse IP est affichée sur le Dashboard une fois la VM démarrée. Remplacez `admin` par le nom d'utilisateur que vous avez défini.

---

## 🏗️ Architecture Technique

| Composant         | Technologie        | Description                                                    |
|------------------ |--------------------|----------------------------------------------------------------|
| **Backend**       | Python Flask       | API REST et bindings `libvirt-python`                          |
| **Hyperviseur**   | KVM / QEMU         | Virtualisation matérielle, disques `qcow2` (Backing Files)     |
| **Frontend**      | HTML5 / JS         | Bootstrap 5 & Chart.js (Mode Local)                            |
| **Orchestration** | Cloud-init         | Injection dynamique User Data & Meta Data via ISO              |

---

## 👤 Auteur

* **@schawil** - Initial work & Maintainer

---

## 📄 Licence

Ce projet est sous licence libre. N'hésitez pas à contribuer !

---

## 🙏 Remerciements

Merci à la communauté open-source pour les outils formidables (KVM, Cloud-init, Flask) qui rendent ce projet possible.