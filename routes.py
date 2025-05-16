import os
import random
import string
import uuid
from datetime import datetime, timedelta
from functools import wraps
from time import strptime
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from flask import (render_template, request, redirect, url_for, flash, 
                   session, jsonify, abort, send_from_directory)
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func, and_, desc, asc
from sqlalchemy.exc import SQLAlchemyError

from app import app, db, login_manager
from models import (Admin, Player, Tournament, TournamentPlayer, Group,
                    TournamentStatus, Match, MatchResult, MatchStatus,
                    Chessboard, PhotoCategory, TournamentPhoto)
from tournament_logic import (create_groups, generate_group_matches,
                              update_group_standings, select_knockout_players,
                              generate_knockout_matches, advance_knockout_player,
                              complete_tournament, assign_board_numbers)

login_manager.login_view = 'login'

# Cache tournaments for navigation
_tournaments_cache = None
_tournaments_cache_time = None

def get_tournaments():
    global _tournaments_cache, _tournaments_cache_time
    now = datetime.now()
    
    # Use cached tournaments if available and less than 5 minutes old
    if _tournaments_cache and _tournaments_cache_time and (now - _tournaments_cache_time).total_seconds() < 300:
        return _tournaments_cache
    
    # Otherwise refresh cache
    tournaments = Tournament.query.order_by(desc(Tournament.start_date)).all()
    _tournaments_cache = tournaments
    _tournaments_cache_time = now
    return tournaments

