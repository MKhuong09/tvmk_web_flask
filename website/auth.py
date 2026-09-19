from datetime import datetime
import random
import time
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from firebase_admin import firestore
from .models import User
from .utils import send_mail_based_on_admin_config

# Khởi tạo Firestore
db = firestore.client()

auth = Blueprint('auth', __name__)

@auth.route('/')
def index():
    return redirect(url_for('auth.login'))

@auth.route('/login.html', methods=['GET', 'POST'])
@auth.route('/login', methods=['GET', 'POST'])
def login():
  if request.method == 'POST':
    username = request.form.get('username')
    password = request.form.get('password')
    users_ref = (
        db.collection('users').where('user_name', '==', username).limit(1).stream()
    )
    user = None
    for doc in users_ref:
      user = User(doc.id, doc.to_dict())
      break

    if user:
      if check_password_hash(user.password, password):
        login_user(user, remember=True)
        flash('Logged in successfully!', category='success')
        if user.role_id == 1 or user.role_id == 3:
          return redirect(url_for('admin_views.admin_scheduleList'))
        elif user.role_id == 2:
          return redirect(url_for('client_views.home'))
      else:
        flash('Incorrect password, try again.', category='error')
    else:
      flash('User not found.', category='error')

  return render_template('login.html', user=current_user)


@auth.route('/logout')
@login_required
def logout():
  logout_user()
  return redirect(url_for('auth.login'))


@auth.route('/sign-up', methods=['GET', 'POST'])
@auth.route('/sign_up.html', methods=['GET', 'POST'])
def sign_up():
  if request.method == 'POST':
    username = request.form.get('username')
    email = request.form.get('email')
    full_name = request.form.get('full_name')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')

    # Kiểm tra xem username đã tồn tại trên Firestore chưa
    existing_users = list(
        db.collection('users').where('user_name', '==', username).limit(1).stream()
    )

    if len(existing_users) > 0:
      flash('Tên đăng nhập đã tồn tại.', category='error')
    elif len(email) < 4:
      flash('Email phải có ít nhất 4 ký tự.', category='error')
    elif len(username) < 2:
      flash('Tên đăng nhập phải có ít nhất 2 ký tự.', category='error')
    elif password != confirm_password:
      flash('Mật khẩu xác nhận không khớp.', category='error')
    elif len(password) < 7:
      flash('Mật khẩu phải có ít nhất 7 ký tự.', category='error')
    else:
      # Chuẩn bị dữ liệu dưới dạng dictionary cho Firestore
      new_user_data = {
          'user_name': username,
          'email': email,
          'full_name': full_name,
          'password': generate_password_hash(password, method='pbkdf2:sha256'),
          'role_id': 2,
          'allowed_off_days': 2,
          'is_verified': True,
      }

      # Lưu trực tiếp lên Firestore collection 
      db.collection('users').add(new_user_data)

      flash('Tạo tài khoản thành công! Hãy đăng nhập nhé 🌸', category='success')
      return redirect(url_for('auth.login'))

  return render_template('sign_up.html', user=current_user)

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