from flask import Blueprint, render_template, request, jsonify, url_for, flash, redirect
from flask_login import login_required, current_user 
from datetime import datetime, timedelta
import pytz
from website.models import Registration, Status , User, db ,Notification  
# 1. Định nghĩa Blueprint với tên duy nhất
client_views = Blueprint('client_views', __name__)

@client_views.route('/')
@login_required
def home():
    vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    current_week = datetime.now(vietnam_tz).isocalendar()[1]
    
    confirmed_status = Status.query.filter_by(name='Đã xác nhận').first()
    
    registrations = []
    if confirmed_status:
        registrations = Registration.query.filter_by(
            week_number=current_week,
            status_id=confirmed_status.id
        ).all()

    schedule_data = {
        'Sáng': {'T2': [], 'T3': [], 'T4': [], 'T5': [], 'T6': [], 'T7': [], 'CN': []},
        'Chiều': {'T2': [], 'T3': [], 'T4': [], 'T5': [], 'T6': [], 'T7': [], 'CN': []}
    }
    
    all_days_in_week = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

    for reg in registrations:
        user_info = User.query.get(reg.user_id)
        if not user_info:
            continue
            
        user_name = getattr(user_info, 'user_name', getattr(user_info, 'username', 'Thành viên'))
        session = reg.session  
        raw_off_days = reg.selected_days  

        off_days_list = [d.strip().replace('Thứ ', 'T').replace('Chủ Nhật', 'CN') for d in raw_off_days.split(",")] if raw_off_days else []
        working_days = [d for d in all_days_in_week if d not in off_days_list]

        sessions_to_add = []
        if session == 'Cả tuần':
            sessions_to_add = ['Sáng', 'Chiều']
        elif session in schedule_data:
            sessions_to_add = [session]

        for s in sessions_to_add:
            for day in working_days:
                if day in schedule_data[s]:
                    schedule_data[s][day].append(user_name)
    working_counts = {day: 0 for day in all_days_in_week}
    
   
    return render_template('clients/client_home.html', user=current_user, schedule_data=schedule_data)

@client_views.route('/shift')
@login_required 
def client_shift():
    vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    current_week = datetime.now(vietnam_tz).isocalendar()[1]
    
    confirmed_status = Status.query.filter_by(name='Đã xác nhận').first()
    
    registrations = []
    if confirmed_status:
        registrations = Registration.query.filter_by(
            week_number=current_week,
            status_id=confirmed_status.id
        ).all()

    all_days_in_week = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    
    # Khởi tạo bộ đếm số lượng đi làm cho từng ngày
    working_counts = {day: 0 for day in all_days_in_week}
    total_capacity = 4  

    for reg in registrations:
        raw_off_days = reg.selected_days  
        off_days_list = [d.strip().replace('Thứ ', 'T').replace('Chủ Nhật', 'CN') for d in raw_off_days.split(",")] if raw_off_days else []
        
        # Những ngày không nằm trong danh sách nghỉ là ngày đi làm
        working_days = [d for d in all_days_in_week if d not in off_days_list]

        for day in working_days:
            if day in working_counts:
                working_counts[day] += 1
    allowed_off_days = getattr(current_user, 'allowed_off_days', 2)
    return render_template(
        'clients/client_shift.html', 
        user=current_user, 
        working_counts=working_counts, 
        total_capacity=total_capacity, 
        allowed_off_days=allowed_off_days
    )