# Helper for admin routes
def admin_login_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        # Check if current user is an admin
        if not hasattr(current_user, 'username'):
            flash('Accesso non autorizzato.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


# Home page
@app.route('/')
def index():
    active_tournaments = Tournament.query.filter(
        Tournament.status != TournamentStatus.COMPLETED
    ).order_by(desc(Tournament.start_date)).limit(5).all()
    
    completed_tournaments = Tournament.query.filter_by(
        status=TournamentStatus.COMPLETED
    ).order_by(desc(Tournament.end_date)).limit(5).all()
    
    return render_template('index.html', 
                           active_tournaments=active_tournaments,
                           completed_tournaments=completed_tournaments)


# Tournament statistics
@app.route('/statistics')
def tournament_statistics():
    tournaments = Tournament.query.order_by(Tournament.start_date.desc()).all()
    return render_template('tournament_statistics.html', tournaments=tournaments)


@app.route('/api/tournament/<int:tournament_id>/stats')
def tournament_stats_api(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Get all players for tournament
    players = db.session.query(
        TournamentPlayer.player_id,
        Player.name,
        TournamentPlayer.points
    ).join(Player).filter(
        TournamentPlayer.tournament_id == tournament_id
    ).all()
    
    # Get all completed matches for tournament
    matches = Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.status == MatchStatus.COMPLETED
    ).all()
    
    # Compute statistics
    total_matches = len(matches)
    white_wins = len([m for m in matches if m.result == MatchResult.WHITE_WIN])
    black_wins = len([m for m in matches if m.result == MatchResult.BLACK_WIN])
    draws = len([m for m in matches if m.result == MatchResult.DRAW])
    forfeits = len([m for m in matches if m.result in [MatchResult.FORFEIT_WHITE, MatchResult.FORFEIT_BLACK]])
    
    # Player rankings
    player_stats = []
    for player_id, name, points in players:
        white_matches = [m for m in matches if m.white_player_id == player_id]
        black_matches = [m for m in matches if m.black_player_id == player_id]
        
        # Calculate individual stats
        wins = len([m for m in white_matches if m.result == MatchResult.WHITE_WIN]) + \
               len([m for m in black_matches if m.result == MatchResult.BLACK_WIN])
        losses = len([m for m in white_matches if m.result == MatchResult.BLACK_WIN]) + \
                len([m for m in black_matches if m.result == MatchResult.WHITE_WIN])
        player_draws = len([m for m in white_matches + black_matches if m.result == MatchResult.DRAW])
        
        total_player_matches = len(white_matches) + len(black_matches)
        
        if total_player_matches > 0:
            player_stats.append({
                'name': name,
                'matches': total_player_matches,
                'wins': wins,
                'draws': player_draws,
                'losses': losses,
                'points': points or 0,
                'win_rate': round((wins / total_player_matches) * 100, 1)
            })
    
    # Sort by points and win rate
    player_stats.sort(key=lambda x: (x['points'], x['win_rate']), reverse=True)
    
    # Group statistics
    groups = Group.query.filter_by(tournament_id=tournament_id).all()
    group_stats = []
    
    for group in groups:
        group_matches = Match.query.filter(
            Match.tournament_id == tournament_id,
            Match.group_id == group.id,
            Match.status == MatchStatus.COMPLETED
        ).all()
        
        group_players = TournamentPlayer.query.filter(
            TournamentPlayer.tournament_id == tournament_id,
            TournamentPlayer.group_id == group.id
        ).join(Player).all()
        
        if group_players:
            group_stats.append({
                'name': group.name,
                'player_count': len(group_players),
                'match_count': len(group_matches),
                'completed_matches': len([m for m in group_matches if m.status == MatchStatus.COMPLETED]),
                'players': [{'name': p.player.name, 'points': p.points} for p in group_players]
            })
    
    return jsonify({
        'tournament': {
            'name': tournament.name,
            'start_date': tournament.start_date.strftime('%d/%m/%Y'),
            'end_date': tournament.end_date.strftime('%d/%m/%Y'),
            'status': tournament.status
        },
        'match_stats': {
            'total': total_matches,
            'white_wins': white_wins,
            'white_win_pct': round(white_wins/total_matches*100, 1) if total_matches else 0,
            'black_wins': black_wins,
            'black_win_pct': round(black_wins/total_matches*100, 1) if total_matches else 0,
            'draws': draws,
            'draw_pct': round(draws/total_matches*100, 1) if total_matches else 0,
            'forfeits': forfeits,
            'forfeit_pct': round(forfeits/total_matches*100, 1) if total_matches else 0
        },
        'player_stats': player_stats,
        'group_stats': group_stats
    })


# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403


# Authentication
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if hasattr(current_user, 'username'):
            # Admin
            return redirect(url_for('admin_dashboard'))
        else:
            # Player
            return redirect(url_for('player_dashboard'))
    
    if request.method == 'POST':
        if 'admin_login' in request.form:
            # Admin login
            username = request.form.get('username')
            password = request.form.get('password')
            
            admin = Admin.query.filter_by(username=username).first()
            if admin and admin.check_password(password):
                login_user(admin)
                next_page = request.args.get('next')
                return redirect(next_page or url_for('admin_dashboard'))
            else:
                flash('Invalid username or password', 'danger')
        else:
            # Player login
            access_code = request.form.get('access_code')
            player = Player.query.filter_by(access_code=access_code).first()
            
            if player:
                login_user(player)
                next_page = request.args.get('next')
                return redirect(next_page or url_for('player_dashboard'))
            else:
                flash('Invalid access code', 'danger')
    
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


# Player routes
@app.route('/player/dashboard')
@login_required
def player_dashboard():
    if hasattr(current_user, 'username'):
        # For admin, redirect to admin dashboard
        return redirect(url_for('admin_dashboard'))
    
    # Get tournaments that this player is part of
    player_tournaments = db.session.query(
        Tournament, TournamentPlayer
    ).join(TournamentPlayer).filter(
        TournamentPlayer.player_id == current_user.id
    ).all()
    
    # Get upcoming matches for this player
    upcoming_matches = []
    recent_matches = []
    next_tournament_id = None
    
    for tournament, player_info in player_tournaments:
        # Get all matches for this player in this tournament
        tournament_matches = get_player_matches(tournament.id, current_user.id)
        
        # Sort by round number
        tournament_matches.sort(key=lambda m: m.round)
        
        # Add completed matches to recent matches list
        for match in tournament_matches:
            if match.status == MatchStatus.COMPLETED:
                recent_matches.append((tournament, match))
            elif match.status == MatchStatus.SCHEDULED or match.status == MatchStatus.IN_PROGRESS:
                upcoming_matches.append((tournament, match))
                
                if not next_tournament_id:
                    next_tournament_id = tournament.id
    
    # Sort recent matches by start time, most recent first
    recent_matches.sort(key=lambda x: x[1].start_time if x[1].start_time else datetime.now(), reverse=True)
    
    # Limit to 5 recent matches
    recent_matches = recent_matches[:5]
    
    # Get standings for groups the player is in
    player_standings = []
    
    for tournament, player_info in player_tournaments:
        if player_info.group_id:
            # Get standings for this group
            group_standings = db.session.query(
                TournamentPlayer, Player
            ).join(Player).filter(
                TournamentPlayer.tournament_id == tournament.id,
                TournamentPlayer.group_id == player_info.group_id
            ).order_by(
                TournamentPlayer.points.desc(),
                TournamentPlayer.tiebreak_score.desc()
            ).all()
            
            player_standings.append({
                'tournament': tournament,
                'group': player_info.group,
                'standings': group_standings,
                'knockout_players': tournament.knockout_players,
                'player_qualified': not player_info.eliminated and player_info.seed is not None
            })
    
    # Get active tournament for player if there is one
    active_tournament = None
    active_player_info = None
    
    if next_tournament_id:
        for tournament, player_info in player_tournaments:
            if tournament.id == next_tournament_id:
                active_tournament = tournament
                active_player_info = player_info
                break
    
    return render_template('player_dashboard.html',
                           player=current_user,
                           tournaments=player_tournaments,
                           upcoming_matches=upcoming_matches,
                           recent_matches=recent_matches,
                           player_standings=player_standings,
                           active_tournament=active_tournament,
                           active_player_info=active_player_info)


def get_player_matches(tournament_id, player_id):
    # Get all matches for this player in this tournament
    player_matches = Match.query.filter(
        Match.tournament_id == tournament_id,
        (Match.white_player_id == player_id) | (Match.black_player_id == player_id)
    ).all()
    
    return player_matches


# Public tournament view
@app.route('/tournament/<int:tournament_id>')
def tournament_view(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Get all active/completed matches
    matches = Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.status.in_([MatchStatus.IN_PROGRESS, MatchStatus.COMPLETED])
    ).all()
    
    # Group stage matches
    group_matches = [m for m in matches if m.group_id is not None]
    
    # Group stage standings
    groups = Group.query.filter_by(tournament_id=tournament_id).all()
    group_standings = {}
    
    for group in groups:
        standings = db.session.query(
            TournamentPlayer, Player
        ).join(Player).filter(
            TournamentPlayer.tournament_id == tournament_id,
            TournamentPlayer.group_id == group.id
        ).order_by(
            TournamentPlayer.points.desc(),
            TournamentPlayer.tiebreak_score.desc()
        ).all()
        
        group_standings[group.id] = standings
    
    # Knockout stage matches
    knockout_matches = [m for m in matches if m.group_id is None and m.knockout_round is not None]
    
    # Organize matches by round
    round_matches = {}
    for match in knockout_matches:
        if match.knockout_round not in round_matches:
            round_matches[match.knockout_round] = []
        round_matches[match.knockout_round].append(match)
    
    # Sort rounds in the correct order (final, semifinal, quarterfinal...)
    round_order = ['final', 'third_place', 'semifinal', 'quarterfinal', 'round_of_16', 'round_of_32']
    sorted_rounds = sorted(round_matches.items(), key=lambda x: round_order.index(x[0]) if x[0] in round_order else 99)
    
    return render_template('tournament_view.html',
                           tournament=tournament,
                           group_matches=group_matches,
                           groups=groups,
                           group_standings=group_standings,
                           knockout_rounds=sorted_rounds)


# Admin dashboard
@app.route('/admin/dashboard')
@admin_login_required
def admin_dashboard():
    # Recent tournaments
    recent_tournaments = Tournament.query.order_by(Tournament.start_date.desc()).limit(5).all()
    
    # Players count
    player_count = Player.query.count()
    
    # Upcoming matches
    upcoming_matches = Match.query.filter(
        Match.status == MatchStatus.SCHEDULED,
        Match.start_time > datetime.now()
    ).order_by(Match.start_time).limit(10).all()
    
    # Active matches
    active_matches = Match.query.filter_by(status=MatchStatus.IN_PROGRESS).all()
    
    return render_template('admin/dashboard.html',
                           recent_tournaments=recent_tournaments,
                           player_count=player_count,
                           upcoming_matches=upcoming_matches,
                           active_matches=active_matches)


# Tournaments
@app.route('/admin/tournaments')
@admin_login_required
def admin_tournaments():
    tournaments = Tournament.query.order_by(Tournament.start_date.desc()).all()
    return render_template('admin/tournaments.html', tournaments=tournaments)


# Template helper function
@app.context_processor
def utility_processor():
    def get_all_players():
        return Player.query.order_by(Player.name).all()
    
    def now():
        return datetime.now()
    
    return dict(get_all_players=get_all_players, now=now, get_tournaments=get_tournaments)


# Tournament management
@app.route('/admin/tournaments/<int:tournament_id>')
@admin_login_required
def admin_tournament_detail(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Get players in tournament
    tournament_players = db.session.query(
        TournamentPlayer, Player
    ).join(Player).filter(
        TournamentPlayer.tournament_id == tournament_id
    ).all()
    
    # Get groups if they exist
    groups = Group.query.filter_by(tournament_id=tournament_id).all()
    group_players = {}
    
    for group in groups:
        players_in_group = db.session.query(
            TournamentPlayer, Player
        ).join(Player).filter(
            TournamentPlayer.tournament_id == tournament_id,
            TournamentPlayer.group_id == group.id
        ).order_by(
            TournamentPlayer.points.desc(),
            TournamentPlayer.tiebreak_score.desc()
        ).all()
        
        group_players[group.id] = players_in_group
    
    # Get matches by group and round
    group_matches = {}
    
    for group in groups:
        matches = Match.query.filter_by(
            tournament_id=tournament_id,
            group_id=group.id
        ).order_by(Match.round).all()
        
        group_matches[group.id] = {}
        for match in matches:
            if match.round not in group_matches[group.id]:
                group_matches[group.id][match.round] = []
            group_matches[group.id][match.round].append(match)
    
    # Get knockout matches
    knockout_matches = Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.group_id.is_(None),
        Match.knockout_round.isnot(None)
    ).all()
    
    # Group knockout matches by round
    round_matches = {}
    for match in knockout_matches:
        if match.knockout_round not in round_matches:
            round_matches[match.knockout_round] = []
        round_matches[match.knockout_round].append(match)
    
    # Get chessboards for tournament
    chessboards = Chessboard.query.filter_by(
        tournament_id=tournament_id
    ).order_by(Chessboard.board_number).all()
    
    # Get unassigned matches
    unassigned_matches = Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.chessboard_id.is_(None),
        Match.status.in_([MatchStatus.SCHEDULED, MatchStatus.IN_PROGRESS])
    ).all()
    
    return render_template('admin/tournament_detail.html',
                           tournament=tournament,
                           tournament_players=tournament_players,
                           groups=groups,
                           group_players=group_players,
                           group_matches=group_matches,
                           knockout_rounds=round_matches,
                           chessboards=chessboards,
                           unassigned_matches=unassigned_matches)


