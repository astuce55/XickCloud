# models/user.py
import hashlib
from typing import Dict, Optional
from models.storage import StorageManager

class UserManager:
    def __init__(self):
        self.storage = StorageManager()
    
    @staticmethod
    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()
    
    def authenticate(self, username: str, password: str) -> bool:
        """Authentifie un utilisateur"""
        users = self.storage.load_users()
        if username in users:
            stored_hash = users[username]['password']
            return stored_hash == self.hash_password(password)
        return False
    
    def get_user(self, username: str) -> Optional[Dict]:
        """Récupère les informations d'un utilisateur"""
        users = self.storage.load_users()
        return users.get(username)
    
    def get_user_role(self, username: str) -> str:
        """Récupère le rôle d'un utilisateur"""
        user = self.get_user(username)
        return user.get('role', 'user') if user else 'user'
    
    def get_user_quota(self, username: str) -> Dict:
        """Récupère les quotas d'un utilisateur"""
        user = self.get_user(username)
        if user and 'quota' in user:
            return user['quota']
        return {'vcpu': 8, 'ram': 16384, 'disk': 200}
    
    def init_default_users(self):
        """Initialise les utilisateurs par défaut"""
        users = self.storage.load_users()
        if not users:
            users = {
                'admin': {
                    'password': self.hash_password('admin123'),
                    'role': 'admin',
                    'quota': {'vcpu': 100, 'ram': 102400, 'disk': 1000}
                },
                'user1': {
                    'password': self.hash_password('user123'),
                    'role': 'user',
                    'quota': {'vcpu': 8, 'ram': 16384, 'disk': 200}
                },
                'user2': {
                    'password': self.hash_password('user123'),
                    'role': 'user',
                    'quota': {'vcpu': 8, 'ram': 16384, 'disk': 200}
                }
            }
            self.storage.save_users(users)