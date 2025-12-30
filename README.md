☁️ NEXUS CLOUD - Orchestrateur IaaS

Un mini-cloud privé complet permettant de déployer, gérer et monitorer des instances virtuelles (Ubuntu/Debian) en quelques secondes.

✨ Points Forts

🚀 Provisioning Turbo : Déploiement en ~30 secondes (Optimisation Cloud-init & Netplan).

🔒 Sécurité Avancée : Gestion automatique des clés SSH et expiration forcée des mots de passe.

📊 Monitoring Réel : Tableau de bord temps réel (CPU Différentiel, RAM RSS).

🎨 Interface Moderne : Design Glassmorphism, entièrement responsive.

🔌 Mode Offline : Toutes les librairies (Bootstrap, Chart.js) sont incluses. Aucune connexion internet requise pour l'interface.

🛠️ Installation

Ce projet nécessite une machine Linux (Ubuntu/Debian) avec l'hyperviseur KVM.

1. Cloner le dépôt

git clone [https://github.com/schawil/nexus-cloud.git](https://github.com/schawil/nexus-cloud.git)
cd nexus-cloud


2. Lancer l'installation automatique

Ce script installe KVM, configure le réseau et télécharge les images Cloud officielles (Ubuntu & Debian).

chmod +x setup.sh  
sudo ./setup.sh


Note : Une fois l'installation terminée, il est conseillé de redémarrer votre session pour appliquer les droits de groupe.

3. Démarrer le serveur

sudo python3 app.py


L'application est accessible localement sur : http://localhost:5000

📱 Accès Distant & Démonstration

Pour présenter le projet au jury ou accéder à l'interface depuis un autre appareil (Smartphone, Laptop), suivez cette procédure :

Prérequis Réseau : Connectez votre PC serveur et l'appareil du jury sur le même réseau Wi-Fi (ou via un partage de connexion).

Récupérer l'IP Locale :
Ouvrez un terminal et identifiez votre adresse IPv4 (ex: 192.168.x.x) :

hostname -I


Lancer le Serveur (Si ce n'est pas déjà fait) :

sudo python3 app.py


Connexion Client :
Sur l'appareil distant, ouvrez le navigateur et tapez :
http://<VOTRE_IP_LOCALE>:5000

Showtime ! 🚀
L'interface est entièrement responsive. Une VM créée depuis le téléphone apparaîtra instantanément sur le serveur.

🔑 Guide de Connexion SSH

NEXUS Cloud génère les clés SSH côté serveur pour garantir la sécurité.

Lors de la création d'une VM, choisissez "Générer une clé".

Votre navigateur va télécharger un fichier (ex: ma-cle-projet).

Ce fichier se trouve dans votre dossier Téléchargements (~/Downloads).

Pour vous connecter :

Ouvrez un terminal et tapez :

1. Sécuriser la clé (Obligatoire)

SSH refusera la clé si les permissions sont trop ouvertes.

chmod 600 ~/Downloads/ma-cle-projet


2. Connexion

ssh -i ~/Downloads/ma-cle-projet admin@ADRESSE_IP


L'adresse IP est affichée sur le Dashboard une fois la VM démarrée.
Remplacez admin par le nom d'utilisateur que vous avez défini.

Composant

Technologie

Description

Backend

Python Flask

API REST et bindings libvirt-python

Hyperviseur

KVM / QEMU

Virtualisation matérielle, disques qcow2 (Backing Files)

Frontend

HTML5 / JS

Bootstrap 5 & Chart.js (Mode Local)

Orchestration

Cloud-init

Injection dynamique User Data & Meta Data via ISO

👤 Auteur

@schawil - Initial work & Maintainer