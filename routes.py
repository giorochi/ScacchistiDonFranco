from flask import render_template, redirect, url_for, flash, request, jsonify, session, abort
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app import app, db
from models import Admin, Player, Tournament, TournamentPlayer, Group, Match, Chessboard, TournamentStatus, MatchStatus, MatchResult
import tournament_logic
from datetime import datetime
import string
import random
import json

# Root route
@app.route('/')
def index():
    tournaments = Tournament.query.order_by(Tournament.start_date.desc()).limit(5).all()
    return render_template('index.html', tournaments=tournaments)

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403

# Authentication routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if hasattr(current_user, 'username'):  # Admin
            return redirect(url_for('admin_dashboard'))
        else:  # Player
            return redirect(url_for('player_dashboard'))

    if request.method == 'POST':
        # First check if it's an admin login
        username = request.form.get('username')
        password = request.form.get('password')

        if username and password:
            admin = Admin.query.filter_by(username=username).first()
            if admin and admin.check_password(password):
                login_user(admin)
                next_page = request.args.get('next')
                return redirect(next_page or url_for('admin_dashboard'))
            else:
                flash('Invalid username or password', 'danger')
        else:
            # Try player access code login
            access_code = request.form.get('access_code')
            if access_code:
                player = Player.query.filter_by(access_code=access_code).first()
                if player:
                    login_user(player)
                    next_page = request.args.get('next')
                    return redirect(next_page or url_for('player_dashboard'))
                else:
                    flash('Invalid access code', 'danger')
            else:
                flash('Please enter login credentials', 'warning')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))

# Player routes
@app.route('/player/dashboard')
@login_required
def player_dashboard():
    if hasattr(current_user, 'username'):  # Admin check
        return redirect(url_for('admin_dashboard'))

    # Get player's tournaments and tournament players
    tournament_players_list = TournamentPlayer.query.filter_by(player_id=current_user.id).all()
    tournaments = [tp.tournament for tp in tournament_players_list]
    
    # Create a dictionary of tournament_id -> tournament_player for easy access
    tournament_players = {tp.tournament_id: tp for tp in tournament_players_list}
    
    # Get group standings for each tournament
    group_standings = {}
    
    for tp in tournament_players_list:
        if tp.group_id:
            # Get all players in this group
            players_in_group = TournamentPlayer.query.filter_by(
                group_id=tp.group_id
            ).order_by(TournamentPlayer.points.desc(), TournamentPlayer.tiebreak_score.desc()).all()
            
            group_standings[tp.tournament_id] = players_in_group

    # Get upcoming matches
    upcoming_matches = Match.query.filter(
        (Match.white_player_id == current_user.id) | (Match.black_player_id == current_user.id),
        Match.status.in_([MatchStatus.SCHEDULED, MatchStatus.IN_PROGRESS])
    ).order_by(Match.start_time).all()

    # Get completed matches
    past_matches = Match.query.filter(
        (Match.white_player_id == current_user.id) | (Match.black_player_id == current_user.id),
        Match.status == MatchStatus.COMPLETED
    ).order_by(Match.start_time.desc()).all()

    # Calculate statistics
    wins = 0
    losses = 0
    draws = 0

    for match in past_matches:
        if not match.result:
            continue
            
        if match.result == MatchResult.DRAW:
            draws += 1
        elif match.white_player_id == current_user.id:
            if match.result in [MatchResult.WHITE_WIN, MatchResult.FORFEIT_BLACK]:
                wins += 1
            elif match.result in [MatchResult.BLACK_WIN, MatchResult.FORFEIT_WHITE]:
                losses += 1
        elif match.black_player_id == current_user.id:
            if match.result in [MatchResult.BLACK_WIN, MatchResult.FORFEIT_WHITE]:
                wins += 1
            elif match.result in [MatchResult.WHITE_WIN, MatchResult.FORFEIT_BLACK]:
                losses += 1

    total_matches = wins + losses + draws
    win_percentage = (wins / total_matches * 100) if total_matches > 0 else 0

    stats = {
        'wins': wins,
        'losses': losses,
        'draws': draws,
        'total': total_matches,
        'win_percentage': win_percentage
    }
    
    # Function to get player matches count for tournament standings
    def get_player_matches(tournament_id, player_id):
        return Match.query.filter(
            Match.tournament_id == tournament_id,
            (Match.white_player_id == player_id) | (Match.black_player_id == player_id),
            Match.status == MatchStatus.COMPLETED
        ).all()
    
    return render_template('player_dashboard.html', 
                          player=current_user,
                          tournaments=tournaments,
                          tournament_players=tournament_players,
                          upcoming_matches=upcoming_matches,
                          past_matches=past_matches,
                          group_standings=group_standings,
                          get_player_matches=get_player_matches,
                          stats=stats)

