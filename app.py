# app.py
from flask import Flask, render_template
from config import SECRET_KEY, DEBUG
from models.user import UserManager
from routes.auth import auth_bp, login_required
from routes.iaas import iaas_bp
from routes.swarm import swarm_bp
from routes.admin import admin_bp
from routes.paas import paas_bp

# Initialisation de Flask
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.debug = DEBUG

# Initialiser les utilisateurs par défaut
user_manager = UserManager()
user_manager.init_default_users()

# Enregistrer les Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(iaas_bp)
app.register_blueprint(swarm_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(paas_bp)

# Route dashboard unifié - CORRECTION ICI
@app.route('/')
@login_required
def index():
    """Redirige vers le dashboard approprié"""
    from flask import session, redirect, url_for
    if 'username' in session:
        return redirect(url_for('iaas.index'))  # Rediriger vers iaas.index
    return redirect(url_for('auth.login'))

# Alias pour le dashboard - CORRECTION ICI
@app.route('/dashboard')
def dashboard():
    """Alias pour le dashboard"""
    from flask import session, redirect, url_for
    if 'username' in session:
        return redirect(url_for('iaas.index'))  # Rediriger vers iaas.index
    return redirect(url_for('auth.login'))

# Gestion des erreurs
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=DEBUG)