@app.route('/admin/tournaments/new', methods=['GET', 'POST'])
@admin_login_required
def admin_tournament_new():
    if request.method == 'POST':
        # Create new tournament
        tournament = Tournament()
        tournament.name = request.form.get('name')
        tournament.description = request.form.get('description')
        tournament.location = request.form.get('location')
        tournament.start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d')
        tournament.end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d')
        tournament.group_count = int(request.form.get('group_count', 4))
        tournament.players_per_group = int(request.form.get('players_per_group', 4))
        tournament.knockout_players = int(request.form.get('knockout_players', 8))
        tournament.board_count = int(request.form.get('board_count', 10))
        
        db.session.add(tournament)
        db.session.commit()
        
        flash(f'Torneo "{tournament.name}" creato con successo!', 'success')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament.id))
    
    return render_template('admin/tournament_form.html')


@app.route('/admin/tournaments/<int:tournament_id>/edit', methods=['GET', 'POST'])
@admin_login_required
def admin_tournament_edit(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    if request.method == 'POST':
        # Update tournament
        tournament.name = request.form.get('name')
        tournament.description = request.form.get('description')
        tournament.location = request.form.get('location')
        tournament.start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d')
        tournament.end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d')
        tournament.group_count = int(request.form.get('group_count', 4))
        tournament.players_per_group = int(request.form.get('players_per_group', 4))
        tournament.knockout_players = int(request.form.get('knockout_players', 8))
        tournament.board_count = int(request.form.get('board_count', 10))
        
        db.session.commit()
        
        flash(f'Torneo "{tournament.name}" aggiornato con successo!', 'success')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament.id))
    
    return render_template('admin/tournament_form.html', tournament=tournament)


