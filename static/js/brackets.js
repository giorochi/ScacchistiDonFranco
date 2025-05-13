/**
 * Knockout Tournament Bracket Visualization
 * This script renders and manages tournament bracket visualization
 */

class TournamentBracket {
    constructor(containerId, matches, rounds) {
        this.container = document.getElementById(containerId);
        this.matches = matches;
        this.rounds = rounds;
        this.bracketEl = null;
    }
    
    initialize() {
        if (!this.container) {
            console.error('Tournament bracket container not found');
            return;
        }
        
        // Clear existing content
        this.container.innerHTML = '';
        
        // Create bracket container
        this.bracketEl = document.createElement('div');
        this.bracketEl.className = 'bracket';
        this.container.appendChild(this.bracketEl);
        
        // Generate rounds
        this.generateRounds();
        
        // Add responsive wrapper
        this.makeResponsive();
    }
    
    generateRounds() {
        // Group matches by round
        const matchesByRound = {};
        
        this.matches.forEach(match => {
            const round = match.round;
            if (!matchesByRound[round]) {
                matchesByRound[round] = [];
            }
            matchesByRound[round].push(match);
        });
        
        // Create each round column
        for (let i = 1; i <= this.rounds; i++) {
            const roundMatches = matchesByRound[i] || [];
            this.createRound(i, roundMatches);
        }
    }
    
    createRound(roundNum, matches) {
        const roundEl = document.createElement('div');
        roundEl.className = 'bracket-round';
        roundEl.setAttribute('data-round', roundNum);
        
        const roundName = this.getRoundName(roundNum);
        
        // Add round title
        const titleEl = document.createElement('div');
        titleEl.className = 'bracket-round-title';
        titleEl.textContent = roundName;
        roundEl.appendChild(titleEl);
        
        // Sort matches by match_num within the round
        matches.sort((a, b) => a.match_num - b.match_num);
        
        // Add matches
        matches.forEach(match => {
            const matchEl = this.createMatch(match);
            roundEl.appendChild(matchEl);
        });
        
        this.bracketEl.appendChild(roundEl);
    }
    
    createMatch(match) {
        const matchEl = document.createElement('div');
        matchEl.className = 'bracket-match';
        matchEl.setAttribute('data-match-id', match.id);
        
        // Create white player element
        const whitePlayerEl = document.createElement('div');
        whitePlayerEl.className = 'bracket-team';
        if (match.white_player) {
            whitePlayerEl.textContent = match.white_player.name;
            
            // Highlight winner if match is completed
            if (match.status === 'completed' && 
                (match.result === 'white_win' || match.result === 'forfeit_black')) {
                whitePlayerEl.classList.add('winner');
            }
        } else {
            whitePlayerEl.textContent = 'TBD';
            whitePlayerEl.classList.add('tbd');
        }
        matchEl.appendChild(whitePlayerEl);
        
        // Create black player element
        const blackPlayerEl = document.createElement('div');
        blackPlayerEl.className = 'bracket-team';
        if (match.black_player) {
            blackPlayerEl.textContent = match.black_player.name;
            
            // Highlight winner if match is completed
            if (match.status === 'completed' && 
                (match.result === 'black_win' || match.result === 'forfeit_white')) {
                blackPlayerEl.classList.add('winner');
            }
        } else {
            blackPlayerEl.textContent = 'TBD';
            blackPlayerEl.classList.add('tbd');
        }
        matchEl.appendChild(blackPlayerEl);
        
        // Add match details as data attributes
        matchEl.setAttribute('data-board', match.board_number || 'TBD');
        matchEl.setAttribute('data-status', match.status);
        matchEl.setAttribute('data-time', match.start_time || 'TBD');
        
        // Add tooltip with match details
        const boardText = match.board_number ? `Board: ${match.board_number}` : 'Board: TBD';
        const timeText = match.start_time ? `Time: ${new Date(match.start_time).toLocaleString()}` : 'Time: TBD';
        const statusText = `Status: ${this.capitalizeFirstLetter(match.status)}`;
        
        matchEl.setAttribute('data-bs-toggle', 'tooltip');
        matchEl.setAttribute('data-bs-placement', 'top');
        matchEl.setAttribute('data-bs-html', 'true');
        matchEl.setAttribute('title', `${boardText}<br>${timeText}<br>${statusText}`);
        
        return matchEl;
    }
    
