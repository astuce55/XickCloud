// static/js/main.js

// Fonctions utilitaires
function showLoading(button) {
    if (button) {
        const originalHTML = button.innerHTML;
        button.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Chargement...';
        button.disabled = true;
        return originalHTML;
    }
}

function hideLoading(button, originalHTML) {
    if (button && originalHTML) {
        button.innerHTML = originalHTML;
        button.disabled = false;
    }
}

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-bg-${type} border-0`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
        </div>
    `;
    
    const container = document.querySelector('.toast-container');
    if (!container) {
        const newContainer = document.createElement('div');
        newContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        document.body.appendChild(newContainer);
        container = newContainer;
    }
    
    container.appendChild(toast);
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
    
    // Supprimer après la disparition
    toast.addEventListener('hidden.bs.toast', function () {
        toast.remove();
    });
}

// Gestion des VMs
async function controlVM(vmName, action) {
    if (action === 'delete' && !confirm(`Supprimer la VM ${vmName} ?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/vm/${vmName}/${action}`, {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(`VM ${action === 'start' ? 'démarrée' : action === 'stop' ? 'arrêtée' : 'supprimée'} avec succès`, 'success');
            // Recharger la page après un délai
            setTimeout(() => location.reload(), 1000);
        } else {
            showToast(`Erreur: ${data.msg}`, 'danger');
        }
    } catch (error) {
        showToast('Erreur réseau', 'danger');
    }
}

// Gestion des clusters Swarm
async function deploySwarmCluster() {
    const form = document.getElementById('deploySwarmForm');
    if (!form) return;
    
    const button = form.querySelector('button[type="submit"]');
    const originalHTML = showLoading(button);
    
    const formData = new FormData(form);
    const data = {
        cluster_name: formData.get('cluster_name'),
        num_managers: parseInt(formData.get('num_managers')),
        num_workers: parseInt(formData.get('num_workers')),
        password: formData.get('password'),
        ssh_key: formData.get('ssh_key')
    };
    
    try {
        const response = await fetch('/api/swarm/deploy', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        
        if (result.success) {
            showToast(`Cluster ${result.cluster.name} en cours de déploiement`, 'success');
            // Fermer le modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('deploySwarmModal'));
            modal.hide();
            // Recharger la page
            setTimeout(() => location.reload(), 2000);
        } else {
            showToast(`Erreur: ${result.msg}`, 'danger');
        }
    } catch (error) {
        showToast('Erreur réseau', 'danger');
    } finally {
        hideLoading(button, originalHTML);
    }
}

async function deleteSwarmCluster(clusterName) {
    if (!confirm(`Supprimer le cluster ${clusterName} et toutes ses VMs ?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/swarm/cluster/${clusterName}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (result.success) {
            showToast(`Cluster ${clusterName} supprimé`, 'success');
            location.reload();
        } else {
            showToast(`Erreur: ${result.msg}`, 'danger');
        }
    } catch (error) {
        showToast('Erreur réseau', 'danger');
    }
}

// Gestion des applications PaaS
async function deployPaaSApp(appId) {
    const appName = prompt(`Nom pour l'application ${appId}:`, `${appId}-${Date.now()}`);
    if (!appName) return;
    
    const clusterName = prompt('Nom du cluster Swarm (laisser vide pour défaut):', '');
    
    try {
        const response = await fetch('/api/paas/deploy', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                app_id: appId,
                app_name: appName,
                cluster_name: clusterName || 'default'
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showToast(`Application ${appName} en cours de déploiement`, 'success');
            location.reload();
        } else {
            showToast(`Erreur: ${result.msg}`, 'danger');
        }
    } catch (error) {
        showToast('Erreur réseau', 'danger');
    }
}

async function deletePaaSApp(appId) {
    if (!confirm(`Supprimer l'application ${appId} ?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/paas/app/${appId}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (result.success) {
            showToast('Application en cours de suppression', 'success');
            location.reload();
        } else {
            showToast(`Erreur: ${result.msg}`, 'danger');
        }
    } catch (error) {
        showToast('Erreur réseau', 'danger');
    }
}

// Recherche globale
function setupGlobalSearch() {
    const searchInput = document.getElementById('globalSearch');
    if (searchInput) {
        searchInput.addEventListener('input', function(e) {
            const term = e.target.value.toLowerCase();
            const tables = document.querySelectorAll('table');
            
            tables.forEach(table => {
                const rows = table.querySelectorAll('tbody tr');
                rows.forEach(row => {
                    const text = row.textContent.toLowerCase();
                    row.style.display = text.includes(term) ? '' : 'none';
                });
            });
        });
    }
}

// Mise à jour automatique des statistiques
function setupAutoRefresh() {
    // Mettre à jour toutes les 30 secondes si sur le dashboard
    if (window.location.pathname === '/' || window.location.pathname.includes('/dashboard')) {
        setInterval(() => {
            // Mettre à jour les stats via AJAX
            fetch('/api/vms')
                .then(response => response.json())
                .then(data => {
                    // Mettre à jour l'interface
                    updateStatsUI(data);
                })
                .catch(error => console.error('Erreur mise à jour:', error));
        }, 30000);
    }
}

function updateStatsUI(vms) {
    // Implémenter la mise à jour des statistiques
    // en fonction des VMs reçues
    console.log('Mise à jour des stats avec', vms.length, 'VMs');
}

// Initialisation
document.addEventListener('DOMContentLoaded', function() {
    // Configurer la recherche globale
    setupGlobalSearch();
    
    // Configurer le rafraîchissement automatique
    setupAutoRefresh();
    
    // Ajouter des animations
    document.querySelectorAll('.stat-card, .action-card').forEach(card => {
        card.classList.add('fade-in');
    });
    
    // Gérer les formulaires
    const forms = document.querySelectorAll('form[data-ajax="true"]');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            const action = this.getAttribute('action');
            const method = this.getAttribute('method') || 'POST';
            
            fetch(action, {
                method: method,
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showToast('Opération réussie', 'success');
                    if (data.redirect) {
                        window.location.href = data.redirect;
                    }
                } else {
                    showToast(`Erreur: ${data.msg}`, 'danger');
                }
            })
            .catch(error => {
                showToast('Erreur réseau', 'danger');
            });
        });
    });
    
    // Initialiser les tooltips Bootstrap
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    tooltipTriggerList.forEach(tooltipTriggerEl => {
        new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Initialiser les popovers Bootstrap
    const popoverTriggerList = document.querySelectorAll('[data-bs-toggle="popover"]');
    popoverTriggerList.forEach(popoverTriggerEl => {
        new bootstrap.Popover(popoverTriggerEl);
    });
});

// Exposer les fonctions globales
window.controlVM = controlVM;
window.deploySwarmCluster = deploySwarmCluster;
window.deleteSwarmCluster = deleteSwarmCluster;
window.deployPaaSApp = deployPaaSApp;
window.deletePaaSApp = deletePaaSApp;