@app.route('/tournament/<int:tournament_id>')
def tournament_view(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)

    # Get groups and standings
    groups = Group.query.filter_by(tournament_id=tournament_id).all()
    group_standings = {}
    group_matches = {}

    for group in groups:
        players = TournamentPlayer.query.filter_by(group_id=group.id)\
            .order_by(TournamentPlayer.points.desc(), TournamentPlayer.tiebreak_score.desc()).all()
        group_standings[group.id] = players
        
        # Get matches for this group
        matches = Match.query.filter_by(
            tournament_id=tournament_id,
            group_id=group.id
        ).order_by(Match.round).all()
        group_matches[group.id] = matches

    # Get knockout matches if in knockout stage
    knockout_matches = None
    if tournament.status in [TournamentStatus.KNOCKOUT_STAGE, TournamentStatus.COMPLETED]:
        knockout_matches = Match.query.filter(
            Match.tournament_id == tournament_id,
            Match.group_id == None
        ).order_by(Match.round, Match.knockout_match_num).all()

    return render_template('tournament_view.html', 
                          tournament=tournament,
                          groups=groups,
                          group_standings=group_standings,
                          group_matches=group_matches,
                          knockout_matches=knockout_matches)

# Admin routes
@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    # Get active tournaments
    active_tournaments = Tournament.query.filter(
        Tournament.status.in_([TournamentStatus.GROUP_STAGE, TournamentStatus.KNOCKOUT_STAGE])
    ).order_by(Tournament.start_date).all()

    # Get upcoming tournaments
    upcoming_tournaments = Tournament.query.filter_by(
        status=TournamentStatus.DRAFT
    ).order_by(Tournament.start_date).all()

    # Get completed tournaments
    completed_tournaments = Tournament.query.filter_by(
        status=TournamentStatus.COMPLETED
    ).order_by(Tournament.start_date.desc()).all()

    # Get recent matches
    recent_matches = Match.query.filter_by(
        status=MatchStatus.COMPLETED
    ).order_by(Match.start_time.desc()).limit(10).all()

    # Get player count
    player_count = Player.query.count()

    return render_template('admin/dashboard.html',
                          active_tournaments=active_tournaments,
                          upcoming_tournaments=upcoming_tournaments,
                          completed_tournaments=completed_tournaments,
                          recent_matches=recent_matches,
                          player_count=player_count)

@app.route('/admin/tournaments')
@login_required
def admin_tournaments():
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    tournaments = Tournament.query.order_by(Tournament.start_date.desc()).all()
    return render_template('admin/tournaments.html', tournaments=tournaments)

@app.context_processor
def utility_processor():
    def get_all_players():
        return Player.query.order_by(Player.name).all()
    def now():
        return datetime.now()
    return dict(get_all_players=get_all_players, now=now)