@app.route('/admin/tournaments/<int:tournament_id>/delete', methods=['POST'])
@admin_login_required
def admin_tournament_delete(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    try:
        db.session.delete(tournament)
        db.session.commit()
        flash(f'Torneo "{tournament.name}" eliminato con successo!', 'success')
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(f'Errore durante l\'eliminazione del torneo: {str(e)}', 'danger')
    
    return redirect(url_for('admin_tournaments'))


# Player management
@app.route('/admin/players')
@admin_login_required
def admin_players():
    players = Player.query.order_by(Player.name).all()
    return render_template('admin/players.html', players=players)


@app.route('/admin/players/new', methods=['GET', 'POST'])
@admin_login_required
def admin_player_new():
    if request.method == 'POST':
        # Create new player
        player = Player()
        player.name = request.form.get('name')
        player.email = request.form.get('email')
        player.phone = request.form.get('phone')
        player.rating = request.form.get('rating')
        player.access_code = Player.generate_access_code()
        
        db.session.add(player)
        db.session.commit()
        
        flash(f'Giocatore "{player.name}" creato con successo!', 'success')
        return redirect(url_for('admin_players'))
    
    return render_template('admin/player_form.html')


@app.route('/admin/players/<int:player_id>/edit', methods=['GET', 'POST'])
@admin_login_required
def admin_player_edit(player_id):
    player = Player.query.get_or_404(player_id)
    
    if request.method == 'POST':
        # Update player
        player.name = request.form.get('name')
        player.email = request.form.get('email')
        player.phone = request.form.get('phone')
        player.rating = request.form.get('rating')
        
        db.session.commit()
        
        flash(f'Giocatore "{player.name}" aggiornato con successo!', 'success')
        return redirect(url_for('admin_players'))
    
    return render_template('admin/player_form.html', player=player)


@app.route('/admin/players/<int:player_id>/delete', methods=['POST'])
@admin_login_required
def admin_player_delete(player_id):
    player = Player.query.get_or_404(player_id)
    
    try:
        db.session.delete(player)
        db.session.commit()
        flash(f'Giocatore "{player.name}" eliminato con successo!', 'success')
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(f'Errore durante l\'eliminazione del giocatore: {str(e)}', 'danger')
    
    return redirect(url_for('admin_players'))


# Tournament player management
@app.route('/admin/tournaments/<int:tournament_id>/add_player', methods=['POST'])
@admin_login_required
def admin_tournament_add_player(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    player_id = request.form.get('player_id')
    
    if not player_id:
        flash('Seleziona un giocatore da aggiungere', 'danger')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    # Check if player already in tournament
    existing = TournamentPlayer.query.filter_by(
        tournament_id=tournament_id,
        player_id=player_id
    ).first()
    
    if existing:
        flash('Il giocatore è già iscritto a questo torneo', 'warning')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    # Add player to tournament
    tournament_player = TournamentPlayer()
    tournament_player.tournament_id = tournament_id
    tournament_player.player_id = player_id
    
    db.session.add(tournament_player)
    db.session.commit()
    
    player = Player.query.get(player_id)
    flash(f'Giocatore "{player.name}" aggiunto al torneo', 'success')
    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))


@app.route('/admin/tournaments/<int:tournament_id>/remove_player/<int:player_id>', methods=['POST'])
@admin_login_required
def admin_tournament_remove_player(tournament_id, player_id):
    # Check if player is in tournament
    tournament_player = TournamentPlayer.query.filter_by(
        tournament_id=tournament_id,
        player_id=player_id
    ).first_or_404()
    
    player = Player.query.get(player_id)
    
    # Check if player has any matches
    player_matches = Match.query.filter(
        Match.tournament_id == tournament_id,
        (Match.white_player_id == player_id) | (Match.black_player_id == player_id),
        Match.status != MatchStatus.CANCELLED
    ).first()
    
    if player_matches:
        flash(f'Non puoi rimuovere "{player.name}" perché ha già partite programmate o completate', 'danger')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    try:
        db.session.delete(tournament_player)
        db.session.commit()
        flash(f'Giocatore "{player.name}" rimosso dal torneo', 'success')
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(f'Errore durante la rimozione del giocatore: {str(e)}', 'danger')
    
    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))


# Tournament management operations
@app.route('/admin/tournaments/<int:tournament_id>/create_groups', methods=['POST'])
@admin_login_required
def admin_tournament_create_groups(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Check if tournament is in draft status
    if tournament.status != TournamentStatus.DRAFT:
        flash('I gironi possono essere creati solo per tornei in stato bozza', 'danger')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    # Check if groups already exist
    existing_groups = Group.query.filter_by(tournament_id=tournament_id).first()
    if existing_groups:
        flash('I gironi sono già stati creati per questo torneo', 'warning')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    # Count players
    player_count = TournamentPlayer.query.filter_by(tournament_id=tournament_id).count()
    if player_count < tournament.group_count:
        flash(f'Non ci sono abbastanza giocatori. Sono necessari almeno {tournament.group_count} giocatori.', 'danger')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    try:
        create_groups(tournament_id)
        tournament.status = TournamentStatus.GROUP_STAGE
        db.session.commit()
        flash('Gironi creati con successo', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante la creazione dei gironi: {str(e)}', 'danger')
    
    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))


@app.route('/admin/tournaments/<int:tournament_id>/generate_matches', methods=['POST'])
@admin_login_required
def admin_tournament_generate_matches(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Check if tournament is in group stage
    if tournament.status != TournamentStatus.GROUP_STAGE:
        flash('Gli accoppiamenti possono essere generati solo per tornei in fase a gironi', 'danger')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    # Check if matches already exist
    existing_matches = Match.query.filter_by(tournament_id=tournament_id).first()
    if existing_matches:
        flash('Gli accoppiamenti sono già stati generati per questo torneo', 'warning')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    try:
        generate_group_matches(tournament_id)
        db.session.commit()
        flash('Accoppiamenti generati con successo', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante la generazione degli accoppiamenti: {str(e)}', 'danger')
    
    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))


