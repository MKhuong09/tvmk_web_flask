from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from os import path
from flask_login import LoginManager

db = SQLAlchemy()
DB_NAME = "database.db"

def create_app():
    #Create Flask app and set up configurations
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'MK dep trai Nhat Tren The Gioi va __ Giau Co va se MuA duoc Xe hoi 31ty07trieu2001k @@'
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_NAME}'
    db.init_app(app)
    
    # Register Blueprints
    from .views import views
    from .auth import auth
    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/auth')
    # Import models to create database tables
    from .models import User, Note
    create_database(app)
    # Set up Flask-Login
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)
    # Define user loader for Flask-Login
    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))

    return app

def create_database(app):
    if not path.exists(path.join(path.dirname(__file__), DB_NAME)):
        with app.app_context():
            db.create_all()
        print('Created Database!')