@app.route('/admin/tournament/<int:tournament_id>')
@login_required
def admin_tournament_detail(tournament_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    tournament = Tournament.query.get_or_404(tournament_id)

    # Get registered players
    tournament_players = TournamentPlayer.query.filter_by(tournament_id=tournament_id).all()

    # Get groups if in group stage
    groups = None
    group_standings = None
    if tournament.status in [TournamentStatus.GROUP_STAGE, TournamentStatus.KNOCKOUT_STAGE, TournamentStatus.COMPLETED]:
        groups = Group.query.filter_by(tournament_id=tournament_id).all()

        group_standings = {}
        for group in groups:
            players = TournamentPlayer.query.filter_by(group_id=group.id)\
                .order_by(TournamentPlayer.points.desc(), TournamentPlayer.tiebreak_score.desc()).all()
            group_standings[group.id] = players

    # Get group matches
    group_matches = Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.group_id != None
    ).order_by(Match.group_id, Match.round).all()

    # Get knockout matches
    knockout_matches = Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.group_id == None
    ).order_by(Match.round, Match.knockout_match_num).all()

    return render_template('admin/tournament_detail.html',
                          tournament=tournament,
                          tournament_players=tournament_players,
                          groups=groups,
                          group_standings=group_standings,
                          group_matches=group_matches,
                          knockout_matches=knockout_matches)

@app.route('/admin/tournament/new', methods=['GET', 'POST'])
@login_required
def admin_tournament_new():
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        location = request.form.get('location')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        group_count = int(request.form.get('group_count', 4))
        players_per_group = int(request.form.get('players_per_group', 4))
        knockout_players = int(request.form.get('knockout_players', 8))
        board_count = int(request.form.get('board_count', 10))

        if not name or not start_date or not end_date or not board_count:
            flash('Please fill all required fields', 'danger')
            return redirect(url_for('admin_tournament_new'))

        try:
            start_date = datetime.strptime(start_date, '%Y-%m-%d')
            end_date = datetime.strptime(end_date, '%Y-%m-%d')
        except ValueError:
            flash('Invalid date format', 'danger')
            return redirect(url_for('admin_tournament_new'))

        tournament = Tournament(
            name=name,
            description=description,
            location=location,
            start_date=start_date,
            end_date=end_date,
            status=TournamentStatus.DRAFT,
            group_count=group_count,
            players_per_group=players_per_group,
            knockout_players=knockout_players,
            board_count=board_count
        )

        db.session.add(tournament)
        db.session.commit()

        flash(f'Tournament "{name}" created successfully', 'success')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament.id))

    return render_template('admin/tournaments.html', creating=True)

@app.route('/admin/tournament/<int:tournament_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_tournament_edit(tournament_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    tournament = Tournament.query.get_or_404(tournament_id)

    if request.method == 'POST':
        tournament.name = request.form.get('name')
        tournament.description = request.form.get('description')
        tournament.location = request.form.get('location')

        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')

        try:
            tournament.start_date = datetime.strptime(start_date, '%Y-%m-%d')
            tournament.end_date = datetime.strptime(end_date, '%Y-%m-%d')
        except ValueError:
            flash('Invalid date format', 'danger')
            return redirect(url_for('admin_tournament_edit', tournament_id=tournament_id))

        tournament.group_count = int(request.form.get('group_count', 4))
        tournament.players_per_group = int(request.form.get('players_per_group', 4))
        tournament.knockout_players = int(request.form.get('knockout_players', 8))

        db.session.commit()

        flash('Tournament updated successfully', 'success')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament.id))

    return render_template('admin/tournament_detail.html', 
                          tournament=tournament, 
                          editing=True)

