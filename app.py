import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from flask_login import LoginManager
from werkzeug.middleware.proxy_fix import ProxyFix

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('error.log')
    ]
)

class Base(DeclarativeBase):
    pass

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "chess_tournament_secret_key")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # needed for url_for to generate with https

# Database configuration
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///chess_tournament.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    'pool_pre_ping': True,
    "pool_recycle": 300,
}

# Initialize database
db = SQLAlchemy(app, model_class=Base)

# Initialize login manager
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

# Error handler
@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f'Server Error: {error}')
    db.session.rollback()
    return 'Internal Server Error', 500

# Create tables
with app.app_context():
    import models  # noqa: F401
    db.create_all()
    logging.info("Database tables created")

# Import user loader after models are defined
from models import Admin, Player

@login_manager.user_loader
def load_user(user_id):
    # Check if this is an admin (admin IDs are integers)
    try:
        user_id_int = int(user_id)
        admin = Admin.query.get(user_id_int)
        if admin:
            return admin
    except ValueError:
        pass
    
    # If not an admin, try to find a player with this code
    return Player.query.filter_by(access_code=user_id).first()
