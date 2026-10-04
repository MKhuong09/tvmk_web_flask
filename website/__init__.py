import os
from flask import Flask, send_from_directory
import json
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, current_user
from flask_socketio import SocketIO  
from werkzeug.security import generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
import firebase_admin
from firebase_admin import credentials, firestore
from .views import views

db = None
# Khởi tạo instance của SocketIO
socketio = SocketIO()

# Định nghĩa lớp User tương thích với Flask-Login khi dùng Firestore
class User(UserMixin):
    def __init__(self, uid, data):
        self.id = uid
        self.email = data.get('email')
        self.user_name = data.get('user_name')
        self.role_id = data.get('role_id')

def create_app():
    global db
    app = Flask(__name__)
    CORS(app)
    app.config['SECRET_KEY'] = 'MK dep trai Nhat Tren The Gioi va __ Giau Co va se MuA duoc Xe hoi 31ty07trieu2001k @@'

    # 1. Khởi tạo kết nối Firebase Admin SDK
    if not firebase_admin._apps:
        current_dir = os.path.abspath(os.path.dirname(__file__))
        cred_path = os.path.join(current_dir, 'serviceAccountKey.json')

        cred = credentials.Certificate(cred_path)
    # 1. Khởi tạo kết nối Firebase Admin SDK
    if not firebase_admin._apps:
        service_account_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON', '')
        if service_account_json:
            try:
                service_account_info = json.loads(service_account_json)
            except json.JSONDecodeError as error:
                raise RuntimeError('FIREBASE_SERVICE_ACCOUNT_JSON must contain valid JSON.') from error
            cred = credentials.Certificate(service_account_info)
        else:
            current_dir = os.path.abspath(os.path.dirname(__file__))
            cred_path = os.path.join(current_dir, 'serviceAccountKey.json')
            if not os.path.isfile(cred_path):
                raise RuntimeError(
                    'Set FIREBASE_SERVICE_ACCOUNT_JSON or provide website/serviceAccountKey.json.'
                )
            cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    
    # 2. Khởi tạo Cloud Firestore Database Client
    db = firestore.client()

    # Khởi tạo SocketIO gắn vào Flask app
    socketio.init_app(app, cors_allowed_origins="*")
        
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

    @app.route('/healthz')
    def health_check():
        return {'status': 'ok'}, 200

    # 3. Đăng ký các Blueprints
    from .auth import auth
    from .admin_views import admin_views
    from .client_views import client_views
    from .client_request import client_request
    from .api import api_bp
    
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(auth, url_prefix='/')
    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(admin_views, url_prefix='/admin')
    app.register_blueprint(client_views, url_prefix='/client')
    app.register_blueprint(client_request, url_prefix='/client')

    # Import file events để đăng ký xử lý các sự kiện Socket
    with app.app_context():
        from . import events

    # 4. Cấu hình Flask-Login
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login' # type: ignore
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            db_client = firestore.client()
            user_doc = db_client.collection('users').document(user_id).get()
            if user_doc and getattr(user_doc, 'exists', False):
                to_dict_fn = getattr(user_doc, 'to_dict', None)
                if callable(to_dict_fn):
                    return User(user_id, to_dict_fn())
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
            admin_check = list(db_client.collection('users').where('role_id', '==', 1).limit(1).stream())
            
            if not admin_check:
                admin_username = os.getenv('BOOTSTRAP_ADMIN_USERNAME')
                admin_email = os.getenv('BOOTSTRAP_ADMIN_EMAIL')
                admin_password = os.getenv('BOOTSTRAP_ADMIN_PASSWORD')
                if not admin_username or not admin_email or not admin_password:
                    raise RuntimeError(
                        'Set BOOTSTRAP_ADMIN_USERNAME, BOOTSTRAP_ADMIN_EMAIL, and '
                        'BOOTSTRAP_ADMIN_PASSWORD to create the initial admin account.'
                    )
                admin_data = {
                    'user_name': 'admin',
                    'email': 'admin@gmail.com',
                    'full_name': 'Quản Trị Viên',
                    'password': generate_password_hash('1234567', method='pbkdf2:sha256'),
                    'role_id': 1, 
                    'allowed_off_days': 2,
                    'is_verified': True,
                }
                db_client.collection('users').document('bootstrap-admin').set(admin_data)
                print("Đã tự động tạo tài khoản Admin thành công!")
            else:
                print("Tài khoản Admin đã tồn tại trong CSDL.")
        except RuntimeError:
            raise
        except Exception as e:
            print(f"Không thể khởi tạo admin tự động: {e}")

    return app