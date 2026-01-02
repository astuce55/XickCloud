 # ☁️ XICK CLOUD - Orchestrateur IaaS Premium

XICK Cloud est un orchestrateur de datacenter privé permettant de déployer, gérer et monitorer des instances virtuelles (Ubuntu/Debian) avec une expérience utilisateur fluide et moderne.
# ✨ Points Forts

    🚀 Provisioning Ultra-Rapide : Déploiement d'instances prêtes à l'emploi en ~30 secondes grâce à l'optimisation Cloud-init & disques COW (Copy-On-Write).

    🔒 Sécurité Native : Gestion granulaire des clés SSH, injection de configurations réseau via Netplan et isolation par hyperviseur.

    📊 Monitoring Temps Réel : Dashboard dynamique affichant la charge CPU réelle (calcul différentiel) et l'utilisation RAM RSS précise.

    🎨 Interface Next-Gen : Design "Dark Mode" haute fidélité, responsive et conçu pour la clarté opérationnelle.

    🔌 Zéro Dépendance Web : Entièrement autonome. Toutes les librairies (Bootstrap, FontAwesome, Chart.js) sont embarquées localement pour fonctionner en réseau isolé.

# 🛠️ Pré-requis & Installation

Ce projet nécessite une machine Linux (Ubuntu/Debian conseillé) avec le support de la virtualisation matérielle (VT-x/AMD-V).
1. Clonage du projet
Bash

git clone https://github.com/astuce55/XickCloud.git
cd xick-cloud

2. Configuration automatique du système

Le script de setup configure l'environnement KVM, crée les ponts réseaux et prépare les images de base (Gold Images).
Bash

chmod +x setup.sh  
sudo ./setup.sh

    Important : Redémarrez votre session utilisateur après le script pour valider l'appartenance au groupe libvirt.

3. Lancement de l'orchestrateur
Bash

sudo python3 app.py

Accès à l'interface : http://localhost:5000
# 📱 Démonstration & Présentation 

XICK Cloud est conçu pour être présenté facilement sur un réseau local.

    Connectez le PC serveur au réseau local (Wifi ou Ethernet).

    Récupérez l'IP du serveur avec la commande hostname -I.

    Connectez-vous depuis n'importe quel autre appareil (tablette, laptop) via : http://<IP_SERVEUR>:5000.

# 🏗️ Architecture Technique
Composant	Technologie	Rôle
Core Engine	Python Flask	Gestion des routes API et pilotage de la libvirt.
Virtualisation	KVM / QEMU	Virtualisation de type 1 pour des performances natives.
Storage	QCOW2	Gestion intelligente du stockage (Snapshots & Backing files).
Monitoring	Libvirt-python	Collecte des métriques CPU (Nanosecondes) et RAM (RSS).
Frontend	HTML5 / CSS / JS	Interface moderne sans dépendances externes (Full local).
# 🔑 Accès aux Instances

Toutes les instances sont créées avec l'utilisateur défini lors du déploiement.

Exemple de connexion avec clé SSH générée :

    Téléchargez la clé depuis l'interface après création.

    Appliquez les permissions de sécurité : chmod 600 la-cle.pem

    Connectez-vous : ssh -i la-cle.pem utilisateur@ip_de_la_vm

# 👤 Auteur

    @Xponentiel- Lead Developer & Architecte Cloud

# 📄 Licence

Projet distribué sous licence MIT. Libre pour toute modification ou contribution.
# Une question ?

N'hésite pas à me solliciter pour ajouter une section spécifique ou détailler un point technique particulier !
