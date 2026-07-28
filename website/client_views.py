from flask import Blueprint, render_template, request, jsonify, url_for
from flask_login import login_required, current_user 
from datetime import datetime, timedelta
import pytz
from website.ChatBot.chatbot_service import get_bot_response
from website.models import Registration # Import service ở trên cùng

# 1. Định nghĩa Blueprint với tên duy nhất
client_views = Blueprint('client_views', __name__)

@client_views.route('/')
@login_required
def home():
    return render_template('clients/client_home.html', user=current_user)

@client_views.route('/shift')
@login_required 
def client_shift():
    return render_template('clients/client_shift.html', user=current_user)

@client_views.route('/register-schedule', methods=['POST'])
@login_required
def register_schedule():
    from .models import Registration
    from website import db
    
    try:
        data = request.get_json()
        selected_days_list = data.get('days', [])
        selected_shifts_list = data.get('shifts', [])
        
        if not selected_days_list or not selected_shifts_list:
             return jsonify({'status': 'error', 'message': 'Vui lòng chọn đầy đủ ngày và ca trực!'}), 400

        string_days = ",".join(selected_days_list)
        string_shifts = ",".join([shift.title() for shift in selected_shifts_list])
        
        vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        current_date = datetime.now(vietnam_tz)
        current_week = current_date.isocalendar()[1]
        
        # Kiểm tra xem đã đăng ký chưa
        existing_reg = Registration.query.filter_by(
            user_id=current_user.id, 
            week_number=current_week
        ).first()
        
        if existing_reg:
            # Chặn không cho đăng ký tiếp
            return jsonify({
                'status': 'error', 
                'message': 'Bạn đã đăng ký lịch tuần này rồi! Vui lòng liên hệ quản trị viên để thay đổi.'
            }), 400
        
        # Chỉ tạo mới nếu chưa có
        new_registration = Registration(
            selected_days=string_days,
            session=string_shifts,
            week_number=current_week,
            created_at=current_date,
            user_id=current_user.id
        )
        db.session.add(new_registration)
        db.session.commit()
        
        return jsonify({
            'status': 'success', 
            'message': 'Đăng ký thành công!',
            'redirect_url': url_for('client_views.client_shift')
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    
@client_views.route('/DetailShift')
@login_required
def client_detailshift(): # Đã đổi tên từ client_shift thành client_detailshift
    vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    now = datetime.now(vietnam_tz)
    current_week = now.isocalendar()[1]
    current_year = now.year
    
    # Lấy lịch từ DB, sắp xếp theo tuần mới nhất
    all_regs = Registration.query.filter_by(user_id=current_user.id)\
                .order_by(Registration.week_number.desc()).all()
    
    upcoming_regs = []
    history_regs = []
    
    for reg in all_regs:
        reg_year = reg.created_at.year
        # Nếu tuần của lịch >= tuần hiện tại -> Sắp tới
        if reg_year > current_year or (reg_year == current_year and reg.week_number >= current_week):
            upcoming_regs.append(reg)
        else:
            history_regs.append(reg)
            
    return render_template('clients/client_DetailShift.html', 
                           user=current_user,
                           upcoming_regs=upcoming_regs, 
                           history_regs=history_regs)

# 2. Sử dụng đúng tên client_views để định nghĩa route chat
@client_views.route('/chat', methods=['POST'])
def chat():
    user_msg = request.json.get('message')
    bot_reply = get_bot_response(user_msg)
    return jsonify({"reply": bot_reply})