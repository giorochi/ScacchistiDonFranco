from flask import render_template, redirect, url_for, flash, request, jsonify, session, abort
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app import app, db
from models import Admin, Player, Tournament, TournamentPlayer, Group, Match, TournamentStatus, MatchStatus, MatchResult
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
    
    # Get player's tournaments
    tournament_players = TournamentPlayer.query.filter_by(player_id=current_user.id).all()
    tournaments = [tp.tournament for tp in tournament_players]
    
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
        if match.result == MatchResult.WHITE_WIN and match.white_player_id == current_user.id:
            wins += 1
        elif match.result == MatchResult.BLACK_WIN and match.black_player_id == current_user.id:
            wins += 1
        elif match.result == MatchResult.WHITE_WIN and match.black_player_id == current_user.id:
            losses += 1
        elif match.result == MatchResult.BLACK_WIN and match.white_player_id == current_user.id:
            losses += 1
        elif match.result == MatchResult.DRAW:
            draws += 1
        elif match.result == MatchResult.FORFEIT_WHITE and match.black_player_id == current_user.id:
            wins += 1
        elif match.result == MatchResult.FORFEIT_BLACK and match.white_player_id == current_user.id:
            wins += 1
        elif match.result == MatchResult.FORFEIT_WHITE and match.white_player_id == current_user.id:
            losses += 1
        elif match.result == MatchResult.FORFEIT_BLACK and match.black_player_id == current_user.id:
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
    
    return render_template('player_dashboard.html', 
                          player=current_user,
                          tournaments=tournaments,
                          upcoming_matches=upcoming_matches,
                          past_matches=past_matches,
                          stats=stats)

@app.route('/tournament/<int:tournament_id>')
def tournament_view(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Get groups and standings
    groups = Group.query.filter_by(tournament_id=tournament_id).all()
    group_standings = {}
    
    for group in groups:
        players = TournamentPlayer.query.filter_by(group_id=group.id)\
            .order_by(TournamentPlayer.points.desc(), TournamentPlayer.tiebreak_score.desc()).all()
        group_standings[group.id] = players
    
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

def get_all_players():
    return Player.query.order_by(Player.name).all()

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
        
        if not name or not start_date or not end_date:
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
            knockout_players=knockout_players
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
