# config.py
import os
import json
from datetime import datetime

# Chemins de base
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

# Chemins des fichiers de données
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

METADATA_FILE = os.path.join(DATA_DIR, 'vm_metadata.json')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
HOSTS_FILE = os.path.join(DATA_DIR, 'kvm_hosts.json')
SWARM_CLUSTERS_FILE = os.path.join(DATA_DIR, 'swarm_clusters.json')
APPS_FILE = os.path.join(DATA_DIR, 'deployed_apps.json')
BILLING_FILE = os.path.join(DATA_DIR, 'billing.json')

# Répertoires de travail
GEN_DIR = os.path.join(BASE_DIR, 'generated')
KEYS_DIR = os.path.join(BASE_DIR, 'keys')
BASE_IMG_DIR = "/var/lib/libvirt/images/base-images"
VM_STORAGE_DIR = "/var/lib/libvirt/images"

os.makedirs(GEN_DIR, exist_ok=True)
os.makedirs(KEYS_DIR, exist_ok=True)

# Configuration Flask
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
DEBUG = os.environ.get('DEBUG', 'True').lower() == 'true'

# Flavors
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
    },
    'swarm': {
        'name': 'Docker Swarm Node',
        'vcpu': 1,
        'ram': 2048,
        'disk': 15,
        'price': 3000
    }
}

# Images OS disponibles
OS_IMAGES = {
    'ubuntu': os.path.join(BASE_IMG_DIR, "base-ubuntu.qcow2"),
    'debian': os.path.join(BASE_IMG_DIR, "base-debian.qcow2")
}

# Catalogue d'applications PaaS
PaaS_CATALOG = {
    'wordpress': {
        'name': 'WordPress',
        'description': 'CMS de blogging',
        'stack': 'wordpress',
        'port': 80,
        'db_type': 'mysql',
        'icon': 'fab fa-wordpress',
        'color': '#21759b',
        'category': 'cms'
    },
    'onlyoffice': {
        'name': 'OnlyOffice',
        'description': 'Suite bureautique collaborative',
        'stack': 'onlyoffice',
        'port': 80,
        'db_type': 'postgresql',
        'icon': 'fas fa-file-alt',
        'color': '#44aaee',
        'category': 'collaboration'
    },
    'odoo': {
        'name': 'Odoo',
        'description': 'ERP open source',
        'stack': 'odoo',
        'port': 8069,
        'db_type': 'postgresql',
        'icon': 'fas fa-cogs',
        'color': '#714b67',
        'category': 'business'
    },
    'openldap': {
        'name': 'OpenLDAP',
        'description': 'Annuaire LDAP',
        'stack': 'openldap',
        'port': 389,
        'db_type': 'none',
        'icon': 'fas fa-address-book',
        'color': '#3e7e9a',
        'category': 'development'
    },
    'mattermost': {
        'name': 'Mattermost',
        'description': 'Messagerie d\'équipe',
        'stack': 'mattermost',
        'port': 8065,
        'db_type': 'mysql',
        'icon': 'fas fa-comments',
        'color': '#0058cc',
        'category': 'collaboration'
    },
    'moodle': {
        'name': 'Moodle',
        'description': 'Plateforme d\'apprentissage',
        'stack': 'moodle',
        'port': 80,
        'db_type': 'mysql',
        'icon': 'fas fa-graduation-cap',
        'color': '#f98012',
        'category': 'cms'
    },
    'owncloud': {
        'name': 'OwnCloud',
        'description': 'Cloud privé',
        'stack': 'owncloud',
        'port': 80,
        'db_type': 'mysql',
        'icon': 'fas fa-cloud',
        'color': '#041e42',
        'category': 'storage'
    },
    'prestashop': {
        'name': 'PrestaShop',
        'description': 'Plateforme e-commerce',
        'stack': 'prestashop',
        'port': 80,
        'db_type': 'mysql',
        'icon': 'fas fa-shopping-cart',
        'color': '#df0067',
        'category': 'business'
    }
}

# Prix de facturation (par heure)
BILLING_RATES = {
    'cpu': 10,      # FCFA par vCPU/heure
    'ram': 5,       # FCFA par GB RAM/heure
    'disk': 2,      # FCFA par GB disque/heure
    'swarm_node': 20,  # FCFA par nœud Swarm/heure
    'app_deployment': 50  # FCFA par déploiement d'app
}

# Configuration par défaut des hôtes KVM - MODIFIER ICI POUR KVM LOCAL PAR DÉFAUT
DEFAULT_HOSTS = [
    {
        'id': 'local',
        'name': 'KVM Local',
        'uri': 'qemu:///system',
        'enabled': True,
        'priority': 1,  # Priorité 1 = utilisé en premier
        'storage_path': '/var/lib/libvirt/images',
        'quotas': {
            'max_vcpu': 8,
            'max_ram': 16384,
            'max_disk': 200
        },
        'description': 'Serveur KVM local (par défaut)'
    }
]

TIMEOUTS = {
    'ssh_connect': 3,
    'libvirt_connect': 5,
    'host_monitor': 10,
    'vm_operation': 30,
    'api_request': 60
}

# Configuration des retries
RETRY_CONFIG = {
    'max_retries': 2,
    'retry_delay': 1,
    'backoff_factor': 1.5
}

# Hôtes avec leurs timeouts spécifiques
HOST_TIMEOUTS = {
    'local': {
        'connect': 2,
        'monitor': 5
    },
    'remote': {
        'connect': 5,
        'monitor': 15
    }
}