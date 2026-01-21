# services/network_service.py
import libvirt
import hashlib
import sys
from typing import Optional
from services.libvirt_service import LibvirtService

class NetworkService:
    def __init__(self):
        pass
    
    @staticmethod
    def get_user_network_name(username: str) -> str:
        """Génère le nom du réseau pour un utilisateur"""
        return f"net_{username}"
    
    @staticmethod
    def get_swarm_network_name(username: str, cluster_name: str) -> str:
        """Génère le nom du réseau pour un cluster Swarm"""
        return f"swarm_{username}_{cluster_name}"
    
    @staticmethod
    def create_network(uri: str, network_name: str) -> bool:
        """Crée un réseau sur un hôte"""
        conn = LibvirtService.get_connection(uri)
        if not conn:
            return False
        
        try:
            # Vérifier si le réseau existe déjà
            try:
                net = conn.networkLookupByName(network_name)
                if net.isActive():
                    return True
                net.create()
                return True
            except libvirt.libvirtError:
                pass  # Le réseau n'existe pas
            
            # Générer une plage IP unique
            ip_suffix = abs(hash(network_name)) % 240 + 10
            network_ip = f"192.168.{ip_suffix}"
            
            network_xml = f"""
<network>
  <name>{network_name}</name>
  <forward mode='nat'/>
  <bridge name='virbr_{ip_suffix}' stp='on' delay='0'/>
  <ip address='{network_ip}.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='{network_ip}.10' end='{network_ip}.200'/>
    </dhcp>
  </ip>
</network>
"""
            net = conn.networkDefineXML(network_xml)
            net.setAutostart(1)
            net.create()
            return True
        except Exception as e:
            print(f"Erreur création réseau {network_name}: {e}", file=sys.stderr)
            return False
        finally:
            if conn:
                conn.close()
    
    @staticmethod
    def create_user_network(uri: str, username: str) -> bool:
        """Crée un réseau pour un utilisateur"""
        network_name = NetworkService.get_user_network_name(username)
        return NetworkService.create_network(uri, network_name)
    
    @staticmethod
    def create_swarm_network(uri: str, username: str, cluster_name: str) -> bool:
        """Crée un réseau pour un cluster Swarm"""
        network_name = NetworkService.get_swarm_network_name(username, cluster_name)
        return NetworkService.create_network(uri, network_name)
    
    @staticmethod
    def delete_network(uri: str, network_name: str) -> bool:
        """Supprime un réseau"""
        conn = LibvirtService.get_connection(uri)
        if not conn:
            return False
        
        try:
            net = conn.networkLookupByName(network_name)
            if net.isActive():
                net.destroy()
            net.undefine()
            return True
        except:
            return False
        finally:
            if conn:
                conn.close()