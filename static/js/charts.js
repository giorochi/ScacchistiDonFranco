// Function to create player statistics chart
function createPlayerStatsChart() {
    const canvas = document.getElementById('playerStatsChart');
    if (!canvas) return;

    const wins = parseInt(canvas.dataset.wins || 0);
    const draws = parseInt(canvas.dataset.draws || 0);
    const losses = parseInt(canvas.dataset.losses || 0);

    new Chart(canvas, {
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
                }
            }
        }
    });
}

// Initialize charts when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    createPlayerStatsChart();
});
function createPlayerStatsChart(canvasId, wins, draws, losses) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    
    const data = {
        labels: ['Wins', 'Draws', 'Losses'],
        datasets: [{
            data: [wins, draws, losses],
            backgroundColor: [
                '#2ecc71', // Success color for wins
                '#f1c40f', // Warning color for draws
                '#e74c3c'  // Danger color for losses
            ],
            borderColor: [
                '#27ae60',
                '#f39c12',
                '#c0392b'
            ],
            borderWidth: 1
        }]
    };
    
    const options = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                position: 'bottom',
                labels: {
                    font: {
                        size: 14
                    },
                    padding: 20
                }
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
    };
    
    return new Chart(ctx, {
        type: 'pie',
        data: data,
        options: options
    });
}

// Function to create tournament progress chart
function createTournamentProgressChart(canvasId, labels, data) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    
    const chartData = {
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
    };
    
    const options = {
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
            },
            tooltip: {
                backgroundColor: 'rgba(44, 62, 80, 0.8)',
                titleFont: {
                    size: 16
                },
                bodyFont: {
                    size: 14
                },
                padding: 15
            }
        }
    };
    
    return new Chart(ctx, {
        type: 'line',
        data: chartData,
        options: options
    });
}

// Function to create group standings chart
function createGroupStandingsChart(canvasId, players, points) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    
    const data = {
        labels: players,
        datasets: [{
            label: 'Points',
            data: points,
            backgroundColor: 'rgba(142, 68, 173, 0.7)',
            borderColor: 'rgba(142, 68, 173, 1)',
            borderWidth: 1
        }]
    };
    
    const options = {
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
    };
    
    return new Chart(ctx, {
        type: 'bar',
        data: data,
        options: options
    });
}

// Initialize charts when the DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Player stats chart
    const playerStatsCanvas = document.getElementById('playerStatsChart');
    if (playerStatsCanvas) {
        const wins = parseInt(playerStatsCanvas.getAttribute('data-wins') || 0);
        const draws = parseInt(playerStatsCanvas.getAttribute('data-draws') || 0);
        const losses = parseInt(playerStatsCanvas.getAttribute('data-losses') || 0);
        
        createPlayerStatsChart('playerStatsChart', wins, draws, losses);
    }
    
    // Tournament progress chart
    const tournamentProgressCanvas = document.getElementById('tournamentProgressChart');
    if (tournamentProgressCanvas) {
        const labels = JSON.parse(tournamentProgressCanvas.getAttribute('data-labels') || '[]');
        const data = JSON.parse(tournamentProgressCanvas.getAttribute('data-values') || '[]');
        
        createTournamentProgressChart('tournamentProgressChart', labels, data);
    }
    
    // Group standings charts
    const groupCharts = document.querySelectorAll('.group-standings-chart');
    if (groupCharts.length > 0) {
        groupCharts.forEach(canvas => {
            const players = JSON.parse(canvas.getAttribute('data-players') || '[]');
            const points = JSON.parse(canvas.getAttribute('data-points') || '[]');
            
            createGroupStandingsChart(canvas.id, players, points);
        });
    }
});
