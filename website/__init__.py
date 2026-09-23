from flask import Flask, send_from_directory
import os
import firebase_admin
from firebase_admin import credentials, firestore
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, current_user
from werkzeug.security import generate_password_hash
from .views import views


db = None

# Định nghĩa lớp User tương thích với Flask-Login khi dùng Firestore
class User(UserMixin):
    def __init__(self, uid, data):
        self.id = uid
        self.email = data.get('email')
        self.user_name = data.get('user_name')
        self.role_id = data.get('role_id')

def create_app():
    # 1. Khởi tạo kết nối Firebase Admin SDK
    if not firebase_admin._apps:
      current_dir = os.path.abspath(os.path.dirname(__file__))
      cred_path = os.path.join(current_dir, 'serviceAccountKey.json')

      cred = credentials.Certificate(cred_path)
      firebase_admin.initialize_app(cred)
    
    # 2. Khởi tạo Cloud Firestore Database Client
    global db
    db = firestore.client()
    
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'MK dep trai Nhat Tren The Gioi va __ Giau Co va se MuA duoc Xe hoi 31ty07trieu2001k @@'
    # app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_NAME}'
    app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', '465'))
    app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'true').lower() == 'true'
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', '')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', '')
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME'])
    # db.init_app(app)
    # Migrate.init_app(app, db) # Khởi tạo Flask-Migrate với ứng dụng và cơ sở dữ liệu
    
    # Định nghĩa các đường dẫn tĩnh
    @app.route('/Content/<path:filename>')
    def serve_content(filename):
        return send_from_directory(os.path.join(app.root_path, 'Content'), filename)

    @app.route('/fonts/<path:filename>')
    def serve_fonts(filename):
        return send_from_directory(os.path.join(app.root_path, 'fonts'), filename)

    @app.route('/Scripts/<path:filename>')
    def serve_scripts(filename):
        return send_from_directory(os.path.join(app.root_path, 'Scripts'), filename)

    # 3. Đăng ký các Blueprints
    from .auth import auth
    
    from .admin_views import admin_views
    from .client_views import client_views
    from .client_request import client_request
    

    app.register_blueprint(auth, url_prefix='/auth')
    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(admin_views, url_prefix='/admin')
    app.register_blueprint(client_views, url_prefix='/client')
    app.register_blueprint(client_request, url_prefix='/client')

    # 4. Cấu hình Flask-Login
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login' # type: ignore
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            db_client = firestore.client()
            user_doc = db_client.collection('users').document(user_id).get()
            if user_doc.exists:
                return User(user_id, user_doc.to_dict())
        except Exception:
            pass
        return None

    # 5. Xử lý bộ đếm thông báo (Notification) 
    @app.context_processor
    def inject_notifications():
        unread_count = 0
        if current_user.is_authenticated:
            try:
                db_client = firestore.client()
                query = db_client.collection('notifications').where('user_id', '==', current_user.id).where('is_read', '==', False)
                unread_count = len(list(query.stream()))
            except Exception:
                unread_count = 0
        return dict(unread_count=unread_count)

    # 6. Tự động kiểm tra và khởi tạo tài khoản Admin mặc định
    with app.app_context():
        try:
            db_client = firestore.client()
            # Kiểm tra xem đã có user nào mang quyền admin (role_id = 1) chưa
            admin_check = list(db_client.collection('users').where('role_id', '==', 1).limit(1).stream())
            
            if not admin_check:
                admin_data = {
                    'user_name': 'admin',
                    'email': 'admin@gmail.com',
                    'full_name': 'Quản Trị Viên',
                    'password': generate_password_hash('1234567', method='pbkdf2:sha256'),
                    'role_id': 1,  # Phân quyền Admin trong hệ thống
                    'allowed_off_days': 2,
                    'is_verified': True,
                }
                db_client.collection('users').add(admin_data)
                print("Đã tự động tạo tài khoản Admin thành công!")
            else:
                print("Tài khoản Admin đã tồn tại trong CSDL.")
        except Exception as e:
            print(f"Không thể khởi tạo admin tự động: {e}")

    return app