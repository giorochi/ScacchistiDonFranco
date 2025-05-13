from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db
import random
import string

# Enum definitions
class TournamentStatus:
    DRAFT = 'draft'
    GROUP_STAGE = 'group_stage'
    KNOCKOUT_STAGE = 'knockout_stage'
    COMPLETED = 'completed'

class MatchStatus:
    SCHEDULED = 'scheduled'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'

class MatchResult:
    WHITE_WIN = 'white_win'
    BLACK_WIN = 'black_win'
    DRAW = 'draw'
    FORFEIT_WHITE = 'forfeit_white'
    FORFEIT_BLACK = 'forfeit_black'
    NO_SHOW = 'no_show'

# Models
class Admin(UserMixin, db.Model):
    __tablename__ = 'admins'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Player(UserMixin, db.Model):
    __tablename__ = 'players'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    access_code = db.Column(db.String(10), unique=True, nullable=False)
    rating = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Relationships
    tournaments = db.relationship('TournamentPlayer', back_populates='player', cascade='all, delete-orphan')
    white_matches = db.relationship('Match', foreign_keys='Match.white_player_id', back_populates='white_player')
    black_matches = db.relationship('Match', foreign_keys='Match.black_player_id', back_populates='black_player')
    
    def get_id(self):
        # Override the default get_id method to use access_code instead of id
        return self.access_code
    
    @staticmethod
    def generate_access_code():
        """Generate a unique access code for a player"""
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            if not Player.query.filter_by(access_code=code).first():
                return code

class Tournament(db.Model):
    __tablename__ = 'tournaments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(100), nullable=True)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default=TournamentStatus.DRAFT)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    # Tournament settings
    group_count = db.Column(db.Integer, default=4)  # Number of groups
    players_per_group = db.Column(db.Integer, default=4)  # Players per group
    knockout_players = db.Column(db.Integer, default=8)  # Players advancing to knockout
    
    # Relationships
    players = db.relationship('TournamentPlayer', back_populates='tournament', cascade='all, delete-orphan')
    groups = db.relationship('Group', back_populates='tournament', cascade='all, delete-orphan')
    matches = db.relationship('Match', back_populates='tournament', cascade='all, delete-orphan')

class TournamentPlayer(db.Model):
    __tablename__ = 'tournament_players'
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournaments.id', ondelete='CASCADE'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id', ondelete='CASCADE'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id', ondelete='SET NULL'), nullable=True)
    seed = db.Column(db.Integer, nullable=True)  # For seeding in knockout stage
    points = db.Column(db.Float, default=0)  # Total points in the tournament
    tiebreak_score = db.Column(db.Float, default=0)  # For tiebreaks
    eliminated = db.Column(db.Boolean, default=False)
    
    # Relationships
    tournament = db.relationship('Tournament', back_populates='players')
    player = db.relationship('Player', back_populates='tournaments')
    group = db.relationship('Group', back_populates='players')
    
    # Ensure each player is only in a tournament once
    __table_args__ = (
        db.UniqueConstraint('tournament_id', 'player_id', name='unique_tournament_player'),
    )

class Group(db.Model):
    __tablename__ = 'groups'
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournaments.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    
    # Relationships
    tournament = db.relationship('Tournament', back_populates='groups')
    players = db.relationship('TournamentPlayer', back_populates='group')
    matches = db.relationship('Match', back_populates='group')

    # Ensure group names are unique within a tournament
    __table_args__ = (
        db.UniqueConstraint('tournament_id', 'name', name='unique_tournament_group'),
    )

class Match(db.Model):
    __tablename__ = 'matches'
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournaments.id', ondelete='CASCADE'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id', ondelete='SET NULL'), nullable=True)  # Null for knockout matches
    round = db.Column(db.Integer, nullable=False)  # Round number (1, 2, 3, etc.)
    board_number = db.Column(db.Integer, nullable=True)  # Chessboard assignment
    
    # Players
    white_player_id = db.Column(db.Integer, db.ForeignKey('players.id', ondelete='SET NULL'), nullable=True)
    black_player_id = db.Column(db.Integer, db.ForeignKey('players.id', ondelete='SET NULL'), nullable=True)
    
    # Match details
    start_time = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default=MatchStatus.SCHEDULED)
    result = db.Column(db.String(20), nullable=True)
    white_score = db.Column(db.Float, nullable=True)
    black_score = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    
    # Knockout phase specific
    knockout_round = db.Column(db.String(20), nullable=True)  # quarterfinal, semifinal, final
    knockout_match_num = db.Column(db.Integer, nullable=True)  # Match number in bracket
    next_match_id = db.Column(db.Integer, db.ForeignKey('matches.id', ondelete='SET NULL'), nullable=True)
    
    # Relationships
    tournament = db.relationship('Tournament', back_populates='matches')
    group = db.relationship('Group', back_populates='matches')
    white_player = db.relationship('Player', foreign_keys=[white_player_id], back_populates='white_matches')
    black_player = db.relationship('Player', foreign_keys=[black_player_id], back_populates='black_matches')
    next_match = db.relationship('Match', remote_side=[id], backref='previous_matches', uselist=False)

    def get_winner_id(self):
        if self.result == MatchResult.WHITE_WIN or self.result == MatchResult.FORFEIT_BLACK:
            return self.white_player_id
        elif self.result == MatchResult.BLACK_WIN or self.result == MatchResult.FORFEIT_WHITE:
            return self.black_player_id
        return None

    def get_loser_id(self):
        if self.result == MatchResult.WHITE_WIN or self.result == MatchResult.FORFEIT_BLACK:
            return self.black_player_id
        elif self.result == MatchResult.BLACK_WIN or self.result == MatchResult.FORFEIT_WHITE:
            return self.white_player_id
        return None

    @property
    def to_dict(self):
        return {
            'id': self.id,
            'round': self.round,
            'knockout_round': self.knockout_round,
            'knockout_match_num': self.knockout_match_num,
            'white_player': self.white_player.name if self.white_player else None,
            'black_player': self.black_player.name if self.black_player else None,
            'result': self.result,
            'status': self.status,
            'next_match_id': self.next_match_id
        }
