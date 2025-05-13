/**
 * Knockout Tournament Bracket Visualization
 * This script renders and manages tournament bracket visualization
 */
document.addEventListener('DOMContentLoaded', function() {
    const bracketElement = document.getElementById('tournamentBracket');
    if (!bracketElement) return;

    const matches = JSON.parse(bracketElement.dataset.matches || '[]');
    if (!matches.length) return;

    const rounds = parseInt(bracketElement.dataset.rounds || '0');
    if (!rounds) return;

    // Create bracket structure
    const bracketHtml = createBracketStructure(matches, rounds);
    bracketElement.innerHTML = bracketHtml;
});

function createBracketStructure(matches, totalRounds) {
    let html = '<div class="tournament-bracket">';

    // Group matches by round
    const matchesByRound = {};
    matches.forEach(match => {
        if (!matchesByRound[match.round]) {
            matchesByRound[match.round] = [];
        }
        matchesByRound[match.round].push(match);
    });

    // Create rounds
    for (let round = 1; round <= totalRounds; round++) {
        const roundMatches = matchesByRound[round] || [];
        html += `<div class="round round-${round}">`;
        html += `<h4 class="round-header">${getRoundName(round, totalRounds)}</h4>`;

        roundMatches.sort((a, b) => a.knockout_match_num - b.knockout_match_num);

        roundMatches.forEach(match => {
            html += createMatchBox(match);
        });

        html += '</div>';
    }

    html += '</div>';
    return html;
}

function createMatchBox(match) {
    const whitePlayerName = match.white_player_name || 'TBD';
    const blackPlayerName = match.black_player_name || 'TBD';

    return `
        <div class="match" data-match-id="${match.id}">
            <div class="player white-player ${match.result === 'white_win' ? 'winner' : ''}">${whitePlayerName}</div>
            <div class="player black-player ${match.result === 'black_win' ? 'winner' : ''}">${blackPlayerName}</div>
        </div>
    `;
}

function getRoundName(round, totalRounds) {
    if (round === totalRounds) return 'Final';
    if (round === totalRounds - 1) return 'Semi-Finals';
    if (round === totalRounds - 2) return 'Quarter-Finals';
    return `Round ${round}`;
}