@app.route('/admin/tournament/<int:tournament_id>/delete', methods=['POST'])
@login_required
def admin_tournament_delete(tournament_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    tournament = Tournament.query.get_or_404(tournament_id)

    # Delete associated records (cascading is set up in models)
    db.session.delete(tournament)
    db.session.commit()

    flash('Tournament deleted successfully', 'success')
    return redirect(url_for('admin_tournaments'))

@app.route('/admin/players')
@login_required
def admin_players():
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    players = Player.query.order_by(Player.name).all()
    return render_template('admin/players.html', players=players)

@app.route('/admin/player/new', methods=['GET', 'POST'])
@login_required
def admin_player_new():
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        rating = request.form.get('rating')

        if not name:
            flash('Player name is required', 'danger')
            return redirect(url_for('admin_player_new'))

        # Generate unique access code
        access_code = Player.generate_access_code()

        player = Player(
            name=name,
            email=email,
            phone=phone,
            access_code=access_code,
            rating=rating if rating else None
        )

        db.session.add(player)
        db.session.commit()

        flash(f'Player "{name}" created successfully with access code: {access_code}', 'success')
        return redirect(url_for('admin_players'))

    return render_template('admin/players.html', creating=True)

@app.route('/admin/player/<int:player_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_player_edit(player_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    player = Player.query.get_or_404(player_id)

    if request.method == 'POST':
        player.name = request.form.get('name')
        player.email = request.form.get('email')
        player.phone = request.form.get('phone')
        rating = request.form.get('rating')
        player.rating = rating if rating else None

        db.session.commit()

        flash('Player updated successfully', 'success')
        return redirect(url_for('admin_players'))

    return render_template('admin/players.html', player=player, editing=True)

@app.route('/admin/player/<int:player_id>/delete', methods=['POST'])
@login_required
def admin_player_delete(player_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    player = Player.query.get_or_404(player_id)

    # Delete player (cascading is set up in models)
    db.session.delete(player)
    db.session.commit()

    flash('Player deleted successfully', 'success')
    return redirect(url_for('admin_players'))

@app.route('/admin/tournament/<int:tournament_id>/add_player', methods=['POST'])
@login_required
def admin_tournament_add_player(tournament_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    tournament = Tournament.query.get_or_404(tournament_id)
    player_id = request.form.get('player_id')

    if not player_id:
        flash('Player ID is required', 'danger')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))

    # Check if player is already in tournament
    existing = TournamentPlayer.query.filter_by(
        tournament_id=tournament_id,
        player_id=player_id
    ).first()

    if existing:
        flash('Player is already in tournament', 'warning')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))

    # Add player to tournament
    tournament_player = TournamentPlayer(
        tournament_id=tournament_id,
        player_id=player_id
    )

    db.session.add(tournament_player)
    db.session.commit()

    flash('Player added to tournament successfully', 'success')
    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))

@app.route('/admin/tournament/<int:tournament_id>/remove_player/<int:player_id>', methods=['POST'])
@login_required
def admin_tournament_remove_player(tournament_id, player_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    # Find the tournament player
    tournament_player = TournamentPlayer.query.filter_by(
        tournament_id=tournament_id,
        player_id=player_id
    ).first_or_404()

    # Delete related matches
    Match.query.filter(
        Match.tournament_id == tournament_id,
        (Match.white_player_id == player_id) | (Match.black_player_id == player_id)
    ).delete()

    # Remove player from tournament
    db.session.delete(tournament_player)
    db.session.commit()

    flash('Player removed from tournament successfully', 'success')
    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))

@app.route('/admin/tournament/<int:tournament_id>/create_groups', methods=['POST'])
@login_required
def admin_tournament_create_groups(tournament_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    success, message = tournament_logic.create_groups(tournament_id)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')

    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))

@app.route('/admin/tournament/<int:tournament_id>/generate_matches', methods=['POST'])
@login_required
def admin_tournament_generate_matches(tournament_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    success, message = tournament_logic.generate_group_matches(tournament_id)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')

    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))

@app.route('/admin/tournament/<int:tournament_id>/update_standings', methods=['POST'])
@login_required
def admin_tournament_update_standings(tournament_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    success, message = tournament_logic.update_group_standings(tournament_id)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')

    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))

@app.route('/admin/tournament/<int:tournament_id>/select_knockout', methods=['POST'])
@login_required
def admin_tournament_select_knockout(tournament_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    # If player_ids provided, use manual selection
    player_ids = request.form.getlist('player_ids')
    if player_ids:
        player_ids = [int(pid) for pid in player_ids]
        success, message = tournament_logic.select_knockout_players(tournament_id, player_ids)
    else:
        # Otherwise use automatic selection
        success, message = tournament_logic.select_knockout_players(tournament_id)

    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')

    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))

@app.route('/admin/tournament/<int:tournament_id>/generate_knockout', methods=['POST'])
@login_required
def admin_tournament_generate_knockout(tournament_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    success, message = tournament_logic.generate_knockout_matches(tournament_id)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')

    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))

