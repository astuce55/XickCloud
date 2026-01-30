# config_logging.py - Nouveau fichier à créer
import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Créer le dossier de logs
LOGS_DIR = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

# Configuration des niveaux de log
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

def setup_logger(name, log_file=None, level=None):
    """Configure un logger avec rotation de fichiers"""
    
    if level is None:
        level = getattr(logging, LOG_LEVEL)
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Éviter les doublons de handlers
    if logger.handlers:
        return logger
    
    # Format des logs
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Handler console (uniquement WARNING et plus)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Handler fichier avec rotation
    if log_file is None:
        log_file = f"{name}.log"
    
    file_path = os.path.join(LOGS_DIR, log_file)
    file_handler = RotatingFileHandler(
        file_path,
        maxBytes=10*1024*1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger

# Loggers par module
app_logger = setup_logger('app', 'xickcloud.log')
iaas_logger = setup_logger('iaas', 'iaas.log')
libvirt_logger = setup_logger('libvirt', 'libvirt.log')
host_logger = setup_logger('host', 'host.log')
swarm_logger = setup_logger('swarm', 'swarm.log')
paas_logger = setup_logger('paas', 'paas.log')
deployment_logger = setup_logger('deployment', 'deployment.log')

# Logger pour le debug (tout log)
debug_logger = setup_logger('debug', 'debug.log', logging.DEBUG)