@app.route('/admin/tournaments/<int:tournament_id>/update_standings', methods=['POST'])
@admin_login_required
def admin_tournament_update_standings(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    try:
        update_group_standings(tournament_id)
        db.session.commit()
        flash('Classifiche aggiornate con successo', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante l\'aggiornamento delle classifiche: {str(e)}', 'danger')
    
    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))


@app.route('/admin/tournaments/<int:tournament_id>/select_knockout', methods=['GET', 'POST'])
@admin_login_required
def admin_tournament_select_knockout(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Check if tournament is in group stage
    if tournament.status != TournamentStatus.GROUP_STAGE:
        flash('La selezione della fase knockout può essere fatta solo per tornei in fase a gironi', 'danger')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    # Get groups and players
    groups = Group.query.filter_by(tournament_id=tournament_id).all()
    group_players = {}
    
    for group in groups:
        players_in_group = db.session.query(
            TournamentPlayer, Player
        ).join(Player).filter(
            TournamentPlayer.tournament_id == tournament_id,
            TournamentPlayer.group_id == group.id
        ).order_by(
            TournamentPlayer.points.desc(),
            TournamentPlayer.tiebreak_score.desc()
        ).all()
        
        group_players[group.id] = players_in_group
    
    # Check if we have knockout matches already
    knockout_matches = Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.group_id.is_(None),
        Match.knockout_round.isnot(None)
    ).first()
    
    if knockout_matches:
        flash('La fase knockout è già stata generata per questo torneo', 'warning')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    if request.method == 'POST':
        # Get selected players
        selected_player_ids = request.form.getlist('selected_players')
        
        if len(selected_player_ids) != tournament.knockout_players:
            flash(f'Devi selezionare esattamente {tournament.knockout_players} giocatori', 'danger')
            return redirect(url_for('admin_tournament_select_knockout', tournament_id=tournament_id))
        
        try:
            select_knockout_players(tournament_id, selected_player_ids)
            tournament.status = TournamentStatus.KNOCKOUT_STAGE
            db.session.commit()
            flash('Giocatori selezionati per la fase knockout con successo', 'success')
            return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Errore durante la selezione dei giocatori: {str(e)}', 'danger')
    
    return render_template('admin/select_knockout.html',
                           tournament=tournament,
                           groups=groups,
                           group_players=group_players)


@app.route('/admin/tournaments/<int:tournament_id>/generate_knockout', methods=['POST'])
@admin_login_required
def admin_tournament_generate_knockout(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Check if tournament is in knockout stage
    if tournament.status != TournamentStatus.KNOCKOUT_STAGE:
        flash('Gli accoppiamenti knockout possono essere generati solo per tornei in fase knockout', 'danger')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    # Check if knockout matches already exist
    knockout_matches = Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.group_id.is_(None),
        Match.knockout_round.isnot(None)
    ).first()
    
    if knockout_matches:
        flash('Gli accoppiamenti knockout sono già stati generati per questo torneo', 'warning')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    try:
        generate_knockout_matches(tournament_id)
        db.session.commit()
        flash('Accoppiamenti knockout generati con successo', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante la generazione degli accoppiamenti knockout: {str(e)}', 'danger')
    
    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))


@app.route('/admin/match/<int:match_id>/edit', methods=['GET', 'POST'])
@admin_login_required
def admin_match_edit(match_id):
    match = Match.query.get_or_404(match_id)
    
    if request.method == 'POST':
        status = request.form.get('status')
        result = request.form.get('result')
        
        match.status = status
        
        if status == MatchStatus.COMPLETED:
            match.result = result
            
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
            elif result == MatchResult.NO_SHOW:
                match.white_score = 0.0
                match.black_score = 0.0
            
            # If this is a knockout match, advance winner to next match
            if match.next_match_id and match.result not in [MatchResult.DRAW, MatchResult.NO_SHOW]:
                advance_knockout_player(match.id)
        
        # Update match details
        if request.form.get('start_time'):
            match.start_time = datetime.strptime(request.form.get('start_time'), '%Y-%m-%dT%H:%M')
        
        match.notes = request.form.get('notes')
        
        db.session.commit()
        
        # Update tournament standings if this is a group match
        if match.group_id:
            update_group_standings(match.tournament_id)
        
        flash('Partita aggiornata con successo', 'success')
        return redirect(url_for('admin_tournament_detail', tournament_id=match.tournament_id))
    
    return render_template('admin/match_edit.html', match=match)


@app.route('/admin/tournaments/<int:tournament_id>/complete', methods=['POST'])
@admin_login_required
def admin_tournament_complete(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Check if tournament is in knockout stage
    if tournament.status != TournamentStatus.KNOCKOUT_STAGE:
        flash('Il torneo può essere completato solo quando è in fase knockout', 'danger')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    # Check if all knockout matches are completed
    incomplete_matches = Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.knockout_round.isnot(None),
        Match.status != MatchStatus.COMPLETED
    ).first()
    
    if incomplete_matches:
        flash('Non puoi completare il torneo finché tutte le partite knockout non sono completate', 'danger')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    try:
        complete_tournament(tournament_id)
        db.session.commit()
        flash('Torneo completato con successo', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante il completamento del torneo: {str(e)}', 'danger')
    
    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))


