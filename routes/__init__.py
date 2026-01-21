# routes/__init__.py
from .auth import auth_bp
from .iaas import iaas_bp
from .swarm import swarm_bp
from .admin import admin_bp
from .paas import paas_bp

__all__ = ['auth_bp', 'iaas_bp', 'swarm_bp', 'admin_bp', 'paas_bp']