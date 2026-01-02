// --- CONFIGURATION ---
const MAX_HISTORY = 60; 
let vmHistory = {};     
let prevData = {};      
let detailChartCpu = null;
let detailChartRam = null;
let currentDetailVM = null;

// --- ACTIONS UI ---
function toggleSSH(m) {
    const p = document.getElementById('ssh-paste-area');
    const g = document.getElementById('ssh-gen-area');
    if(p && g) {
        p.style.display = (m === 'paste') ? 'block' : 'none';
        g.style.display = (m === 'gen') ? 'block' : 'none';
    }
}

function copyToClip(id) {
    const el = document.getElementById(id);
    if(el) {
        navigator.clipboard.writeText(el.value);
        alert("Copié !");
    }
}

function showConsole(n, ip) {
    document.getElementById('virsh-vm-name').innerText = n;
    const sshField = document.getElementById('ssh-cmd');
    sshField.value = (ip && ip !== 'N/A') ? `ssh user@${ip}` : 'En attente IP...';
    
    // Utilisation de window.bootstrap pour être sûr que la lib est chargée
    const modal = new bootstrap.Modal(document.getElementById('consoleModal'));
    modal.show();
}

function controlVM(name, action, btnElement) {
    if (action === 'delete' && !confirm(`⚠ SUPPRESSION DÉFINITIVE ⚠\n\nVoulez-vous vraiment supprimer "${name}" ?`)) return;

    // Feedback visuel
    const originalContent = btnElement.innerHTML;
    btnElement.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i>';
    btnElement.disabled = true;

    fetch(`/api/vm/${name}/${action}`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                fetchStats(); // Rafraîchissement immédiat
            } else {
                alert("Erreur KVM : " + data.msg);
            }
        })
        .catch(err => console.error("API Error:", err))
        .finally(() => {
            setTimeout(() => {
                if(btnElement) {
                    btnElement.innerHTML = originalContent;
                    btnElement.disabled = false;
                }
            }, 500);
        });
}

// --- GRAPHIQUES DETAILS ---
function openDetails(vmName) {
    currentDetailVM = vmName;
    document.getElementById('detail-title').innerText = "MONITORING : " + vmName.toUpperCase();
    
    const modalEl = document.getElementById('detailsModal');
    const modal = new bootstrap.Modal(modalEl);
    modal.show();
    
    modalEl.addEventListener('shown.bs.modal', () => {
        initDetailCharts();
        updateDetailCharts();
    }, { once: true });
}

function initDetailCharts() {
    if (detailChartCpu) detailChartCpu.destroy();
    if (detailChartRam) detailChartRam.destroy();

    const commonOptions = {
        responsive: true, maintainAspectRatio: false, animation: false,
        elements: { line: { tension: 0.4 }, point: { radius: 0 } },
        scales: {
            x: { display: false },
            y: { beginAtZero: true, grid: { color: '#334155' }, ticks: { color: '#94a3b8' } }
        },
        plugins: { legend: { display: false } }
    };

    const ctxCpu = document.getElementById('detailCpuChart').getContext('2d');
    detailChartCpu = new Chart(ctxCpu, {
        type: 'line',
        data: { labels: [], datasets: [{ label: 'CPU %', data: [], borderColor: '#10b981', backgroundColor: 'rgba(16, 185, 129, 0.2)', fill: true }] },
        options: { ...commonOptions, scales: { ...commonOptions.scales, y: { ...commonOptions.scales.y, max: 100 } } }
    });

    const ctxRam = document.getElementById('detailRamChart').getContext('2d');
    detailChartRam = new Chart(ctxRam, {
        type: 'line',
        data: { labels: [], datasets: [{ label: 'RAM', data: [], borderColor: '#f97316', backgroundColor: 'rgba(249, 115, 22, 0.2)', fill: true }] },
        options: commonOptions
    });
}

function updateDetailCharts() {
    if (!currentDetailVM || !vmHistory[currentDetailVM] || !detailChartCpu) return;
    const hist = vmHistory[currentDetailVM];
    
    detailChartCpu.data.labels = hist.labels;
    detailChartCpu.data.datasets[0].data = hist.cpu;
    detailChartCpu.update('none');

    detailChartRam.data.labels = hist.labels;
    detailChartRam.data.datasets[0].data = hist.ram;
    detailChartRam.update('none');
    
    // Update text values inside modal
    if(hist.cpu.length > 0) {
        document.getElementById('det-cpu-val').innerText = hist.cpu[hist.cpu.length-1] + "%";
        document.getElementById('det-ram-val').innerText = hist.ram[hist.ram.length-1] + " MiB";
    }
}

