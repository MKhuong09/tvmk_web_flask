from flask import Flask, app,send_from_directory
from flask_sqlalchemy import SQLAlchemy
from os import path
from flask_login import LoginManager
import os
from flask_migrate import Migrate

db = SQLAlchemy()
Migrate = Migrate()
DB_NAME = "database.db"

def create_app():
    #Create Flask app and set up configurations
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'MK dep trai Nhat Tren The Gioi va __ Giau Co va se MuA duoc Xe hoi 31ty07trieu2001k @@'
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_NAME}'
    db.init_app(app)
    Migrate.init_app(app, db) # Khởi tạo Flask-Migrate với ứng dụng và cơ sở dữ liệu

    @app.route('/Content/<path:filename>')
    def serve_content(filename):
       
        return send_from_directory(os.path.join(app.root_path, 'Content'), filename)

    @app.route('/fonts/<path:filename>')
    def serve_fonts(filename):
        
        return send_from_directory(os.path.join(app.root_path, 'fonts'), filename)

    @app.route('/Scripts/<path:filename>')
    def serve_scripts(filename):
        
        return send_from_directory(os.path.join(app.root_path, 'Scripts'), filename)
    
    # Register Blueprints
    from .views import views
    from .auth import auth
    from .admin_views import admin_views
    from .client_views import client_views
    # from .ChatBot.chatbot_views import chatbot_views
    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/auth')
    app.register_blueprint(admin_views, url_prefix='/admin')
    app.register_blueprint(client_views, url_prefix='/client')
    # app.register_blueprint(chatbot_views, url_prefix='/chatbot')
    # Import models to create database tables
    from .models import User, Note,Registration
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
            from website import db
            from .models import Role,User,Status
            from werkzeug.security import generate_password_hash

            # 1. Tạo cấu trúc các bảng vật lý từ cấu trúc đã đăng ký
            db.create_all()
            print('Created Database!')
            
            # 2. Kiểm tra dữ liệu và chèn các Role mặc định (ĐÃ ĐƯỢC ĐƯA VÀO TRONG KHỐI WITH)
            if not Role.query.first():
                admin_role = Role(id=1, name='Quản trị viên')
                client_role = Role(id=2, name='Dân quân')
                staff_role = Role(id=3, name='Admin')

                db.session.add_all([admin_role, client_role, staff_role])
                db.session.commit()
                print('Successfully initialized default Roles (Quản trị viên, Dân quân, Admin)!')
            if not User.query.filter_by(user_name="DongLam123").first():
                hashed_pw1 = generate_password_hash("123", method='pbkdf2:sha256')
                admin1 = User(
                    email="donglam123@gmail.com", 
                    user_name="DongLam123", 
                    password=hashed_pw1, 
                    role_id=1
                )
                db.session.add(admin1)
                print("Đã tạo tự động Admin 1 (DongLam123 / MK: 123)")

            # Kiểm tra và tạo Admin 2: MKhuong123
            if not User.query.filter_by(user_name="MKhuong123").first():
                hashed_pw2 = generate_password_hash("123", method='pbkdf2:sha256')
                admin2 = User(
                    email="MKhuong123@gmail.com", 
                    user_name="MKhuong123", 
                    password=hashed_pw2, 
                    role_id=1
                )
                db.session.add(admin2)
                print("Đã tạo tự động Admin 2 (MKhuong123 / MK: 123)")

            db.session.commit()
        with app.app_context():
            if not Status.query.filter_by(name='Chờ xác nhận').first():
                db.session.add(Status(name='Chờ xác nhận'))
            if not Status.query.filter_by(name='Đã xác nhận').first():
                db.session.add(Status(name='Đã xác nhận'))
            db.session.commit()