@app.route('/admin/match/<int:match_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_match_edit(match_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    match = Match.query.get_or_404(match_id)

    if request.method == 'POST':
        # Update match details
        result = request.form.get('result')
        status = request.form.get('status')
        board_number = request.form.get('board_number')
        start_time = request.form.get('start_time')
        notes = request.form.get('notes')

        match.result = result
        match.status = status
        match.board_number = int(board_number) if board_number else None
        match.notes = notes

        if start_time:
            try:
                match.start_time = datetime.strptime(start_time, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('Invalid date/time format', 'danger')
                return redirect(url_for('admin_match_edit', match_id=match_id))

        # Set scores based on result
        if result == MatchResult.WHITE_WIN:
            match.white_score = 1.0
            match.black_score = 0.0
        elif result == MatchResult.BLACK_WIN:
            match.white_score = 0.0
            match.black_score = 1.0
        elif result == MatchResult.DRAW:
            match.white_score = 0.5
            match.black_score = 0.5
        elif result == MatchResult.FORFEIT_WHITE:
            match.white_score = 0.0
            match.black_score = 1.0
        elif result == MatchResult.FORFEIT_BLACK:
            match.white_score = 1.0
            match.black_score = 0.0

        db.session.commit()

        # If match is completed, update standings and advance player if knockout match
        if status == MatchStatus.COMPLETED:
            tournament_logic.update_group_standings(match.tournament_id)

            # If knockout match and has a next match, advance the winner
            if match.group_id is None and match.next_match_id:
                tournament_logic.advance_knockout_player(match.id)

        flash('Match updated successfully', 'success')
        return redirect(url_for('admin_tournament_detail', tournament_id=match.tournament_id))

    return render_template('admin/matches.html', match=match)

@app.route('/admin/tournament/<int:tournament_id>/complete', methods=['POST'])
@login_required
def admin_tournament_complete(tournament_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)

    success, message = tournament_logic.complete_tournament(tournament_id)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')

    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))

@app.route('/admin/tournament/<int:tournament_id>/player_codes')
@login_required
def admin_tournament_player_codes(tournament_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)
        
    tournament = Tournament.query.get_or_404(tournament_id)
    tournament_players = TournamentPlayer.query.filter_by(tournament_id=tournament_id).join(
        Player, TournamentPlayer.player_id == Player.id
    ).order_by(Player.name).all()
    
    return render_template('admin/player_codes.html',
                          tournament=tournament,
                          tournament_players=tournament_players)

# First time setup - create admin if none exists
@app.route('/setup', methods=['GET', 'POST'])
def setup():
    # Check if any admin exists
    admin_exists = Admin.query.first() is not None

    if admin_exists:
        flash('Setup already completed', 'info')
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        email = request.form.get('email')

        if not username or not password or not email:
            flash('All fields are required', 'danger')
            return redirect(url_for('setup'))

        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return redirect(url_for('setup'))

        admin = Admin(username=username, email=email)
        admin.set_password(password)

        db.session.add(admin)
        db.session.commit()

        flash('Admin account created successfully', 'success')
        return redirect(url_for('login'))

    return render_template('setup.html')


# Chessboard routes
@app.route('/chessboard/<code>')
def chessboard_view(code):
    chessboard = Chessboard.query.filter_by(access_code=code).first_or_404()
    tournament = chessboard.tournament
    
    # Find active match for this board
    match = Match.query.filter_by(
        chessboard_id=chessboard.id,
        status=MatchStatus.IN_PROGRESS
    ).first()
    
    if not match:
        # Find scheduled match
        match = Match.query.filter_by(
            chessboard_id=chessboard.id,
            status=MatchStatus.SCHEDULED
        ).first()
    
    # Set last used timestamp
    chessboard.last_used = datetime.now()
    db.session.commit()
    
    return render_template('chessboard.html', 
                         chessboard=chessboard,
                         tournament=tournament,
                         match=match,
                         display_mode=chessboard.display_mode)

