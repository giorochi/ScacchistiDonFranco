import random
from datetime import datetime, timedelta
from app import db
from models import Tournament, Player, TournamentPlayer, Group, Match, MatchStatus, MatchResult, TournamentStatus

def assign_board_numbers(matches, total_boards):
    # Assegna i numeri delle scacchiere in modo ciclico
    for i, match in enumerate(matches):
        match.board_number = (i % total_boards) + 1

def create_groups(tournament_id):
    """Create groups for a tournament and assign players to groups"""
    tournament = Tournament.query.get(tournament_id)
    if not tournament:
        return False, "Tournament not found"
    
    # Check if we have enough players
    players = [tp.player for tp in tournament.players]
    if len(players) < tournament.group_count * 2:
        return False, f"Not enough players. Need at least {tournament.group_count * 2} players."
    
    # Delete existing groups
    Group.query.filter_by(tournament_id=tournament_id).delete()
    
    # Create new groups
    groups = []
    for i in range(tournament.group_count):
        group = Group(
            tournament_id=tournament_id,
            name=f"Group {chr(65+i)}"  # Group A, Group B, etc.
        )
        db.session.add(group)
        groups.append(group)
    
    # Flush to get group IDs
    db.session.flush()
    
    # Randomize player order for assignment
    tournament_players = TournamentPlayer.query.filter_by(tournament_id=tournament_id).all()
    random.shuffle(tournament_players)
    
    # Assign players to groups
    for i, tp in enumerate(tournament_players):
        group_index = i % tournament.group_count
        tp.group_id = groups[group_index].id
    
    # Update tournament status
    tournament.status = TournamentStatus.GROUP_STAGE
    
    db.session.commit()
    return True, "Groups created successfully"

def generate_group_matches(tournament_id):
    """Generate round-robin matches for each group"""
    tournament = Tournament.query.get(tournament_id)
    if not tournament:
        return False, "Tournament not found"
    
    # Delete any existing group matches
    Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.group_id != None
    ).delete()
    
    # Get all groups
    groups = Group.query.filter_by(tournament_id=tournament_id).all()
    
    # Start time for the first match
    start_time = tournament.start_date
    board_number = 1
    
    for group in groups:
        # Get players in this group
        tournament_players = TournamentPlayer.query.filter_by(group_id=group.id).all()
        players = [tp.player_id for tp in tournament_players]
        
        if len(players) < 2:
            continue
        
        # Round-robin tournament schedule generation
        if len(players) % 2 == 1:
            players.append(None)  # Add a bye if odd number of players
        
        n = len(players)
        rounds = n - 1
        half = n // 2
        
        for round_num in range(rounds):
            # Generate pairings for this round
            pairings = []
            for i in range(half):
                if i == 0 and players[n-1-i] is None:
                    continue  # Skip bye
                if players[i] is None or players[n-1-i] is None:
                    continue  # Skip bye
                
                # Alternate colors for fairness
                if round_num % 2 == 0:
                    white_id, black_id = players[i], players[n-1-i]
                else:
                    white_id, black_id = players[n-1-i], players[i]
                
                pairings.append((white_id, black_id))
            
            # Create match for each pairing
            for white_id, black_id in pairings:
                match = Match(
                    tournament_id=tournament_id,
                    group_id=group.id,
                    round=round_num + 1,
                    board_number=board_number,
                    white_player_id=white_id,
                    black_player_id=black_id,
                    start_time=start_time,
                    status=MatchStatus.SCHEDULED
                )
                db.session.add(match)
                
                # Increment board number
                board_number = board_number % 10 + 1
            
            # Next round starts 1 hour later
            start_time += timedelta(hours=1)
            
            # Rotate players for next round, keeping player 0 fixed
            players = [players[0]] + [players[-1]] + players[1:-1]
    
    db.session.commit()
    return True, "Group matches generated successfully"

