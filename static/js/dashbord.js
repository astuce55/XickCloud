let prevStats = {}; // Stockage pour calcul CPU

function renderVMs(vms) {
    const tbody = document.getElementById('vm-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    let totalRunning = 0;
    let totalRamUsedMiB = 0;
    let totalCpuUsage = 0;

    vms.forEach(vm => {
        const isRun = vm.status.toLowerCase() === 'running';
        if (isRun) totalRunning++;

        // --- CALCUL CPU (Point 1) ---
        let cpuUsage = 0;
        if (isRun && prevStats[vm.name]) {
            const timeDiff = vm.timestamp - prevStats[vm.name].timestamp;
            const cpuDiff = vm.cpu_time - prevStats[vm.name].cpu_time;
            if (timeDiff > 0) {
                // Formule : (Delta nanosecondes / Delta temps) / (1e9 pour ns -> s) / nb vcpu
                cpuUsage = (cpuDiff / timeDiff) / 10000000; 
                cpuUsage = Math.min(Math.max(cpuUsage, 0), 100); // Brider entre 0 et 100
            }
        }
        // Sauvegarde pour le prochain tour
        prevStats[vm.name] = { cpu_time: vm.cpu_time, timestamp: vm.timestamp };
        if (isRun) totalCpuUsage += cpuUsage;

        // RAM
        let ramPct = 0;
        if (isRun && vm.max_mem > 0) {
            ramPct = (vm.used_mem / vm.max_mem) * 100;
            totalRamUsedMiB += vm.used_mem;
        }

        const row = document.createElement('tr');
        row.innerHTML = `
            <td><div class="fw-bold">${vm.name}</div></td>
            <td><span class="badge bg-dark border border-secondary text-muted">${vm.username}</span></td>
            <td><code>${vm.ip !== "N/A" ? vm.ip : '---'}</code></td>
            <td style="width: 180px">
                <div class="d-flex justify-content-between small mb-1">
                    <span>CPU: ${isRun ? cpuUsage.toFixed(1) + '%' : '0%'}</span>
                    <span>RAM: ${ramPct.toFixed(0)}%</span>
                </div>
                <div class="progress-xick">
                    <div class="bar" style="width: ${ramPct}%"></div>
                </div>
            </td>
            <td>
                <span class="${isRun ? 'text-success' : 'text-muted'} small fw-bold">
                    <i class="fas fa-circle me-1" style="font-size: 8px"></i> ${vm.status.toUpperCase()}
                </span>
            </td>
            <td class="text-end">
                ${isRun ? 
                    `<button class="btn btn-sm btn-dark text-warning me-1" onclick="controlVM('${vm.name}', 'stop', this)"><i class="fas fa-stop"></i></button>` : 
                    `<button class="btn btn-sm btn-dark text-success me-1" onclick="controlVM('${vm.name}', 'start', this)"><i class="fas fa-play"></i></button>`
                }
                <button class="btn btn-sm btn-dark text-danger" onclick="controlVM('${vm.name}', 'delete', this)"><i class="fas fa-trash"></i></button>
            </td>
        `;
        tbody.appendChild(row);
    });

    // Stats Globales
    const clusterCpu = totalRunning > 0 ? (totalCpuUsage / totalRunning).toFixed(1) : 0;
    document.getElementById('global-cpu').innerText = clusterCpu + "%";
    document.getElementById('bar-cpu').style.width = clusterCpu + "%";
    document.getElementById('global-running').innerText = totalRunning;
    document.getElementById('global-ram').innerText = (totalRamUsedMiB / 1024).toFixed(1) + " GiB";
}

async function controlVM(name, action, btn) {
    if (action === 'delete' && !confirm(`Supprimer ${name} ?`)) return;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    try {
        await fetch(`/api/vm/${name}/${action}`, { method: 'POST' });
    } finally { fetchStats(); }
}

async function handleDeploy(event) {
    event.preventDefault();
    const btn = document.getElementById('deployBtn');
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Déploiement...';
    btn.disabled = true;
    try {
        const response = await fetch('/deploy', { method: 'POST', body: new FormData(event.target) });
        if (response.ok) {
            bootstrap.Modal.getInstance(document.getElementById('deployModal')).hide();
            fetchStats();
        } else { alert("Erreur lors du déploiement"); }
    } finally {
        btn.innerHTML = 'Démarrer le déploiement';
        btn.disabled = false;
    }
}

function fetchStats() {
    fetch('/api/monitor')
        .then(r => r.json())
        .then(data => renderVMs(data))
        .catch(e => console.error("Update failed"));
}

function filterVMs() {
    const term = document.getElementById('searchInput').value.toLowerCase();
    document.querySelectorAll('#vm-table-body tr').forEach(row => {
        row.style.display = row.innerText.toLowerCase().includes(term) ? '' : 'none';
    });
}

document.addEventListener('DOMContentLoaded', () => {
    fetchStats();
    setInterval(fetchStats, 3000);
});

