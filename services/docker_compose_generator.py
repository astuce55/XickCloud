# services/docker_compose_generator.py
import os
from config import GEN_DIR, PaaS_CATALOG

class DockerComposeGenerator:
    """Génère des fichiers docker-compose.yml pour les applications PaaS"""
    
    def __init__(self):
        os.makedirs(GEN_DIR, exist_ok=True)
    
    def generate_compose(self, app_id: str, stack_name: str, db_password: str) -> str:
        """
        Génère un fichier docker-compose.yml pour une application
        
        CORRECTIONS APPORTÉES:
        1. Ajout d'un réseau overlay pour Docker Swarm
        2. Configuration correcte des services de BD avec volumes nommés
        3. Variables d'environnement DB correctement passées aux applications
        4. Health checks pour s'assurer que la BD démarre avant l'app
        """
        
        if app_id not in PaaS_CATALOG:
            return None
        
        app_info = PaaS_CATALOG[app_id]
        db_type = app_info.get('db_type', 'none')
        
        compose_file = os.path.join(GEN_DIR, f"{stack_name}-compose.yml")
        
        # Nom du réseau overlay (attachable permet l'accès depuis l'extérieur)
        network_name = f"{stack_name}_network"
        
        # Nom du service de base de données
        db_service_name = f"{stack_name}_db" if db_type != 'none' else None
        
        compose_content = self._generate_compose_content(
            app_id=app_id,
            stack_name=stack_name,
            db_password=db_password,
            db_type=db_type,
            network_name=network_name,
            db_service_name=db_service_name
        )
        
        with open(compose_file, 'w') as f:
            f.write(compose_content)
        
        return compose_file
    
    def _generate_compose_content(self, app_id: str, stack_name: str, db_password: str, 
                                   db_type: str, network_name: str, db_service_name: str) -> str:
        """Génère le contenu du docker-compose selon le type d'application"""
        
        # En-tête commun
        compose = f"""version: '3.8'

services:
"""
        
        # Ajouter le service de base de données si nécessaire
        if db_type == 'mysql':
            compose += self._generate_mysql_service(stack_name, db_password, network_name)
        elif db_type == 'postgresql':
            compose += self._generate_postgresql_service(stack_name, db_password, network_name)
        
        # Ajouter le service de l'application
        compose += self._generate_app_service(app_id, stack_name, db_password, db_type, 
                                              network_name, db_service_name)
        
        # Ajouter la définition des volumes
        if db_type != 'none':
            compose += f"""
volumes:
  {stack_name}_db_data:
    driver: local
"""
        
        # Ajouter la définition du réseau overlay
        compose += f"""
networks:
  {network_name}:
    driver: overlay
    attachable: true
"""
        
        return compose
    
    def _generate_mysql_service(self, stack_name: str, db_password: str, network_name: str) -> str:
        """Génère le service MySQL avec configuration correcte"""
        return f"""  {stack_name}_db:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: {db_password}
      MYSQL_DATABASE: {stack_name}_db
      MYSQL_USER: {stack_name}_user
      MYSQL_PASSWORD: {db_password}
    volumes:
      - {stack_name}_db_data:/var/lib/mysql
    networks:
      - {network_name}
    deploy:
      placement:
        constraints:
          - node.role == manager
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-p{db_password}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

"""
    
    def _generate_postgresql_service(self, stack_name: str, db_password: str, network_name: str) -> str:
        """Génère le service PostgreSQL avec configuration correcte"""
        return f"""  {stack_name}_db:
    image: postgres:15
    environment:
      POSTGRES_DB: {stack_name}_db
      POSTGRES_USER: {stack_name}_user
      POSTGRES_PASSWORD: {db_password}
    volumes:
      - {stack_name}_db_data:/var/lib/postgresql/data
    networks:
      - {network_name}
    deploy:
      placement:
        constraints:
          - node.role == manager
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U {stack_name}_user"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

"""
    
    def _generate_app_service(self, app_id: str, stack_name: str, db_password: str, 
                              db_type: str, network_name: str, db_service_name: str) -> str:
        """Génère le service de l'application avec dépendances correctes"""
        
        app_info = PaaS_CATALOG[app_id]
        port = app_info.get('port', 80)
        
        # Configuration de base
        service = f"""  {stack_name}_app:
"""
        
        # Image selon l'application
        service += self._get_app_image(app_id)
        
        # Variables d'environnement avec connexion DB
        if db_type != 'none':
            service += self._get_app_environment(app_id, stack_name, db_password, db_type, db_service_name)
        else:
            service += "    environment:\n"
            service += f"      - APP_NAME={stack_name}\n"
        
        # Port exposé
        service += f"""    ports:
      - "{port}:{port}"
"""
        
        # Réseau
        service += f"""    networks:
      - {network_name}
"""
        
        # Dépendances et déploiement
        if db_type != 'none':
            service += f"""    depends_on:
      - {stack_name}_db
"""
        
        service += f"""    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
        delay: 10s
        max_attempts: 3
"""
        
        return service
    
    def _get_app_image(self, app_id: str) -> str:
        """Retourne l'image Docker appropriée pour l'application"""
        
        images = {
            'wordpress': '    image: wordpress:latest\n',
            'onlyoffice': '    image: onlyoffice/documentserver:latest\n',
            'odoo': '    image: odoo:17.0\n',
            'openldap': '    image: osixia/openldap:latest\n',
            'mattermost': '    image: mattermost/mattermost-team-edition:latest\n',
            'moodle': '    image: bitnami/moodle:latest\n',
            'owncloud': '    image: owncloud/server:latest\n',
            'prestashop': '    image: prestashop/prestashop:latest\n'
        }
        
        return images.get(app_id, '    image: nginx:latest\n')
    
    def _get_app_environment(self, app_id: str, stack_name: str, db_password: str, 
                            db_type: str, db_service_name: str) -> str:
        """Génère les variables d'environnement selon l'application et le type de BD"""
        
        env = "    environment:\n"
        
        # Configuration commune selon le type de BD
        if db_type == 'mysql':
            db_host = db_service_name
            db_name = f"{stack_name}_db"
            db_user = f"{stack_name}_user"
            
            if app_id == 'wordpress':
                env += f"""      - WORDPRESS_DB_HOST={db_host}
      - WORDPRESS_DB_NAME={db_name}
      - WORDPRESS_DB_USER={db_user}
      - WORDPRESS_DB_PASSWORD={db_password}
"""
            elif app_id == 'mattermost':
                env += f"""      - MM_SQLSETTINGS_DRIVERNAME=mysql
      - MM_SQLSETTINGS_DATASOURCE={db_user}:{db_password}@tcp({db_host}:3306)/{db_name}?charset=utf8mb4,utf8&readTimeout=30s&writeTimeout=30s
      - MM_SERVICESETTINGS_SITEURL=http://localhost:8065
"""
            elif app_id == 'moodle':
                env += f"""      - MOODLE_DATABASE_TYPE=mysqli
      - MOODLE_DATABASE_HOST={db_host}
      - MOODLE_DATABASE_NAME={db_name}
      - MOODLE_DATABASE_USER={db_user}
      - MOODLE_DATABASE_PASSWORD={db_password}
"""
            elif app_id == 'owncloud':
                env += f"""      - OWNCLOUD_DB_TYPE=mysql
      - OWNCLOUD_DB_HOST={db_host}
      - OWNCLOUD_DB_NAME={db_name}
      - OWNCLOUD_DB_USERNAME={db_user}
      - OWNCLOUD_DB_PASSWORD={db_password}
      - OWNCLOUD_ADMIN_USERNAME=admin
      - OWNCLOUD_ADMIN_PASSWORD={db_password}
"""
            elif app_id == 'prestashop':
                env += f"""      - DB_SERVER={db_host}
      - DB_NAME={db_name}
      - DB_USER={db_user}
      - DB_PASSWD={db_password}
"""
        
        elif db_type == 'postgresql':
            db_host = db_service_name
            db_name = f"{stack_name}_db"
            db_user = f"{stack_name}_user"
            
            if app_id == 'odoo':
                env += f"""      - HOST={db_host}
      - USER={db_user}
      - PASSWORD={db_password}
      - DB_NAME={db_name}
"""
            elif app_id == 'onlyoffice':
                env += f"""      - DB_TYPE=postgres
      - DB_HOST={db_host}
      - DB_NAME={db_name}
      - DB_USER={db_user}
      - DB_PWD={db_password}
"""
        
        return env
    
    def get_compose_templates(self) -> dict:
        """Retourne la liste des templates disponibles"""
        return {
            app_id: {
                'name': info['name'],
                'db_type': info.get('db_type', 'none'),
                'port': info.get('port', 80)
            }
            for app_id, info in PaaS_CATALOG.items()
        }