def update_group_standings(tournament_id):
    """Update standings for all groups in a tournament"""
    tournament = Tournament.query.get(tournament_id)
    if not tournament:
        return False, "Tournament not found"
    
    # Get all groups
    groups = Group.query.filter_by(tournament_id=tournament_id).all()
    
    for group in groups:
        # Get all players in this group
        tournament_players = TournamentPlayer.query.filter_by(group_id=group.id).all()
        
        # Reset points
        for tp in tournament_players:
            tp.points = 0
            tp.tiebreak_score = 0
        
        # Get all completed matches in this group
        matches = Match.query.filter(
            Match.group_id == group.id,
            Match.status == MatchStatus.COMPLETED
        ).all()
        
        # Calculate points for each player
        for match in matches:
            if match.result == MatchResult.WHITE_WIN:
                white_score, black_score = 1, 0
            elif match.result == MatchResult.BLACK_WIN:
                white_score, black_score = 0, 1
            elif match.result == MatchResult.DRAW:
                white_score, black_score = 0.5, 0.5
            elif match.result == MatchResult.FORFEIT_WHITE:
                white_score, black_score = 0, 1
            elif match.result == MatchResult.FORFEIT_BLACK:
                white_score, black_score = 1, 0
            else:
                continue  # Skip if result is not set
            
            # Update player scores
            if match.white_player_id:
                white_tp = next((tp for tp in tournament_players if tp.player_id == match.white_player_id), None)
                if white_tp:
                    white_tp.points += white_score
            
            if match.black_player_id:
                black_tp = next((tp for tp in tournament_players if tp.player_id == match.black_player_id), None)
                if black_tp:
                    black_tp.points += black_score
        
        # Calculate tiebreak scores (could be Sonneborn-Berger, Buchholz, etc.)
        # Here we'll use a simple sum of opponents' scores
        for tp in tournament_players:
            white_matches = Match.query.filter(
                Match.group_id == group.id,
                Match.status == MatchStatus.COMPLETED,
                Match.white_player_id == tp.player_id
            ).all()
            
            black_matches = Match.query.filter(
                Match.group_id == group.id,
                Match.status == MatchStatus.COMPLETED,
                Match.black_player_id == tp.player_id
            ).all()
            
            # Sum up opponents' scores
            for match in white_matches:
                if match.black_player_id:
                    opp_tp = next((p for p in tournament_players if p.player_id == match.black_player_id), None)
                    if opp_tp:
                        tp.tiebreak_score += opp_tp.points
            
            for match in black_matches:
                if match.white_player_id:
                    opp_tp = next((p for p in tournament_players if p.player_id == match.white_player_id), None)
                    if opp_tp:
                        tp.tiebreak_score += opp_tp.points
    
    db.session.commit()
    return True, "Group standings updated successfully"