    getRoundName(roundNum) {
        // Handle special round names
        switch(roundNum) {
            case this.rounds:
                return 'Final';
            case this.rounds - 1:
                return 'Semifinal';
            case this.rounds - 2:
                return 'Quarterfinal';
            default:
                return `Round ${roundNum}`;
        }
    }
    
    makeResponsive() {
        // Add horizontal scrolling for small screens
        const wrapperEl = document.createElement('div');
        wrapperEl.className = 'bracket-wrapper';
        wrapperEl.style.overflowX = 'auto';
        
        // Move bracket element into wrapper
        this.container.appendChild(wrapperEl);
        wrapperEl.appendChild(this.bracketEl);
        
        // Set minimum width for the bracket based on number of rounds
        this.bracketEl.style.minWidth = `${this.rounds * 220}px`;
    }
    
    capitalizeFirstLetter(string) {
        return string.charAt(0).toUpperCase() + string.slice(1);
    }
    
    // Update bracket with new match data
    updateMatch(matchId, matchData) {
        const matchEl = this.bracketEl.querySelector(`[data-match-id="${matchId}"]`);
        if (!matchEl) return;
        
        const whitePlayerEl = matchEl.querySelector('.bracket-team:first-child');
        const blackPlayerEl = matchEl.querySelector('.bracket-team:last-child');
        
        // Update white player
        if (matchData.white_player) {
            whitePlayerEl.textContent = matchData.white_player.name;
            whitePlayerEl.classList.remove('tbd');
        }
        
        // Update black player
        if (matchData.black_player) {
            blackPlayerEl.textContent = matchData.black_player.name;
            blackPlayerEl.classList.remove('tbd');
        }
        
        // Update winner highlighting
        whitePlayerEl.classList.remove('winner');
        blackPlayerEl.classList.remove('winner');
        
        if (matchData.status === 'completed') {
            if (matchData.result === 'white_win' || matchData.result === 'forfeit_black') {
                whitePlayerEl.classList.add('winner');
            } else if (matchData.result === 'black_win' || matchData.result === 'forfeit_white') {
                blackPlayerEl.classList.add('winner');
            }
        }
        
        // Update match details
        matchEl.setAttribute('data-board', matchData.board_number || 'TBD');
        matchEl.setAttribute('data-status', matchData.status);
        matchEl.setAttribute('data-time', matchData.start_time || 'TBD');
        
        // Update tooltip
        const boardText = matchData.board_number ? `Board: ${matchData.board_number}` : 'Board: TBD';
        const timeText = matchData.start_time ? `Time: ${new Date(matchData.start_time).toLocaleString()}` : 'Time: TBD';
        const statusText = `Status: ${this.capitalizeFirstLetter(matchData.status)}`;
        
        matchEl.setAttribute('title', `${boardText}<br>${timeText}<br>${statusText}`);
        
        // Refresh tooltip
        const tooltip = bootstrap.Tooltip.getInstance(matchEl);
        if (tooltip) {
            tooltip.dispose();
        }
        new bootstrap.Tooltip(matchEl);
    }
}

// Initialize bracket when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    const bracketContainer = document.getElementById('tournamentBracket');
    if (bracketContainer) {
        // Get tournament data from data attributes
        const matchesData = JSON.parse(bracketContainer.getAttribute('data-matches') || '[]');
        const roundsCount = parseInt(bracketContainer.getAttribute('data-rounds') || '0');
        
        if (matchesData.length > 0 && roundsCount > 0) {
            const bracket = new TournamentBracket('tournamentBracket', matchesData, roundsCount);
            bracket.initialize();
            
            // Initialize tooltips after bracket is rendered
            const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
            tooltipTriggerList.map(function (tooltipTriggerEl) {
                return new bootstrap.Tooltip(tooltipTriggerEl);
            });
            
            // Make bracket available globally for updates
            window.tournamentBracket = bracket;
        }
    }
});