@app.route('/admin/tournaments/<int:tournament_id>/player_codes')
@admin_login_required
def admin_tournament_player_codes(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    tournament_players = db.session.query(
        Player, TournamentPlayer
    ).join(TournamentPlayer).filter(
        TournamentPlayer.tournament_id == tournament_id
    ).order_by(Player.name).all()
    
    return render_template('admin/player_codes.html',
                           tournament=tournament,
                           tournament_players=tournament_players)


# Chessboard view
@app.route('/chessboard/<code>')
def chessboard_view(code):
    # Find chessboard by access code
    chessboard = Chessboard.query.filter_by(access_code=code).first_or_404()
    
    # Update last used time
    chessboard.last_used = datetime.now()
    db.session.commit()
    
    # Get active match on this board
    active_match = Match.query.filter(
        Match.chessboard_id == chessboard.id,
        Match.status.in_([MatchStatus.SCHEDULED, MatchStatus.IN_PROGRESS])
    ).first()
    
    tournament = Tournament.query.get(chessboard.tournament_id)
    
    return render_template('chessboard.html',
                           chessboard=chessboard,
                           active_match=active_match,
                           tournament=tournament)


@app.route('/chessboard/<code>/start', methods=['POST'])
def chessboard_start_match(code):
    # Find chessboard by access code
    chessboard = Chessboard.query.filter_by(access_code=code).first_or_404()
    match_id = request.form.get('match_id')
    
    if not match_id:
        flash('Nessuna partita selezionata', 'danger')
        return redirect(url_for('chessboard_view', code=code))
    
    match = Match.query.get(match_id)
    
    if match.status == MatchStatus.SCHEDULED:
        match.status = MatchStatus.IN_PROGRESS
        match.start_time = datetime.now()
        db.session.commit()
        flash('Partita iniziata', 'success')
    
    return redirect(url_for('chessboard_view', code=code))


@app.route('/chessboard/<code>/submit_result', methods=['POST'])
def chessboard_submit_result(code):
    # Find chessboard by access code
    chessboard = Chessboard.query.filter_by(access_code=code).first_or_404()
    match_id = request.form.get('match_id')
    result = request.form.get('result')
    
    if not match_id or not result:
        flash('Dati mancanti', 'danger')
        return redirect(url_for('chessboard_view', code=code))
    
    match = Match.query.get(match_id)
    
    if match.status != MatchStatus.COMPLETED:
        match.status = MatchStatus.COMPLETED
        match.result = result
        
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
        elif result == MatchResult.NO_SHOW:
            match.white_score = 0.0
            match.black_score = 0.0
        
        # If this is a knockout match, advance winner to next match
        if match.next_match_id and match.result not in [MatchResult.DRAW, MatchResult.NO_SHOW]:
            advance_knockout_player(match.id)
        
        db.session.commit()
        
        # Update tournament standings if this is a group match
        if match.group_id:
            update_group_standings(match.tournament_id)
        
        flash('Risultato registrato', 'success')
    
    return redirect(url_for('chessboard_view', code=code))


# Chessboard management
@app.route('/admin/tournaments/<int:tournament_id>/chessboards')
@admin_login_required
def admin_tournament_chessboards(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    chessboards = Chessboard.query.filter_by(
        tournament_id=tournament_id
    ).order_by(Chessboard.board_number).all()
    
    return render_template('admin/chessboards.html',
                           tournament=tournament,
                           chessboards=chessboards)


@app.route('/admin/tournaments/<int:tournament_id>/create_chessboards', methods=['POST'])
@admin_login_required
def admin_tournament_create_chessboards(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Get number to create
    board_count = int(request.form.get('board_count', 1))
    
    if board_count <= 0:
        flash('Il numero di scacchiere deve essere maggiore di zero', 'danger')
        return redirect(url_for('admin_tournament_chessboards', tournament_id=tournament_id))
    
    # Find next board number
    max_board = db.session.query(func.max(Chessboard.board_number)).filter(
        Chessboard.tournament_id == tournament_id
    ).scalar() or 0
    
    # Create chessboards
    for i in range(1, board_count + 1):
        chessboard = Chessboard()
        chessboard.tournament_id = tournament_id
        chessboard.board_number = max_board + i
        chessboard.access_code = Chessboard.generate_access_code()
        chessboard.display_mode = 'single'
        chessboard.is_active = True
        
        db.session.add(chessboard)
    
    db.session.commit()
    flash(f'{board_count} scacchiere create con successo', 'success')
    return redirect(url_for('admin_tournament_chessboards', tournament_id=tournament_id))


@app.route('/admin/tournaments/<int:tournament_id>/assign_matches', methods=['POST'])
@admin_login_required
def admin_tournament_assign_matches(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    # Get unassigned matches
    unassigned_matches = Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.board_number.is_(None),
        Match.status.in_([MatchStatus.SCHEDULED])
    ).all()
    
    if not unassigned_matches:
        flash('Non ci sono partite da assegnare', 'info')
        return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))
    
    # Get active chessboards
    chessboards = Chessboard.query.filter_by(
        tournament_id=tournament_id,
        is_active=True
    ).count()
    
    if not chessboards:
        flash('Non ci sono scacchiere attive', 'danger')
        return redirect(url_for('admin_tournament_chessboards', tournament_id=tournament_id))
    
    try:
        # Assign board numbers
        board_numbers = assign_board_numbers(unassigned_matches, chessboards)
        
        for match, board_num in board_numbers.items():
            match.board_number = board_num
        
        db.session.commit()
        flash('Scacchiere assegnate con successo', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Errore durante l\'assegnazione delle scacchiere: {str(e)}', 'danger')
    
    return redirect(url_for('admin_tournament_detail', tournament_id=tournament_id))


@app.route('/admin/match/<int:match_id>/assign_board', methods=['POST'])
@admin_login_required
def admin_match_assign_board(match_id):
    match = Match.query.get_or_404(match_id)
    chessboard_id = request.form.get('chessboard_id')
    
    if not chessboard_id:
        flash('Nessuna scacchiera selezionata', 'danger')
        return redirect(url_for('admin_tournament_detail', tournament_id=match.tournament_id))
    
    # Check if chessboard exists and is active
    chessboard = Chessboard.query.filter_by(
        id=chessboard_id,
        is_active=True
    ).first()
    
    if not chessboard:
        flash('Scacchiera non valida o non attiva', 'danger')
        return redirect(url_for('admin_tournament_detail', tournament_id=match.tournament_id))
    
    match.chessboard_id = chessboard.id
    match.board_number = chessboard.board_number
    db.session.commit()
    
    flash('Partita assegnata alla scacchiera', 'success')
    return redirect(url_for('admin_tournament_detail', tournament_id=match.tournament_id))


@app.route('/admin/chessboard/<int:board_id>/toggle_display_mode', methods=['POST'])
@admin_login_required
def admin_chessboard_toggle_display_mode(board_id):
    chessboard = Chessboard.query.get_or_404(board_id)
    
    if chessboard.display_mode == 'single':
        chessboard.display_mode = 'double'
    else:
        chessboard.display_mode = 'single'
    
    db.session.commit()
    
    flash('Modalità di visualizzazione modificata', 'success')
    return redirect(url_for('admin_tournament_chessboards', tournament_id=chessboard.tournament_id))


@app.route('/admin/chessboard/<int:board_id>/toggle_active', methods=['POST'])
@admin_login_required
def admin_chessboard_toggle_active(board_id):
    chessboard = Chessboard.query.get_or_404(board_id)
    
    chessboard.is_active = not chessboard.is_active
    
    db.session.commit()
    
    status = 'attivata' if chessboard.is_active else 'disattivata'
    flash(f'Scacchiera {status} con successo', 'success')
    return redirect(url_for('admin_tournament_chessboards', tournament_id=chessboard.tournament_id))


@app.route('/admin/chessboard/<int:board_id>/regenerate_code', methods=['POST'])
@admin_login_required
def admin_chessboard_regenerate_code(board_id):
    chessboard = Chessboard.query.get_or_404(board_id)
    
    chessboard.access_code = Chessboard.generate_access_code()
    db.session.commit()
    
    flash('Codice di accesso rigenerato', 'success')
    return redirect(url_for('admin_tournament_chessboards', tournament_id=chessboard.tournament_id))


@app.route('/admin/chessboard/<int:board_id>/delete', methods=['POST'])
@admin_login_required
def admin_chessboard_delete(board_id):
    chessboard = Chessboard.query.get_or_404(board_id)
    tournament_id = chessboard.tournament_id
    
    # Check if chessboard has active matches
    active_match = Match.query.filter(
        Match.chessboard_id == board_id,
        Match.status.in_([MatchStatus.SCHEDULED, MatchStatus.IN_PROGRESS])
    ).first()
    
    if active_match:
        flash('Non puoi eliminare una scacchiera con partite attive', 'danger')
        return redirect(url_for('admin_tournament_chessboards', tournament_id=tournament_id))
    
    try:
        db.session.delete(chessboard)
        db.session.commit()
        flash('Scacchiera eliminata con successo', 'success')
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(f'Errore durante l\'eliminazione della scacchiera: {str(e)}', 'danger')
    
    return redirect(url_for('admin_tournament_chessboards', tournament_id=tournament_id))


# Initialization function
@app.route('/setup', methods=['GET', 'POST'])
def setup():
    # Sempre permetti la creazione di un nuovo admin per il tuo caso specifico
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        
        # Crea un nuovo admin
        admin = Admin()
        admin.username = username
        admin.email = email
        admin.set_password(password)
        
        db.session.add(admin)
        db.session.commit()
        
        flash('Setup completato con successo. Ora puoi effettuare il login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('setup.html')


#
# Gallery Management Routes
#

# Utility function to ensure upload directory exists
def ensure_upload_directory():
    os.makedirs('static/uploads/photos', exist_ok=True)

# Admin gallery management
@app.route('/admin/tournaments/<int:tournament_id>/gallery')
@admin_login_required
def admin_gallery(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    categories = PhotoCategory.query.all()
    
    # Get selected category_id from query params
    selected_category_id = request.args.get('category_id', type=int)
    
    # Filter photos by category if selected
    if selected_category_id:
        photos = TournamentPhoto.query.filter_by(
            tournament_id=tournament_id,
            category_id=selected_category_id
        ).order_by(TournamentPhoto.event_date, TournamentPhoto.order).all()
    else:
        photos = TournamentPhoto.query.filter_by(
            tournament_id=tournament_id
        ).order_by(TournamentPhoto.event_date, TournamentPhoto.order).all()
    
    return render_template('admin/gallery.html',
                           tournament=tournament,
                           photos=photos,
                           categories=categories,
                           selected_category_id=selected_category_id)

@app.route('/admin/tournaments/<int:tournament_id>/gallery/filter')
@admin_login_required
def admin_gallery_filter(tournament_id):
    return redirect(url_for('admin_gallery', 
                            tournament_id=tournament_id, 
                            category_id=request.args.get('category_id')))

@app.route('/admin/gallery/add_category', methods=['POST'])
@admin_login_required
def admin_gallery_add_category():
    name = request.form.get('name')
    description = request.form.get('description')
    
    if not name:
        flash('Il nome della categoria è obbligatorio', 'danger')
        return redirect(request.referrer)
    
    category = PhotoCategory()
    category.name = name
    category.description = description
    
    db.session.add(category)
    db.session.commit()
    
    flash('Categoria aggiunta con successo', 'success')
    return redirect(request.referrer)

@app.route('/admin/gallery/edit_category', methods=['POST'])
@admin_login_required
def admin_gallery_edit_category():
    category_id = request.form.get('category_id')
    name = request.form.get('name')
    description = request.form.get('description')
    
    if not category_id or not name:
        flash('Dati mancanti', 'danger')
        return redirect(request.referrer)
    
    category = PhotoCategory.query.get_or_404(category_id)
    category.name = name
    category.description = description
    
    db.session.commit()
    
    flash('Categoria aggiornata con successo', 'success')
    return redirect(request.referrer)

@app.route('/admin/gallery/delete_category/<int:category_id>', methods=['GET'])
@admin_login_required
def admin_gallery_delete_category(category_id):
    category = PhotoCategory.query.get_or_404(category_id)
    
    # Remove category from photos but don't delete photos
    photos = TournamentPhoto.query.filter_by(category_id=category_id).all()
    for photo in photos:
        photo.category_id = None
    
    db.session.delete(category)
    db.session.commit()
    
    flash('Categoria eliminata con successo', 'success')
    return redirect(request.referrer)

@app.route('/admin/tournaments/<int:tournament_id>/gallery/upload', methods=['POST'])
@admin_login_required
def admin_gallery_upload(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    if 'photos' not in request.files:
        flash('Nessun file caricato', 'danger')
        return redirect(url_for('admin_gallery', tournament_id=tournament_id))
    
    files = request.files.getlist('photos')
    
    if not files or files[0].filename == '':
        flash('Nessun file selezionato', 'danger')
        return redirect(url_for('admin_gallery', tournament_id=tournament_id))
    
    category_id = request.form.get('category_id')
    if category_id == '':
        category_id = None
    
    event_date = request.form.get('event_date')
    if event_date:
        event_date = datetime.strptime(event_date, '%Y-%m-%d')
    else:
        event_date = None
    
    description = request.form.get('description')
    
    ensure_upload_directory()
    success_count = 0
    
    for file in files:
        if file and file.filename:
            # Ensure filename is secure
            filename = secure_filename(file.filename)
            # Add unique identifier to prevent filename conflicts
            name, ext = os.path.splitext(filename)
            unique_filename = f"{name}_{uuid.uuid4().hex}{ext}"
            
            # Save the file
            file_path = os.path.join('static/uploads/photos', unique_filename)
            file.save(file_path)
            
            # Create database entry
            photo = TournamentPhoto()
            photo.tournament_id = tournament_id
            photo.category_id = category_id
            photo.filename = unique_filename
            photo.title = os.path.splitext(filename)[0]  # Use filename as title
            photo.description = description
            photo.event_date = event_date
            
            db.session.add(photo)
            success_count += 1
    
    db.session.commit()
    
    flash(f'{success_count} foto caricate con successo', 'success')
    return redirect(url_for('admin_gallery', tournament_id=tournament_id))

@app.route('/admin/gallery/edit_photo/<int:photo_id>', methods=['GET', 'POST'])
@admin_login_required
def admin_gallery_edit_photo(photo_id):
    photo = TournamentPhoto.query.get_or_404(photo_id)
    categories = PhotoCategory.query.all()
    
    if request.method == 'POST':
        photo.title = request.form.get('title')
        photo.description = request.form.get('description')
        
        category_id = request.form.get('category_id')
        if category_id == '':
            photo.category_id = None
        else:
            photo.category_id = category_id
        
        event_date = request.form.get('event_date')
        if event_date:
            photo.event_date = datetime.strptime(event_date, '%Y-%m-%d')
        else:
            photo.event_date = None
        
        order = request.form.get('order')
        if order is not None and order.isdigit():
            photo.order = int(order)
        
        db.session.commit()
        
        flash('Foto aggiornata con successo', 'success')
        return redirect(url_for('admin_gallery', tournament_id=photo.tournament_id))
    
    return render_template('admin/edit_photo.html',
                           photo=photo,
                           categories=categories)

@app.route('/admin/gallery/delete_photo/<int:photo_id>', methods=['GET'])
@admin_login_required
def admin_gallery_delete_photo(photo_id):
    photo = TournamentPhoto.query.get_or_404(photo_id)
    tournament_id = photo.tournament_id
    
    # Delete file from filesystem
    file_path = os.path.join('static/uploads/photos', photo.filename)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        flash(f'Errore durante l\'eliminazione del file: {str(e)}', 'warning')
    
    # Delete database entry
    db.session.delete(photo)
    db.session.commit()
    
    flash('Foto eliminata con successo', 'success')
    return redirect(url_for('admin_gallery', tournament_id=tournament_id))

# Public gallery view
@app.route('/gallery/tournament/<int:tournament_id>')
def gallery_view(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    categories = PhotoCategory.query.all()
    
    # Get filters from query params
    selected_category_id = request.args.get('category_id', type=int)
    selected_date_str = request.args.get('event_date')
    
    # Build query
    query = TournamentPhoto.query.filter_by(tournament_id=tournament_id)
    
    if selected_category_id:
        query = query.filter_by(category_id=selected_category_id)
    
    selected_date = None
    if selected_date_str:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
        query = query.filter(func.date(TournamentPhoto.event_date) == selected_date)
    
    # Get all available event dates for filter dropdown
    event_dates = db.session.query(
        func.date(TournamentPhoto.event_date)
    ).filter(
        TournamentPhoto.tournament_id == tournament_id,
        TournamentPhoto.event_date.isnot(None)
    ).distinct().all()
    
    event_dates = [datetime.combine(date[0], datetime.min.time()) for date in event_dates]
    
    # Get filtered photos
    photos = query.order_by(TournamentPhoto.event_date, TournamentPhoto.order).all()
    
    return render_template('gallery/public_gallery.html',
                           tournament=tournament,
                           photos=photos,
                           categories=categories,
                           event_dates=event_dates,
                           selected_category_id=selected_category_id,
                           selected_date=selected_date)