def select_knockout_players(tournament_id, player_ids=None):
    """Select players for knockout stage either automatically or manually"""
    tournament = Tournament.query.get(tournament_id)
    if not tournament:
        return False, "Tournament not found"
    
    if player_ids:
        # Manual selection
        if len(player_ids) != tournament.knockout_players:
            return False, f"Must select exactly {tournament.knockout_players} players"
        
        # Validate all players are in the tournament
        for player_id in player_ids:
            tp = TournamentPlayer.query.filter_by(
                tournament_id=tournament_id,
                player_id=player_id
            ).first()
            
            if not tp:
                return False, f"Player {player_id} not in tournament"
            
            # Set as not eliminated for knockout stage
            tp.eliminated = False
        
        # Set all other players as eliminated
        TournamentPlayer.query.filter(
            TournamentPlayer.tournament_id == tournament_id,
            ~TournamentPlayer.player_id.in_(player_ids)
        ).update({TournamentPlayer.eliminated: True}, synchronize_session=False)
        
    else:
        # Automatic selection based on group results
        groups = Group.query.filter_by(tournament_id=tournament_id).all()
        
        # Get top players from each group
        selected_players = []
        players_per_group = tournament.knockout_players // tournament.group_count
        remaining = tournament.knockout_players % tournament.group_count
        
        for group in groups:
            # Get players sorted by points then tiebreak
            group_players = TournamentPlayer.query.filter_by(group_id=group.id)\
                .order_by(TournamentPlayer.points.desc(), TournamentPlayer.tiebreak_score.desc())\
                .limit(players_per_group + (1 if remaining > 0 else 0))\
                .all()
            
            for tp in group_players:
                selected_players.append(tp.player_id)
            
            if remaining > 0:
                remaining -= 1
        
        # Set elimination status
        TournamentPlayer.query.filter(
            TournamentPlayer.tournament_id == tournament_id
        ).update({TournamentPlayer.eliminated: True}, synchronize_session=False)
        
        TournamentPlayer.query.filter(
            TournamentPlayer.tournament_id == tournament_id,
            TournamentPlayer.player_id.in_(selected_players)
        ).update({TournamentPlayer.eliminated: False}, synchronize_session=False)
    
    # Update tournament status
    tournament.status = TournamentStatus.KNOCKOUT_STAGE
    
    db.session.commit()
    return True, "Players selected for knockout stage"

def generate_knockout_matches(tournament_id):
    """Generate knockout stage matches including third place playoff"""
    tournament = Tournament.query.get(tournament_id)
    if not tournament:
        return False, "Tournament not found"
    
    # Delete any existing knockout matches
    Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.group_id == None
    ).delete()
    
    # Get qualified players
    qualified_tps = TournamentPlayer.query.filter_by(
        tournament_id=tournament_id,
        eliminated=False
    ).order_by(TournamentPlayer.points.desc(), TournamentPlayer.tiebreak_score.desc()).all()
    
    qualified_player_ids = [tp.player_id for tp in qualified_tps]
    
    if len(qualified_player_ids) != tournament.knockout_players:
        return False, f"Need exactly {tournament.knockout_players} players for knockout stage"
    
    # Determine the number of rounds needed
    player_count = len(qualified_player_ids)
    round_count = 0
    while 2**round_count < player_count:
        round_count += 1
    
    # Generate knockout bracket
    matches_by_round = {}
    
    # First round - seed the players
    first_round_match_count = 2**(round_count-1)
    seeds = create_seeded_bracket(qualified_player_ids)
    
    start_time = tournament.start_date + timedelta(days=1)  # Day after group stage
    board_number = 1
    
    # Create all rounds of matches
    for round_num in range(1, round_count + 1):
        round_name = get_round_name(round_num, round_count)
        match_count_in_round = 2**(round_count - round_num)
        matches_by_round[round_num] = []
        
        for match_num in range(1, match_count_in_round + 1):
            match = Match(
                tournament_id=tournament_id,
                group_id=None,  # Knockout match
                round=round_num,
                knockout_round=round_name,
                knockout_match_num=match_num,
                board_number=board_number,
                start_time=start_time + timedelta(hours=round_num-1),
                status=MatchStatus.SCHEDULED
            )
            
            # Only assign players to first round
            if round_num == 1:
                seed_idx = match_num - 1
                if seed_idx*2 < len(seeds):
                    match.white_player_id = seeds[seed_idx*2]
                if seed_idx*2+1 < len(seeds):
                    match.black_player_id = seeds[seed_idx*2+1]
            
            board_number = board_number % 10 + 1
            db.session.add(match)
            matches_by_round[round_num].append(match)
    
    # Flush to get match IDs
    db.session.flush()
    
    # Set up next_match relationships
    for round_num in range(1, round_count):
        matches_in_round = matches_by_round[round_num]
        matches_in_next_round = matches_by_round[round_num + 1]
        
        for i, match in enumerate(matches_in_round):
            next_match_idx = i // 2
            if next_match_idx < len(matches_in_next_round):
                match.next_match_id = matches_in_next_round[next_match_idx].id
    
    db.session.commit()
    return True, "Knockout matches generated successfully"

