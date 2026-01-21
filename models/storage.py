# models/storage.py
import os
import json
from typing import Dict, List, Any
from config import USERS_FILE, HOSTS_FILE, APPS_FILE, BILLING_FILE, DEFAULT_HOSTS

class StorageManager:
    def __init__(self):
        pass
    
    # Gestion des utilisateurs
    @staticmethod
    def load_users() -> Dict:
        if os.path.exists(USERS_FILE):
            try:
                with open(USERS_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    @staticmethod
    def save_users(users: Dict):
        with open(USERS_FILE, 'w') as f:
            json.dump(users, f, indent=2)
    
    # Gestion des hôtes
    @staticmethod
    def load_hosts() -> List[Dict]:
        if os.path.exists(HOSTS_FILE):
            try:
                with open(HOSTS_FILE, 'r') as f:
                    return json.load(f)
            except:
                return DEFAULT_HOSTS.copy()
        return DEFAULT_HOSTS.copy()
    
    @staticmethod
    def save_hosts(hosts: List[Dict]):
        with open(HOSTS_FILE, 'w') as f:
            json.dump(hosts, f, indent=2)
    
    # Gestion des applications
    @staticmethod
    def load_apps() -> Dict:
        if os.path.exists(APPS_FILE):
            try:
                with open(APPS_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    @staticmethod
    def save_apps(apps: Dict):
        with open(APPS_FILE, 'w') as f:
            json.dump(apps, f, indent=2)
    
    # Gestion de la facturation
    @staticmethod
    def load_billing() -> Dict:
        if os.path.exists(BILLING_FILE):
            try:
                with open(BILLING_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    @staticmethod
    def save_billing(billing: Dict):
        with open(BILLING_FILE, 'w') as f:
            json.dump(billing, f, indent=2)