# app.py - VERSION CORRIGÉE SANS URL_PREFIX CONFLICTUELS
from flask import Flask, render_template, session, redirect, url_for
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

# Enregistrer les Blueprints SANS url_prefix (les routes sont déjà définies dans les blueprints)
# CORRECTION: Retirer tous les url_prefix='/' qui ne servent à rien et causent des conflits
app.register_blueprint(auth_bp)
app.register_blueprint(iaas_bp)
app.register_blueprint(swarm_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(paas_bp)

# Route dashboard unifié
@app.route('/')
@login_required
def index():
    """Redirige vers le dashboard approprié"""
    if 'username' in session:
        return redirect(url_for('iaas.index'))
    return redirect(url_for('auth.login'))

# Alias pour le dashboard
@app.route('/dashboard')
@login_required
def dashboard():
    """Alias pour le dashboard"""
    if 'username' in session:
        return redirect(url_for('iaas.index'))
    return redirect(url_for('auth.login'))

# Gestion des erreurs
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

# Route de debug pour lister toutes les routes (utile pour débogage)
@app.route('/debug/routes')
def list_routes():
    """Liste toutes les routes disponibles (DEBUG ONLY)"""
    if not app.debug:
        return "Debug mode only", 403
    
    import urllib.parse
    output = ['<h1>Routes enregistrées dans Flask</h1><pre>']
    
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
        methods = ','.join([m for m in rule.methods if m not in ['HEAD', 'OPTIONS']])
        line = f"{str(rule):60s} {methods:20s} → {rule.endpoint}"
        output.append(line)
    
    output.append('</pre>')
    return '\n'.join(output)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=DEBUG)