from datetime import datetime
import random
import time
from flask import Blueprint, flash, redirect, render_template, request, session, url_for, jsonify
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from firebase_admin import firestore
from .models import User
from .utils import send_mail_based_on_admin_config
from typing import Any

# Khởi tạo Firestore
db = firestore.client()

auth = Blueprint('auth', __name__)

@auth.route('/')
def index():
    return redirect('/login')

@auth.route('/login.html', methods=['GET', 'POST'])
@auth.route('/login', methods=['GET', 'POST'])
@auth.route('/api/login', methods=['POST','OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return jsonify({'success': True}), 200
    if request.method == 'POST':
        is_api = request.is_json or request.headers.get('Content-Type') == 'application/json'
        data = request.get_json() if is_api else request.form
        
        username = data.get('username')
        password = data.get('password')

        users_ref = db.collection('users').where('user_name', '==', username).limit(1).stream()
        user = None
        user_id = None
        for doc in users_ref:
            user = User(doc.id, doc.to_dict())
            user_id = doc.id
            break

        if user and check_password_hash(user.password, password):
            if is_api:
                return jsonify({
                    'success': True,
                    'message': 'Đăng nhập thành công',
                    'user_id': user_id,
                    'role_id': user.role_id
                }), 200
            else:
                
                login_user(user, remember=True)
                if user.role_id in [1, 3]:
                    return redirect(url_for('admin_views.admin_scheduleList'))
                else:
                    return redirect(url_for('client_views.home'))
        else:
            if is_api:
                return jsonify({'success': False, 'message': 'Sai tài khoản hoặc mật khẩu'}), 401
            else:
                flash('Sai tài khoản hoặc mật khẩu', category='error')
    return render_template('login.html', user=current_user)


@auth.route('/logout')
@login_required
def logout():
  logout_user()
  return redirect(url_for('auth.login'))


@auth.route('/sign_up', methods=['GET', 'POST'])
@auth.route('/sign_up.html', methods=['GET', 'POST'])
@auth.route('/api/register', methods=['POST'])
@auth.route('/sign_up', methods=['GET', 'POST'])
@auth.route('/sign_up.html', methods=['GET', 'POST'])
@auth.route('/api/register', methods=['POST'])
def sign_up():
    if request.method == 'POST':
        is_api = request.is_json or request.headers.get('Content-Type') == 'application/json'
        data = request.get_json() if is_api else request.form

        username = (data.get('username') or '').strip()
        email = (data.get('email') or '').strip().lower()
        full_name = (data.get('full_name') or '').strip()
        password = data.get('password') or ''

        existing_users = list(
            db.collection('users')
            .where('user_name', '==', username)
            .limit(1)
            .stream()
        )
        existing_email_users = []

        if email:
            existing_email_users = list(
                db.collection('users')
                .where('email', '==', email)
                .limit(1)
                .stream()
            )
        # Email được admin duyệt có document ID là địa chỉ email viết thường
        authorized_email_ref: Any = (
    db.collection('authorized_emails').document(email)
    if email else None
)
        authorized_email_doc = (
            authorized_email_ref.get()
            if authorized_email_ref else None
        )

        if not username or not email or not password:
            msg = 'Vui lòng nhập đầy đủ thông tin.'
        elif existing_users:
            msg = 'Tên đăng nhập đã tồn tại.'
        elif existing_email_users:
            msg = 'Email này đã được sử dụng.'
        elif len(password) < 7:
            msg = 'Mật khẩu phải có ít nhất 7 ký tự.'
        elif not authorized_email_doc or not authorized_email_doc.exists:
            msg = 'Email này chưa được admin cấp phép.'
        elif (authorized_email_doc.to_dict() or {}).get('is_used', False):
            msg = 'Email này đã được dùng để đăng ký.'
        else:
            msg = None

        if msg:
            if is_api:
                return jsonify({'success': False, 'message': msg}), 400

            flash(msg, category='error')
            return render_template('login.html', user=current_user)

        new_user_data = {
            'user_name': username,
            'email': email,
            'full_name': full_name,
            'password': generate_password_hash(password, method='pbkdf2:sha256'),
            'role_id': 2,
            'allowed_off_days': 2,
            'is_verified': True,
        }

        # Tạo tài khoản rồi đánh dấu email đã sử dụng
        db.collection('users').add(new_user_data)
        authorized_email_ref.delete()

        if is_api:
            return jsonify({
                'success': True,
                'message': 'Tạo tài khoản thành công!'
            }), 201

        flash('Tạo tài khoản thành công!', category='success')
        return redirect('/login')

    return render_template('login.html', user=current_user)
@auth.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
  if 'temp_user' not in session:
    flash('Phiên đăng ký đã hết hạn hoặc không tồn tại.', category='error')
    return redirect(url_for('auth.sign_up'))

  stored_user = session['temp_user']

  if request.method == 'POST':
    user_otp = request.form.get('otp')

    current_time = datetime.utcnow().timestamp()
    if current_time > stored_user['otp_expiry']:
      flash('Mã OTP đã hết hạn (quá 5 phút). Vui lòng đăng ký lại để nhận mã mới.', category='error')
      session.pop('temp_user', None)
      return redirect(url_for('auth.sign_up'))

    if user_otp == stored_user['otp']:
      # Chuẩn bị data user chính thức
      new_user_data = {
          'email': stored_user['email'],
          'user_name': stored_user['username'],
          'full_name': stored_user['full_name'],
          'password': stored_user['password'],
          'role_id': 2,
          'allowed_off_days': 2,
          'is_verified': True,
      }

      # Đẩy lên Firestore và nhận lại Document ID vừa sinh ra
      _, doc_ref = db.collection('users').add(new_user_data)

      # Tạo instance User 
      user_obj = User(doc_ref.id, new_user_data)

      session.pop('temp_user', None)
      login_user(user_obj, remember=True)
      flash('Xác thực tài khoản thành công! Chào mừng bạn đến với hệ thống 💖', category='success')
      return redirect(url_for('client_views.home'))
    else:
      flash('Mã OTP không chính xác, vui lòng thử lại.', category='error')

  return render_template('verify_otp.html', user=current_user)


@auth.route('/send-otp-ajax', methods=['POST'])
def send_otp_ajax():
  data = request.get_json()
  email = data.get('email')

  if not email:
    return {'success': False, 'message': 'Chưa nhập email!'}

  otp = str(random.randint(100000, 999999))
  expiry_time = time.time() + 300

  temp_user = session.get('temp_user', {})
  temp_user['email'] = email
  temp_user['otp'] = otp
  temp_user['otp_expiry'] = expiry_time
  session['temp_user'] = temp_user

  subject = 'Mã xác nhận tài khoản - Squad Guard Duty Roster'
  recipients = [email]
  body = f'Mã OTP xác nhận đăng ký tài khoản của bạn là: {otp}\nMã này có hiệu lực trong vòng 5 phút. 🌸'

  email_sent = send_mail_based_on_admin_config(subject, recipients, body)
  if email_sent:
    return {'success': True, 'message': 'Đã gửi mã OTP thành công!'}
  else:
    return {'success': False, 'message': 'Không thể gửi email, vui lòng kiểm tra lại cấu hình.'}