# models/user.py
import hashlib
from typing import Dict, Optional
from models.storage import StorageManager

class UserManager:
    """Gestionnaire des utilisateurs"""
    
    def __init__(self):
        self.storage = StorageManager()
        self.users = self.storage.load_users()
    
    def hash_password(self, password: str) -> str:
        """Hash un mot de passe avec SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def init_default_users(self):
        """Initialise les utilisateurs par défaut"""
        default_users = {
            'admin': {
                'password': self.hash_password('admin123'),
                'role': 'admin',
                'email': 'admin@xickcloud.local'
            },
            'user1': {
                'password': self.hash_password('user123'),
                'role': 'user',
                'email': 'user1@xickcloud.local'
            },
            'user2': {
                'password': self.hash_password('user123'),
                'role': 'user',
                'email': 'user2@xickcloud.local'
            }
        }
        
        # Créer uniquement les utilisateurs qui n'existent pas
        updated = False
        for username, user_data in default_users.items():
            if username not in self.users:
                self.users[username] = user_data
                updated = True
        
        if updated:
            self.storage.save_users(self.users)
    
    def authenticate(self, username: str, password: str) -> bool:
        """Authentifie un utilisateur"""
        user = self.users.get(username)
        if not user:
            return False
        
        password_hash = self.hash_password(password)
        return user.get('password') == password_hash
    
    def get_user_role(self, username: str) -> Optional[str]:
        """Récupère le rôle d'un utilisateur"""
        user = self.users.get(username)
        return user.get('role') if user else None
    
    def create_user(self, username: str, password: str, role: str = 'user', email: str = '') -> bool:
        """Crée un nouvel utilisateur"""
        if username in self.users:
            return False
        
        self.users[username] = {
            'password': self.hash_password(password),
            'role': role,
            'email': email
        }
        
        self.storage.save_users(self.users)
        return True
    
    def delete_user(self, username: str) -> bool:
        """Supprime un utilisateur"""
        if username in self.users and username != 'admin':
            del self.users[username]
            self.storage.save_users(self.users)
            return True
        return False
    
    def update_password(self, username: str, new_password: str) -> bool:
        """Met à jour le mot de passe d'un utilisateur"""
        if username in self.users:
            self.users[username]['password'] = self.hash_password(new_password)
            self.storage.save_users(self.users)
            return True
        return False
    
    def get_all_users(self) -> Dict:
        """Récupère tous les utilisateurs (sans les mots de passe)"""
        users_safe = {}
        for username, user_data in self.users.items():
            users_safe[username] = {
                'role': user_data.get('role', 'user'),
                'email': user_data.get('email', '')
            }
        return users_safe