@client_views.route('/register-schedule', methods=['POST'])
@login_required
def register_schedule():
    from website import db
    
    try:
        data = request.get_json()
        selected_off_days = data.get('days', [])
        allowed_limit = getattr(current_user, 'allowed_off_days', 2)
        if len(selected_off_days) != allowed_limit:
             return jsonify({
                 'status': 'error', 
                 'message': 'Vui lòng chọn chính xác 2 ngày không trực!'
             }), 400

        string_off_days = ",".join(selected_off_days)
        string_shifts = "Cả tuần" # Giá trị mặc định vì đã bỏ chọn buổi
        
        vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        current_date = datetime.now(vietnam_tz)
        current_week = current_date.isocalendar()[1]
        
        existing_reg = Registration.query.filter_by(
            user_id=current_user.id, 
            week_number=current_week
        ).first()
        
        if existing_reg:
            return jsonify({
                'status': 'error', 
                'message': 'Bạn đã đăng ký lịch tuần này rồi!'
            }), 400
        # 👉 LOGIC KIỂM TRA SỐ LƯỢNG TỐI ĐA 3 NGƯỜI CHO CÁC NGÀY ĐI LÀM
        all_days_in_week = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
        # Chuẩn hóa ngày nghỉ do user chọn
        off_days_normalized = [d.strip().replace('Thứ ', 'T').replace('Chủ Nhật', 'CN') for d in selected_off_days]
        # Các ngày user sẽ đi làm trong tuần này
        user_working_days = [d for d in all_days_in_week if d not in off_days_normalized]

        # Lấy tất cả các đăng ký ĐÃ ĐƯỢC XÁC NHẬN trong tuần này
        confirmed_status = Status.query.filter_by(name='Đã xác nhận').first()
        if confirmed_status:
            confirmed_regs = Registration.query.filter_by(
                week_number=current_week,
                status_id=confirmed_status.id
            ).all()

            # Đếm số lượng người hiện đang đi làm thực tế theo từng ngày
            current_counts = {day: 0 for day in all_days_in_week}
            for reg in confirmed_regs:
                if reg.selected_days:
                    r_off = [d.strip().replace('Thứ ', 'T').replace('Chủ Nhật', 'CN') for d in reg.selected_days.split(",")]
                    r_work = [d for d in all_days_in_week if d not in r_off]
                    for d in r_work:
                        if d in current_counts:
                            current_counts[d] += 1

            # Kiểm tra xem ngày nào user muốn đi làm mà đã đạt ngưỡng tối đa (3 người) chưa
            MAX_CAPACITY = 3
            for day in user_working_days:
                if current_counts.get(day, 0) >= MAX_CAPACITY:
                    return jsonify({
                        'status': 'error',
                        'message': f'Ngày {day} đã đủ số lượng tối đa ({MAX_CAPACITY} người). Vui lòng chọn ngày nghỉ khác!'
                    }, 400)

        # 👉 1. Tìm hoặc tạo trạng thái 'Chờ xác nhận' trong bảng Status
        pending_status = Status.query.filter_by(name='Chờ xác nhận').first()
        if not pending_status:
            pending_status = Status(name='Chờ xác nhận')
            db.session.add(pending_status)
            db.session.commit()
        
        # 👉 2. Truyền status_id vào khi khởi tạo Registration
        new_registration = Registration(
            selected_days=string_off_days,
            session=string_shifts,
            week_number=current_week,
            created_at=current_date,
            user_id=current_user.id,
            status_id=pending_status.id  # 👈 Bổ sung dòng này để hết lỗi NOT NULL
        )
        db.session.add(new_registration)
        db.session.commit()
        
        return jsonify({
            'status': 'success', 
            'message': 'Đăng ký thành công!'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500
    
@client_views.route('/DetailShift')
@login_required
def client_detailshift(): 
    vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    now = datetime.now(vietnam_tz)
    current_week = now.isocalendar()[1]
    current_year = now.year
    
    all_regs = Registration.query.filter_by(user_id=current_user.id)\
                .order_by(Registration.week_number.desc()).all()
    
    upcoming_regs = []
    history_regs = []
    
    all_days_in_week = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    
    for reg in all_regs:
        if reg.selected_days:
            off_days_list = [d.strip() for d in reg.selected_days.split(",")]
            reg.working_days = [day for day in all_days_in_week if day not in off_days_list]
        else:
            reg.working_days = []
        # Kiểm tra xem lịch này đã được admin xác nhận chưa hoặc đã qua tuần chưa
        is_confirmed = reg.status_obj and reg.status_obj.name == 'Đã xác nhận'
        is_past_week = reg.week_number < current_week # (hoặc điều kiện thời gian của em)
        
        # Nếu đã xác nhận HOẶC đã qua tuần cũ thì cho rớt xuống bảng Lịch sử (history_regs)
      
        if is_confirmed or is_past_week:
            history_regs.append(reg)
        else:
            upcoming_regs.append(reg)
            
    return render_template('clients/client_DetailShift.html', 
                           user=current_user,
                           upcoming_regs=upcoming_regs, 
                           history_regs=history_regs)

@client_views.route('/request-change/<int:id>', methods=['POST'])
@login_required
def request_change_shift(id):
    reg = Registration.query.get_or_404(id)
    
    # Kiểm tra xem có đúng là lịch của user hiện tại không
    if reg.user_id != current_user.id:
        flash('Bạn không có quyền thực hiện thao tác này.', 'danger')
        return redirect(url_for('client.client_detailshift'))
        
    reason = request.form.get('reason')
    
    # Ở đây em có thể lưu yêu cầu vào bảng thông báo (Notification), bảng yêu cầu đổi lịch riêng, 
    # hoặc cập nhật trạng thái tạm thời, gửi email/tin nhắn cho Admin tùy theo cấu trúc database của dự án.
    # Ví dụ tạm thời hiển thị thông báo thành công:
    
    flash(f'Đã gửi phiếu thay đổi lịch tuần {reg.week_number} thành công đến Admin!', 'success')
    return redirect(url_for('client.client_detailshift'))

@client_views.route('/edit-shift/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_shift(id):
    reg = Registration.query.get_or_404(id)
    
    if reg.user_id != current_user.id:
        flash('Bạn không có quyền chỉnh sửa lịch này.', 'danger')
        return redirect(url_for('client_views.client_detailshift'))
        
    if request.method == 'POST':
        # Lấy giá trị từ dropdown 2 ngày nghỉ
        d1 = request.form.get('day_1')
        d2 = request.form.get('day_2')
        days_list = [d for d in [d1, d2] if d]
        
        # Cập nhật thông tin lịch
        reg.selected_days = ", ".join(days_list) if days_list else ""
        reg.session = request.form.get('session', 'Cả tuần')
        
        # Đánh dấu trạng thái là đang chờ duyệt (nếu bảng của em có cột status)
        reg.status = 'pending' 
        
        # Ghi nhận thời gian thay đổi hiện tại
        current_time_str = datetime.now().strftime('%d/%m/%Y lúc %H:%M')
        
        # TẠO THÔNG BÁO GỬI CHO ADMIN (Dạng 1: Chờ duyệt - kèm thời gian thay đổi)
        # Tạo thông báo gửi cho Admin (Dạng chờ duyệt kèm thời gian)
        notif = Notification(
            user_id=current_user.id,
            title="Yêu cầu sửa lịch trực (Chờ duyệt)",
            message=f"Học viên {current_user.user_name} vừa thay đổi lịch trực tuần {reg.week_number} vào lúc {current_time_str}.",
            status='pending'
        )
        db.session.add(notif)
        
        db.session.commit()
        
        flash('Cập nhật lịch thành công và đã gửi yêu cầu chờ duyệt!', 'success')
        return redirect(url_for('client_views.client_detailshift'))
        
    return render_template('clients/client_edit_shift.html', reg=reg)