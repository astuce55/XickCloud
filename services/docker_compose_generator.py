# services/docker_compose_generator.py - NOUVEAU FICHIER
import os
from typing import Dict, Optional
from config import GEN_DIR, PaaS_CATALOG
from config_logging import deployment_logger as logger

class DockerComposeGenerator:
    """Génère des fichiers docker-compose.yml pour les applications PaaS"""
    
    def __init__(self):
        self.compose_dir = os.path.join(GEN_DIR, 'compose')
        os.makedirs(self.compose_dir, exist_ok=True)
    
    def generate_wordpress(self, app_name: str, db_password: str = "wordpress_pass") -> str:
        """Génère docker-compose pour WordPress"""
        
        compose_content = f"""version: '3.8'

services:
  db:
    image: mysql:8.0
    volumes:
      - db_data:/var/lib/mysql
    environment:
      MYSQL_ROOT_PASSWORD: {db_password}
      MYSQL_DATABASE: wordpress
      MYSQL_USER: wordpress
      MYSQL_PASSWORD: {db_password}
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure

  wordpress:
    image: wordpress:latest
    ports:
      - "80:80"
    environment:
      WORDPRESS_DB_HOST: db:3306
      WORDPRESS_DB_USER: wordpress
      WORDPRESS_DB_PASSWORD: {db_password}
      WORDPRESS_DB_NAME: wordpress
    volumes:
      - wp_data:/var/www/html
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
    depends_on:
      - db

volumes:
  db_data:
  wp_data:

networks:
  app_network:
    driver: overlay
"""
        
        file_path = os.path.join(self.compose_dir, f"{app_name}.yml")
        with open(file_path, 'w') as f:
            f.write(compose_content)
        
        logger.info(f"Généré docker-compose pour WordPress: {file_path}")
        return file_path
    
    def generate_mattermost(self, app_name: str, db_password: str = "mattermost_pass") -> str:
        """Génère docker-compose pour Mattermost"""
        
        compose_content = f"""version: '3.8'

services:
  postgres:
    image: postgres:13-alpine
    environment:
      POSTGRES_USER: mmuser
      POSTGRES_PASSWORD: {db_password}
      POSTGRES_DB: mattermost
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure

  mattermost:
    image: mattermost/mattermost-team-edition:latest
    ports:
      - "8065:8065"
    environment:
      MM_SQLSETTINGS_DRIVERNAME: postgres
      MM_SQLSETTINGS_DATASOURCE: postgres://mmuser:{db_password}@postgres:5432/mattermost?sslmode=disable&connect_timeout=10
      MM_SERVICESETTINGS_SITEURL: http://localhost:8065
    volumes:
      - mattermost_config:/mattermost/config
      - mattermost_data:/mattermost/data
      - mattermost_logs:/mattermost/logs
      - mattermost_plugins:/mattermost/plugins
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
    depends_on:
      - postgres

volumes:
  postgres_data:
  mattermost_config:
  mattermost_data:
  mattermost_logs:
  mattermost_plugins:

networks:
  app_network:
    driver: overlay
"""
        
        file_path = os.path.join(self.compose_dir, f"{app_name}.yml")
        with open(file_path, 'w') as f:
            f.write(compose_content)
        
        logger.info(f"Généré docker-compose pour Mattermost: {file_path}")
        return file_path
    
    def generate_odoo(self, app_name: str, db_password: str = "odoo_pass") -> str:
        """Génère docker-compose pour Odoo"""
        
        compose_content = f"""version: '3.8'

services:
  postgres:
    image: postgres:13
    environment:
      POSTGRES_DB: postgres
      POSTGRES_PASSWORD: {db_password}
      POSTGRES_USER: odoo
    volumes:
      - odoo_db:/var/lib/postgresql/data
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure

  odoo:
    image: odoo:16.0
    ports:
      - "8069:8069"
    environment:
      HOST: postgres
      USER: odoo
      PASSWORD: {db_password}
    volumes:
      - odoo_data:/var/lib/odoo
      - odoo_addons:/mnt/extra-addons
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
    depends_on:
      - postgres

volumes:
  odoo_db:
  odoo_data:
  odoo_addons:

networks:
  app_network:
    driver: overlay
"""
        
        file_path = os.path.join(self.compose_dir, f"{app_name}.yml")
        with open(file_path, 'w') as f:
            f.write(compose_content)
        
        logger.info(f"Généré docker-compose pour Odoo: {file_path}")
        return file_path
    
    def generate_owncloud(self, app_name: str, db_password: str = "owncloud_pass") -> str:
        """Génère docker-compose pour OwnCloud"""
        
        compose_content = f"""version: '3.8'

services:
  mariadb:
    image: mariadb:10.11
    environment:
      MYSQL_ROOT_PASSWORD: {db_password}
      MYSQL_DATABASE: owncloud
      MYSQL_USER: owncloud
      MYSQL_PASSWORD: {db_password}
    volumes:
      - mysql_data:/var/lib/mysql
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure

  redis:
    image: redis:7-alpine
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure

  owncloud:
    image: owncloud/server:latest
    ports:
      - "80:8080"
    environment:
      OWNCLOUD_DOMAIN: localhost
      OWNCLOUD_DB_TYPE: mysql
      OWNCLOUD_DB_NAME: owncloud
      OWNCLOUD_DB_USERNAME: owncloud
      OWNCLOUD_DB_PASSWORD: {db_password}
      OWNCLOUD_DB_HOST: mariadb
      OWNCLOUD_REDIS_ENABLED: "true"
      OWNCLOUD_REDIS_HOST: redis
      OWNCLOUD_ADMIN_USERNAME: admin
      OWNCLOUD_ADMIN_PASSWORD: admin123
    volumes:
      - owncloud_data:/mnt/data
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
    depends_on:
      - mariadb
      - redis

volumes:
  mysql_data:
  owncloud_data:

networks:
  app_network:
    driver: overlay
"""
        
        file_path = os.path.join(self.compose_dir, f"{app_name}.yml")
        with open(file_path, 'w') as f:
            f.write(compose_content)
        
        logger.info(f"Généré docker-compose pour OwnCloud: {file_path}")
        return file_path
    
    def generate_moodle(self, app_name: str, db_password: str = "moodle_pass") -> str:
        """Génère docker-compose pour Moodle"""
        
        compose_content = f"""version: '3.8'

services:
  mariadb:
    image: mariadb:10.11
    environment:
      MYSQL_ROOT_PASSWORD: {db_password}
      MYSQL_DATABASE: moodle
      MYSQL_USER: moodle
      MYSQL_PASSWORD: {db_password}
    volumes:
      - mariadb_data:/var/lib/mysql
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure

  moodle:
    image: bitnami/moodle:latest
    ports:
      - "80:8080"
      - "443:8443"
    environment:
      MOODLE_DATABASE_HOST: mariadb
      MOODLE_DATABASE_PORT_NUMBER: 3306
      MOODLE_DATABASE_USER: moodle
      MOODLE_DATABASE_PASSWORD: {db_password}
      MOODLE_DATABASE_NAME: moodle
      MOODLE_USERNAME: admin
      MOODLE_PASSWORD: admin123
    volumes:
      - moodle_data:/bitnami/moodle
      - moodledata_data:/bitnami/moodledata
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
    depends_on:
      - mariadb

volumes:
  mariadb_data:
  moodle_data:
  moodledata_data:

networks:
  app_network:
    driver: overlay
"""
        
        file_path = os.path.join(self.compose_dir, f"{app_name}.yml")
        with open(file_path, 'w') as f:
            f.write(compose_content)
        
        logger.info(f"Généré docker-compose pour Moodle: {file_path}")
        return file_path
    
    def generate_prestashop(self, app_name: str, db_password: str = "prestashop_pass") -> str:
        """Génère docker-compose pour PrestaShop"""
        
        compose_content = f"""version: '3.8'

services:
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: {db_password}
      MYSQL_DATABASE: prestashop
      MYSQL_USER: prestashop
      MYSQL_PASSWORD: {db_password}
    volumes:
      - mysql_data:/var/lib/mysql
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure

  prestashop:
    image: prestashop/prestashop:latest
    ports:
      - "80:80"
    environment:
      DB_SERVER: mysql
      DB_NAME: prestashop
      DB_USER: prestashop
      DB_PASSWD: {db_password}
      PS_DOMAIN: localhost
      PS_INSTALL_AUTO: 1
    volumes:
      - prestashop_data:/var/www/html
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
    depends_on:
      - mysql

volumes:
  mysql_data:
  prestashop_data:

networks:
  app_network:
    driver: overlay
"""
        
        file_path = os.path.join(self.compose_dir, f"{app_name}.yml")
        with open(file_path, 'w') as f:
            f.write(compose_content)
        
        logger.info(f"Généré docker-compose pour PrestaShop: {file_path}")
        return file_path
    
    def generate_onlyoffice(self, app_name: str, db_password: str = "onlyoffice_pass") -> str:
        """Génère docker-compose pour OnlyOffice"""
        
        compose_content = f"""version: '3.8'

services:
  postgresql:
    image: postgres:13
    environment:
      POSTGRES_DB: onlyoffice
      POSTGRES_USER: onlyoffice
      POSTGRES_PASSWORD: {db_password}
    volumes:
      - postgresql_data:/var/lib/postgresql/data
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure

  rabbitmq:
    image: rabbitmq:3-management-alpine
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure

  onlyoffice:
    image: onlyoffice/documentserver:latest
    ports:
      - "80:80"
      - "443:443"
    environment:
      DB_TYPE: postgres
      DB_HOST: postgresql
      DB_PORT: 5432
      DB_NAME: onlyoffice
      DB_USER: onlyoffice
      DB_PWD: {db_password}
      AMQP_URI: amqp://guest:guest@rabbitmq
    volumes:
      - onlyoffice_data:/var/www/onlyoffice/Data
      - onlyoffice_logs:/var/log/onlyoffice
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
    depends_on:
      - postgresql
      - rabbitmq

volumes:
  postgresql_data:
  onlyoffice_data:
  onlyoffice_logs:

networks:
  app_network:
    driver: overlay
"""
        
        file_path = os.path.join(self.compose_dir, f"{app_name}.yml")
        with open(file_path, 'w') as f:
            f.write(compose_content)
        
        logger.info(f"Généré docker-compose pour OnlyOffice: {file_path}")
        return file_path
    
    def generate_openldap(self, app_name: str, admin_password: str = "admin_pass") -> str:
        """Génère docker-compose pour OpenLDAP"""
        
        compose_content = f"""version: '3.8'

services:
  openldap:
    image: osixia/openldap:latest
    ports:
      - "389:389"
      - "636:636"
    environment:
      LDAP_ORGANISATION: "XickCloud"
      LDAP_DOMAIN: "xickcloud.local"
      LDAP_ADMIN_PASSWORD: {admin_password}
    volumes:
      - ldap_data:/var/lib/ldap
      - ldap_config:/etc/ldap/slapd.d
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure

  phpldapadmin:
    image: osixia/phpldapadmin:latest
    ports:
      - "80:80"
    environment:
      PHPLDAPADMIN_LDAP_HOSTS: openldap
      PHPLDAPADMIN_HTTPS: "false"
    networks:
      - app_network
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
    depends_on:
      - openldap

volumes:
  ldap_data:
  ldap_config:

networks:
  app_network:
    driver: overlay
"""
        
        file_path = os.path.join(self.compose_dir, f"{app_name}.yml")
        with open(file_path, 'w') as f:
            f.write(compose_content)
        
        logger.info(f"Généré docker-compose pour OpenLDAP: {file_path}")
        return file_path
    
    def generate_compose(self, app_id: str, app_name: str, password: str = None) -> Optional[str]:
        """Génère le docker-compose approprié selon l'app_id"""
        
        if password is None:
            import secrets
            password = secrets.token_urlsafe(16)
        
        generators = {
            'wordpress': self.generate_wordpress,
            'mattermost': self.generate_mattermost,
            'odoo': self.generate_odoo,
            'owncloud': self.generate_owncloud,
            'moodle': self.generate_moodle,
            'prestashop': self.generate_prestashop,
            'onlyoffice': self.generate_onlyoffice,
            'openldap': self.generate_openldap
        }
        
        generator = generators.get(app_id)
        if generator:
            try:
                return generator(app_name, password)
            except Exception as e:
                logger.error(f"Erreur génération compose pour {app_id}: {e}", exc_info=True)
                return None
        else:
            logger.error(f"Pas de générateur pour l'application: {app_id}")
            return None