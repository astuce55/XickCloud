# routes/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from functools import wraps
from models.user import UserManager

auth_bp = Blueprint('auth', __name__)
user_manager = UserManager()

# Initialiser les utilisateurs par défaut
user_manager.init_default_users()

# Décorateurs d'authentification
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session or session.get('role') != 'admin':
            from flask import jsonify
            return jsonify({'error': 'Accès interdit'}), 403
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if user_manager.authenticate(username, password):
            session['username'] = username
            session['role'] = user_manager.get_user_role(username)
            return redirect(url_for('iaas.index'))  # CORRECTION: Rediriger vers iaas.index
        
        flash('Identifiants incorrects', 'error')
    
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))