@app.route('/chessboard/<code>/start_match', methods=['POST'])
def chessboard_start_match(code):
    chessboard = Chessboard.query.filter_by(access_code=code).first_or_404()
    
    # Find scheduled match for this board
    match = Match.query.filter_by(
        chessboard_id=chessboard.id,
        status=MatchStatus.SCHEDULED
    ).first()
    
    if not match:
        flash('No scheduled match found for this board', 'danger')
        return redirect(url_for('chessboard_view', code=code))
    
    # Update match status
    match.status = MatchStatus.IN_PROGRESS
    match.start_time = datetime.now()
    
    db.session.commit()
    
    flash('Partita avviata!', 'success')
    return redirect(url_for('chessboard_view', code=code))

@app.route('/chessboard/<code>/submit_result', methods=['POST'])
def chessboard_submit_result(code):
    chessboard = Chessboard.query.filter_by(access_code=code).first_or_404()
    
    # Find active match for this board
    match = Match.query.filter_by(
        chessboard_id=chessboard.id,
        status=MatchStatus.IN_PROGRESS
    ).first()
    
    if not match:
        flash('No active match found for this board', 'danger')
        return redirect(url_for('chessboard_view', code=code))
    
    result = request.form.get('result')
    notes = request.form.get('notes')
    
    if not result:
        flash('Please select a result', 'danger')
        return redirect(url_for('chessboard_view', code=code))
    
    # Update match result
    match.result = result
    match.notes = notes
    match.status = MatchStatus.COMPLETED
    
    # Set scores based on result
    if result == MatchResult.WHITE_WIN or result == MatchResult.FORFEIT_BLACK:
        match.white_score = 1.0
        match.black_score = 0.0
    elif result == MatchResult.BLACK_WIN or result == MatchResult.FORFEIT_WHITE:
        match.white_score = 0.0
        match.black_score = 1.0
    elif result == MatchResult.DRAW:
        match.white_score = 0.5
        match.black_score = 0.5
    else:  # No show
        match.white_score = 0.0
        match.black_score = 0.0
    
    db.session.commit()
    
    # Update tournament standings
    if match.group_id:  # Group stage match
        tournament_logic.update_group_standings(match.tournament_id)
    elif match.knockout_round:  # Knockout stage match
        tournament_logic.advance_knockout_player(match.id)
    
    flash('Risultato registrato con successo!', 'success')
    return redirect(url_for('chessboard_view', code=code))

# Admin chessboard management routes
@app.route('/admin/tournament/<int:tournament_id>/chessboards')
@login_required
def admin_tournament_chessboards(tournament_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)
    
    tournament = Tournament.query.get_or_404(tournament_id)
    chessboards = Chessboard.query.filter_by(tournament_id=tournament_id).order_by(Chessboard.board_number).all()
    matches = Match.query.filter_by(tournament_id=tournament_id).all()
    
    return render_template('admin/chessboards.html',
                          tournament=tournament,
                          chessboards=chessboards,
                          matches=matches)

@app.route('/admin/tournament/<int:tournament_id>/create_chessboards', methods=['POST'])
@login_required
def admin_tournament_create_chessboards(tournament_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)
    
    tournament = Tournament.query.get_or_404(tournament_id)
    board_count = int(request.form.get('board_count', tournament.board_count))
    reset_existing = request.form.get('reset_existing') == '1'
    
    # Update tournament board count
    tournament.board_count = board_count
    
    if reset_existing:
        # Delete existing chessboards
        Chessboard.query.filter_by(tournament_id=tournament_id).delete()
    
    # Create new chessboards if needed
    existing_boards = Chessboard.query.filter_by(tournament_id=tournament_id).count()
    
    for i in range(existing_boards + 1, board_count + 1):
        board = Chessboard(
            tournament_id=tournament_id,
            board_number=i,
            access_code=Chessboard.generate_access_code(),
            display_mode='single',
            is_active=True
        )
        db.session.add(board)
    
    db.session.commit()
    
    flash(f'Scacchiere generate con successo: {board_count}', 'success')
    return redirect(url_for('admin_tournament_chessboards', tournament_id=tournament_id))

