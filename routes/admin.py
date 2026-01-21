# routes/admin.py
from flask import Blueprint, render_template, request, jsonify, session
from models.host import HostManager
from models.user import UserManager
from models.storage import StorageManager
from routes.auth import login_required, admin_required

admin_bp = Blueprint('admin', __name__)
host_manager = HostManager()
user_manager = UserManager()
storage = StorageManager()

@admin_bp.route('/admin')
@login_required
@admin_required
def index():
    """Dashboard administrateur"""
    return render_template('admin.html')

@admin_bp.route('/admin/hosts')
@login_required
@admin_required
def hosts_management():
    """Gestion des hôtes KVM"""
    hosts = host_manager.get_all_hosts()
    
    # Ajouter les statistiques d'utilisation
    for host in hosts:
        if host.get('enabled', True):
            usage = host_manager.get_host_usage(host['uri'])
            host['usage'] = usage
            host['status'] = 'online' if usage else 'offline'
        else:
            host['status'] = 'disabled'
    
    return render_template('admin_hosts.html', hosts=hosts)

@admin_bp.route('/api/admin/hosts', methods=['GET'])
@login_required
@admin_required
def api_get_hosts():
    """API pour récupérer les hôtes"""
    hosts = host_manager.get_all_hosts()
    
    for host in hosts:
        if host.get('enabled', True):
            usage = host_manager.get_host_usage(host['uri'])
            host['usage'] = usage
            host['status'] = 'online' if usage else 'offline'
        else:
            host['status'] = 'disabled'
    
    return jsonify(hosts)

@admin_bp.route('/api/admin/hosts', methods=['POST'])
@login_required
@admin_required
def api_add_host():
    """API pour ajouter un hôte"""
    data = request.json
    host = host_manager.add_host(data)
    return jsonify({'success': True, 'host': host})

@admin_bp.route('/api/admin/hosts/<host_id>', methods=['PUT'])
@login_required
@admin_required
def api_update_host(host_id):
    """API pour mettre à jour un hôte"""
    data = request.json
    host = host_manager.update_host(host_id, data)
    
    if host:
        return jsonify({'success': True, 'host': host})
    else:
        return jsonify({'success': False, 'error': 'Hôte non trouvé'}), 404

@admin_bp.route('/api/admin/hosts/<host_id>', methods=['DELETE'])
@login_required
@admin_required
def api_delete_host(host_id):
    """API pour supprimer un hôte"""
    success = host_manager.delete_host(host_id)
    return jsonify({'success': success})

@admin_bp.route('/admin/users')
@login_required
@admin_required
def users_management():
    """Gestion des utilisateurs"""
    users = storage.load_users()
    return render_template('admin_users.html', users=users)

@admin_bp.route('/admin/billing')
@login_required
@admin_required
def billing_management():
    """Gestion de la facturation"""
    billing = storage.load_billing()
    return render_template('admin_billing.html', billing=billing)