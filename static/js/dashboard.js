// ── Sidebar toggle (mobile) ──────────────────────────────────────────────────
function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
}

// ── Format currency ──────────────────────────────────────────────────────────
function formatINR(paise) {
    return '₹' + (paise / 100).toLocaleString('en-IN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

// ── Revenue Line Chart ───────────────────────────────────────────────────────
function initRevenueChart(labels, data) {
    const ctx = document.getElementById('revenueChart');
    if (!ctx) return;

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Revenue (₹)',
                data: data,
                borderColor: '#2563eb',
                backgroundColor: 'rgba(37,99,235,.08)',
                borderWidth: 2,
                pointRadius: 4,
                pointBackgroundColor: '#2563eb',
                fill: true,
                tension: 0.4,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: { color: '#f1f5f9' },
                    ticks: {
                        callback: v => '₹' + (v/100).toLocaleString('en-IN')
                    }
                },
                x: { grid: { display: false } }
            }
        }
    });
}

// ── Payment Method Doughnut Chart ────────────────────────────────────────────
function initMethodChart(labels, data) {
    const ctx = document.getElementById('methodChart');
    if (!ctx) return;

    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: ['#2563eb','#16a34a','#d97706','#7c3aed','#db2777'],
                borderWidth: 0,
                hoverOffset: 4,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { font: { size: 12 }, padding: 16 }
                }
            },
            cutout: '65%',
        }
    });
}