// --- RENDERING CORE ---
function renderVMs(vms) {
    // 1. GLOBAL STATS
    let runningCount = vms.filter(v => v.status === 'Running').length;
    let ramTotal = vms.reduce((acc, v) => acc + (v.status === 'Running' ? v.used_mem : 0), 0) / 1024;
    let cpuClusterTotal = 0;

    const elRun = document.getElementById('global-running');
    if(elRun) elRun.innerText = runningCount + " / " + vms.length;
    
    const elRam = document.getElementById('global-ram');
    if(elRam) elRam.innerText = ramTotal.toFixed(2) + " GiB";
    
    const elEmpty = document.getElementById('empty-state');
    if(elEmpty) elEmpty.style.display = vms.length === 0 ? 'block' : 'none';

    // 2. BUILD TABLE
    const tbody = document.getElementById('vm-table-body');
    const sidebar = document.getElementById('sidebar-vm-list');
    
    if (!tbody || !sidebar) return; // Sécurité si le DOM n'est pas prêt

    tbody.innerHTML = '';
    sidebar.innerHTML = '';

    vms.forEach((vm, index) => {
        // --- CALCUL CPU ---
        let cpu = 0;
        if (prevData[vm.name]) {
            const dC = vm.cpu_time - prevData[vm.name].cpu_time;
            const dT = vm.timestamp - prevData[vm.name].timestamp;
            if (dT > 0) cpu = ((dC / 1e9) / dT / vm.vcpu) * 100;
        }
        prevData[vm.name] = vm;
        cpu = parseFloat(Math.min(Math.max(cpu, 0), 100).toFixed(1));
        if (vm.status === 'Running') cpuClusterTotal += cpu;

        // --- HISTORIQUE ---
        if (!vmHistory[vm.name]) vmHistory[vm.name] = { cpu: [], ram: [], labels: [] };
        const hist = vmHistory[vm.name];
        const timeLabel = new Date().toLocaleTimeString();
        hist.labels.push(timeLabel);
        hist.cpu.push(cpu);
        hist.ram.push(vm.used_mem.toFixed(0));
        if (hist.labels.length > MAX_HISTORY) { hist.labels.shift(); hist.cpu.shift(); hist.ram.shift(); }

        // --- ELEMENTS ---
        const isRun = vm.status === 'Running';
        const statusClass = isRun ? 'running' : 'stopped';
        const ramPct = vm.max_mem > 0 ? ((vm.used_mem / vm.max_mem) * 100) : 0;
        
        // BOUTONS AVEC COULEURS CORRECTES
        const btnPlay = isRun 
            ? `<button class="btn-icon stop" onclick="controlVM('${vm.name}','stop', this)" title="Arrêter"><i class="fas fa-stop"></i></button>`
            : `<button class="btn-icon start" onclick="controlVM('${vm.name}','start', this)" title="Démarrer"><i class="fas fa-play"></i></button>`;

        // SIDEBAR
        const sideItem = document.createElement('div');
        sideItem.className = `tree-item vm-${statusClass}`;
        sideItem.onclick = () => openDetails(vm.name);
        sideItem.innerHTML = `<i class="fas fa-desktop vm-icon"></i> <span>${100+index} (${vm.name})</span>`;
        sidebar.appendChild(sideItem);

        // TABLE
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${100+index}</td>
            <td class="clickable-row vm-name-cell" onclick="openDetails('${vm.name}')">
                <i class="fas fa-search me-2 text-muted"></i>${vm.name}
            </td>
            <td><div class="status-badge ${statusClass}"><div class="dot"></div> ${vm.status}</div></td>
            <td class="font-monospace text-muted">${vm.ip || '-'}</td>
            <td>
                <div class="d-flex align-items-center gap-2">
                    <div class="progress-slim"><div class="progress-bar bg-primary" style="width:${cpu}%"></div></div>
                    <span class="small text-white">${cpu}%</span>
                </div>
            </td>
            <td>
                <div class="d-flex align-items-center gap-2">
                    <div class="progress-slim"><div class="progress-bar bg-warning" style="width:${ramPct}%"></div></div>
                    <span class="small text-white">${ramPct.toFixed(0)}%</span>
                </div>
            </td>
            <td style="text-align: right;">
                ${btnPlay}
                <button class="btn-icon console" onclick="showConsole('${vm.name}','${vm.ip}')" title="Console"><i class="fas fa-terminal"></i></button>
                <button class="btn-icon delete" onclick="controlVM('${vm.name}','delete', this)" title="Supprimer"><i class="fas fa-trash-alt"></i></button>
            </td>
        `;
        tbody.appendChild(row);
    });

    // UPDATE HEADER
    const avgClusterCpu = (vms.length > 0) ? (cpuClusterTotal / vms.length).toFixed(1) : 0;
    const elCpu = document.getElementById('global-cpu');
    const barCpu = document.getElementById('bar-cpu');
    if(elCpu) elCpu.innerText = avgClusterCpu + "%";
    if(barCpu) barCpu.style.width = Math.min(avgClusterCpu, 100) + "%";

    // REFRESH DETAILS
    if(currentDetailVM) updateDetailCharts();
}

function fetchStats() {
    // Detection Environnement
    const isLocal = window.location.protocol === 'file:' || window.location.href.startsWith('blob:');
    
    if (isLocal) {
        // MOCK DATA pour preview sans backend
        const mockVMs = [
            { name: "web-srv", status: "Running", ip: "192.168.122.10", vcpu: 2, max_mem: 2048, used_mem: 1024, cpu_time: Date.now()*1000, timestamp: Date.now()/1000 },
            { name: "db-prod", status: "Stopped", ip: "N/A", vcpu: 4, max_mem: 4096, used_mem: 0, cpu_time: 0, timestamp: Date.now()/1000 }
        ];
        renderVMs(mockVMs);
        return;
    }

    const loader = document.getElementById('loader');
    if(loader) loader.style.visibility = 'visible';

    fetch('/api/monitor')
        .then(r => r.json())
        .then(vms => { renderVMs(vms); })
        .catch(e => console.error("Sync Error:", e))
        .finally(() => { if(loader) loader.style.visibility = 'hidden'; });
}

// Boucle principale
setInterval(fetchStats, 2000);
fetchStats();