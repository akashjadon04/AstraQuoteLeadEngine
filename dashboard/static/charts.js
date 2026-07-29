// Chart configuration defaults for dark theme
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = 'rgba(255, 255, 255, 0.1)';

// initDashboardCharts() runs more than once per page view (initial load, then
// again whenever the pipeline finishes while the dashboard is open) — Chart.js
// throws "Canvas is already in use" if a new Chart is created on a canvas that
// still holds a previous instance, so every instance created here must be
// tracked and destroyed before its canvas is reused.
const _dashboardCharts = {};

function _renderChart(canvasId, config) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    if (_dashboardCharts[canvasId]) {
        _dashboardCharts[canvasId].destroy();
    }
    _dashboardCharts[canvasId] = new Chart(ctx, config);
}

async function initDashboardCharts() {
    try {
        const response = await fetch('/api/stats');
        const data = await response.json();

        // 1. Canton Distribution (Doughnut)
        _renderChart('cantonChart', {
            type: 'doughnut',
            data: {
                labels: Object.keys(data.canton_distribution),
                datasets: [{
                    data: Object.values(data.canton_distribution),
                    backgroundColor: [
                        '#8b5cf6', '#06b6d4', '#22c55e', '#f59e0b', '#ef4444',
                        '#ec4899', '#8b5cf6', '#14b8a6'
                    ],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'right' } }
            }
        });

        // 2. Niche Distribution (Horizontal Bar)
        _renderChart('nicheChart', {
            type: 'bar',
            data: {
                labels: Object.keys(data.niche_distribution),
                datasets: [{
                    label: 'Leads by Niche',
                    data: Object.values(data.niche_distribution),
                    backgroundColor: '#06b6d4',
                    borderRadius: 4
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } }
            }
        });

        // 3. Urgency Distribution (Bar)
        _renderChart('urgencyChart', {
            type: 'bar',
            data: {
                labels: Object.keys(data.urgency_distribution),
                datasets: [{
                    label: 'Leads by Urgency',
                    data: Object.values(data.urgency_distribution),
                    backgroundColor: [
                        '#ef4444', // High
                        '#f59e0b', // Medium
                        '#22c55e'  // Low
                    ],
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } }
            }
        });

        // 4. Fit Score Distribution (Bar) — the ICP-match axis (size, legitimacy,
        // niche, named contact), deliberately shown separately from Urgency/Digital
        // above so "best leads" and "worst website" are never conflated.
        if (data.fit_distribution) {
            _renderChart('fitChart', {
                type: 'bar',
                data: {
                    labels: Object.keys(data.fit_distribution),
                    datasets: [{
                        label: 'Leads by Fit Score',
                        data: Object.values(data.fit_distribution),
                        backgroundColor: [
                            '#10b981', // Qualified
                            '#06b6d4', // Good
                            '#f59e0b', // Fair
                            '#ef4444'  // Poor
                        ],
                        borderRadius: 4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } }
                }
            });
        }

        // 5. Company Size Distribution (Bar) — the "is it big enough" axis. Green
        // for bands worth calling (established/small), amber/red for the one/two-
        // person shops the sales team asked us to filter out.
        if (data.size_distribution) {
            const sizeColors = {
                'Established (~10+)': '#10b981',
                'Small team (~4-9)': '#22c55e',
                'Micro (~2-3)': '#f59e0b',
                'Sole trader (~1)': '#ef4444',
                'Unknown': '#64748b'
            };
            const sizeLabels = Object.keys(data.size_distribution);
            _renderChart('sizeChart', {
                type: 'bar',
                data: {
                    labels: sizeLabels,
                    datasets: [{
                        label: 'Leads by Estimated Size',
                        data: Object.values(data.size_distribution),
                        backgroundColor: sizeLabels.map(l => sizeColors[l] || '#64748b'),
                        borderRadius: 4
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } }
                }
            });
        }

    } catch (error) {
        console.error('Error loading chart data:', error);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('cantonChart')) {
        initDashboardCharts();
    }
});
