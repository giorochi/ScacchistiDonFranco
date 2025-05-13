// Function to create player statistics chart
function createPlayerStatsChart() {
    const canvas = document.getElementById('playerStatsChart');
    if (!canvas) {
        console.log('Canvas element not found');
        return;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) {
        console.log('Could not get 2d context');
        return;
    }

    const wins = parseInt(canvas.dataset.wins || 0);
    const draws = parseInt(canvas.dataset.draws || 0);
    const losses = parseInt(canvas.dataset.losses || 0);

    new Chart(ctx, {
        type: 'pie',
        data: {
            labels: ['Wins', 'Draws', 'Losses'],
            datasets: [{
                data: [wins, draws, losses],
                backgroundColor: ['#28a745', '#ffc107', '#dc3545']
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom'
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const total = wins + draws + losses;
                            const value = context.raw;
                            const percentage = Math.round((value / total) * 100);
                            return `${context.label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

// Function to create tournament progress chart
function createTournamentProgressChart(canvasId, labels, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Points',
                data: data,
                backgroundColor: 'rgba(52, 152, 219, 0.2)',
                borderColor: 'rgba(52, 152, 219, 1)',
                borderWidth: 2,
                pointBackgroundColor: 'rgba(52, 152, 219, 1)',
                pointBorderColor: '#fff',
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: 'rgba(52, 152, 219, 1)',
                pointRadius: 5,
                pointHoverRadius: 7,
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        precision: 1
                    }
                }
            },
            plugins: {
                legend: {
                    display: false
                }
            }
        }
    });
}

// Function to create group standings chart
function createGroupStandingsChart(canvasId, players, points) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: players,
            datasets: [{
                label: 'Points',
                data: points,
                backgroundColor: 'rgba(142, 68, 173, 0.7)',
                borderColor: 'rgba(142, 68, 173, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: 'y',
            scales: {
                x: {
                    beginAtZero: true,
                    ticks: {
                        precision: 1
                    }
                }
            },
            plugins: {
                legend: {
                    display: false
                }
            }
        }
    });
}

// Initialize charts when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Initialize player stats chart if element exists
    createPlayerStatsChart();

    // Initialize tournament progress chart if element exists
    const tournamentProgressCanvas = document.getElementById('tournamentProgressChart');
    if (tournamentProgressCanvas) {
        const labels = JSON.parse(tournamentProgressCanvas.dataset.labels || '[]');
        const data = JSON.parse(tournamentProgressCanvas.dataset.values || '[]');
        createTournamentProgressChart('tournamentProgressChart', labels, data);
    }

    // Initialize group standings charts if elements exist
    const groupCharts = document.querySelectorAll('.group-standings-chart');
    groupCharts.forEach(canvas => {
        const players = JSON.parse(canvas.dataset.players || '[]');
        const points = JSON.parse(canvas.dataset.points || '[]');
        createGroupStandingsChart(canvas.id, players, points);
    });
});