@app.route('/admin/tournament/<int:tournament_id>/assign_matches', methods=['POST'])
@login_required
def admin_tournament_assign_matches(tournament_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)
    
    tournament = Tournament.query.get_or_404(tournament_id)
    round_value = request.form.get('round')
    auto_assign = request.form.get('auto_assign') == '1'
    show_next_round = request.form.get('show_next_round') == '1'
    
    if not round_value:
        flash('Seleziona un turno', 'warning')
        return redirect(url_for('admin_tournament_chessboards', tournament_id=tournament_id))
    
    # Get active chessboards
    chessboards = Chessboard.query.filter_by(
        tournament_id=tournament_id,
        is_active=True
    ).order_by(Chessboard.board_number).all()
    
    if not chessboards:
        flash('No active chessboards available', 'warning')
        return redirect(url_for('admin_tournament_chessboards', tournament_id=tournament_id))
    
    # Get matches for the selected round
    if round_value.isdigit():
        # Group stage round
        matches = Match.query.filter_by(
            tournament_id=tournament_id,
            round=int(round_value),
            status=MatchStatus.SCHEDULED
        ).order_by(Match.group_id).all()
    else:
        # Knockout round
        matches = Match.query.filter_by(
            tournament_id=tournament_id,
            knockout_round=round_value,
            status=MatchStatus.SCHEDULED
        ).order_by(Match.knockout_match_num).all()
    
    if not matches:
        flash('No matches found for the selected round', 'warning')
        return redirect(url_for('admin_tournament_chessboards', tournament_id=tournament_id))
    
    # Clear any previous assignments for these matches
    for match in matches:
        match.chessboard_id = None
        match.show_next_round = show_next_round
    
    if auto_assign:
        # Auto assign matches to boards
        for i, match in enumerate(matches):
            if i < len(chessboards):
                match.chessboard_id = chessboards[i].id
            else:
                break
    
    db.session.commit()
    
    flash(f'Partite assegnate alle scacchiere: {min(len(matches), len(chessboards))}', 'success')
    return redirect(url_for('admin_tournament_chessboards', tournament_id=tournament_id))

@app.route('/admin/match/<int:match_id>/assign_board', methods=['POST'])
@login_required
def admin_match_assign_board(match_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)
    
    match = Match.query.get_or_404(match_id)
    chessboard_id = request.form.get('chessboard_id')
    
    if not chessboard_id:
        flash('Please select a chessboard', 'warning')
        return redirect(url_for('admin_tournament_chessboards', tournament_id=match.tournament_id))
    
    # Assign match to board
    match.chessboard_id = chessboard_id
    db.session.commit()
    
    flash('Match assigned to chessboard successfully', 'success')
    return redirect(url_for('admin_tournament_chessboards', tournament_id=match.tournament_id))

@app.route('/admin/chessboard/<int:board_id>/toggle-display-mode', methods=['POST'])
@login_required
def admin_chessboard_toggle_display_mode(board_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)
    
    board = Chessboard.query.get_or_404(board_id)
    
    # Toggle display mode between single and double
    board.display_mode = 'double' if board.display_mode == 'single' else 'single'
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/admin/chessboard/<int:board_id>/toggle-active', methods=['POST'])
@login_required
def admin_chessboard_toggle_active(board_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)
    
    board = Chessboard.query.get_or_404(board_id)
    
    # Toggle active status
    board.is_active = not board.is_active
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/admin/chessboard/<int:board_id>/regenerate-code', methods=['POST'])
@login_required
def admin_chessboard_regenerate_code(board_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)
    
    board = Chessboard.query.get_or_404(board_id)
    
    # Generate new access code
    board.access_code = Chessboard.generate_access_code()
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/admin/chessboard/<int:board_id>/delete', methods=['POST'])
@login_required
def admin_chessboard_delete(board_id):
    # Check if user is admin
    if not hasattr(current_user, 'username'):
        abort(403)
    
    board = Chessboard.query.get_or_404(board_id)
    
    # Clear chessboard_id from associated matches
    Match.query.filter_by(chessboard_id=board_id).update({Match.chessboard_id: None})
    
    # Delete the chessboard
    db.session.delete(board)
    db.session.commit()
    
    return jsonify({'success': True})