def advance_knockout_player(match_id):
    """Advance the winner of a knockout match to the next match"""
    match = Match.query.get(match_id)
    if not match:
        return False, "Match not found"
    
    if match.status != MatchStatus.COMPLETED:
        return False, "Match not completed yet"
    
    winner_id = match.get_winner_id()
    if not winner_id:
        return False, "No winner determined"
    
    # Gestione speciale per le semifinali
    if match.knockout_round == "semifinal":
        # Trova la finale esistente o creane una nuova
        final_match = Match.query.filter_by(
            tournament_id=match.tournament_id,
            knockout_round="final"
        ).first()
        
        if not final_match:
            # Crea un nuovo match per la finale
            final_match = Match(
                tournament_id=match.tournament_id,
                round=match.round + 1,
                knockout_round="final",
                knockout_match_num=1,
                status=MatchStatus.SCHEDULED,
                start_time=match.start_time + timedelta(hours=1)
            )
            db.session.add(final_match)
        
        # Trova tutte le semifinali
        semifinal_matches = Match.query.filter_by(
            tournament_id=match.tournament_id,
            knockout_round="semifinal"
        ).order_by(Match.knockout_match_num).all()
        
        # Determina la posizione del vincitore (bianco/nero) nella finale
        is_first_semifinal = semifinal_matches[0].id == match.id
        
        if is_first_semifinal:
            final_match.white_player_id = winner_id
        else:
            final_match.black_player_id = winner_id
            
        # Se entrambi i giocatori sono stati assegnati, imposta lo stato su SCHEDULED
        if final_match.white_player_id and final_match.black_player_id:
            final_match.status = MatchStatus.SCHEDULED
            
        db.session.flush()
    
    elif match.next_match_id:
        # Gestione normale per altri turni
        next_match = Match.query.get(match.next_match_id)
        if not next_match:
            return False, "Next match not found"
        
        prev_matches = Match.query.filter_by(next_match_id=next_match.id).order_by(Match.id).all()
        match_index = prev_matches.index(match)
        
        if match_index % 2 == 0:
            next_match.white_player_id = winner_id
        else:
            next_match.black_player_id = winner_id
    
    db.session.commit()
    return True, "Winner advanced to next match"

def get_round_name(round_num, total_rounds):
    """Get the name of a knockout round (e.g., 'quarterfinal', 'semifinal', 'final')"""
    if round_num == total_rounds:
        return "final"
    elif round_num == total_rounds - 1:
        return "semifinal"
    elif round_num == total_rounds - 2:
        return "quarterfinal"
    else:
        return f"round_{round_num}"

def create_seeded_bracket(player_ids):
    """Create a seeded bracket for knockout stage"""
    # Basic implementation - could be more sophisticated
    player_count = len(player_ids)
    bracket_size = 1
    while bracket_size < player_count:
        bracket_size *= 2
    
    # Create the bracket with "byes" (None values) as needed
    seeds = player_ids + [None] * (bracket_size - player_count)
    
    # Apply standard tournament seeding
    result = []
    for i in range(bracket_size // 2):
        result.append(seeds[i])
        result.append(seeds[bracket_size - 1 - i] if i < len(seeds) // 2 else None)
    
    return result

def complete_tournament(tournament_id):
    """Mark tournament as completed"""
    tournament = Tournament.query.get(tournament_id)
    if not tournament:
        return False, "Tournament not found"
    
    # Check if all matches are completed
    incomplete_matches = Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.status != MatchStatus.COMPLETED,
        Match.status != MatchStatus.CANCELLED
    ).count()
    
    if incomplete_matches > 0:
        return False, f"There are {incomplete_matches} incomplete matches"
    
    tournament.status = TournamentStatus.COMPLETED
    tournament.end_date = datetime.now()
    
    db.session.commit()
    return True, "Tournament marked as completed"
