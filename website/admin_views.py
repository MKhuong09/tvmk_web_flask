from flask import Blueprint, render_template, redirect, request, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func
from .models import db, User, Registration, Status
from datetime import datetime
import pytz

admin_views = Blueprint('admin_views', __name__)

# Hàm phụ trợ: Chuyển đổi danh sách ngày nghỉ thành danh sách ngày đi làm thực tế
def get_working_days(selected_days_str):
    if not selected_days_str or selected_days_str == "--":
        return "--"
    
    # Các ngày chuẩn trong tuần
    all_days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    
    # Tách chuỗi ngày người dùng nhập (ví dụ: "T3,T4")
    excluded_days = [d.strip().upper() for d in selected_days_str.split(",")]
    
    # Lọc ra những ngày KHÔNG nằm trong danh sách nghỉ
    working_days = [day for day in all_days if day not in excluded_days]
    
    # Trả về chuỗi các ngày đi làm thực tế
    return ", ".join(working_days) if working_days else "Không có ngày làm"


@admin_views.route('/home')
@login_required
def admin_home():
    total_people = User.query.count()
    
    all_users = User.query.all()
    registered = 0
    not_registered = 0

    for user in all_users:
        reg = Registration.query.filter_by(user_id=user.id).order_by(Registration.id.desc()).first()
        
        if reg and reg.selected_days and reg.session:
            registered += 1
        else:
            not_registered += 1

    total_schedule = total_people  
    week_schedule = total_people   

    return render_template(
        'admin/admin_home.html', 
        user=current_user,
        total_people=total_people,
        total_schedule=total_schedule,
        week_schedule=week_schedule,
        registered=registered,
        not_registered=not_registered
    )


@admin_views.route('/scheduleList')
@login_required
def admin_scheduleList():
    registrations = Registration.query.order_by(Registration.id.desc()).all()
    
    schedules_data = []
    for reg in registrations:
        user_info = User.query.get(reg.user_id)
        
        # Tự động quy đổi từ ngày nghỉ sang ngày đi làm thực tế
        actual_days = get_working_days(reg.selected_days)
        
        schedules_data.append({
            "id": reg.id,
            "ho_ten": user_info.user_name if user_info else "Không rõ",
            "gmail": user_info.email if user_info else "Không rõ",
            "created_at": reg.created_at.strftime('%d/%m/%Y %H:%M') if reg.created_at else None,
            "selected_days": actual_days,  # Hiển thị các ngày làm việc thực tế lên bảng
            "session": reg.session,
            "status_name": reg.status_obj.name if reg.status_obj else "Chờ xác nhận"
        })
            
    return render_template(
        'admin/admin_scheduleList.html', 
        schedules=schedules_data, 
        user=current_user
    )


@admin_views.route('/approve-schedule/<int:reg_id>', methods=['POST'])
@login_required
def approve_schedule(reg_id):
    registration = Registration.query.get_or_404(reg_id)
    
    # 1. Thay vì tìm 'Đã xác nhận', ta tìm/tạo trạng thái 'Đã duyệt'
    approved_status = Status.query.filter_by(name='Đã duyệt').first()
    if not approved_status:
        approved_status = Status(name='Đã duyệt')
        db.session.add(approved_status)
        db.session.commit()
    
    try:
        # 2. Chuyển trạng thái đơn này thành 'Đã duyệt' (chưa hiện lên client vội)
        registration.status_id = approved_status.id
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Đã duyệt đơn thành công!'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_views.route('/generate-schedule', methods=['POST'])
@login_required
def generate_schedule():
    if current_user.role_id != 1:  # Kiểm tra quyền Admin
        flash('Bạn không có quyền thực hiện chức năng này!', 'danger')
        return redirect(url_for('admin_views.admin_home'))

    try:
        vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        current_week = datetime.now(vietnam_tz).isocalendar()[1]

        # Lấy trạng thái 'Đã duyệt' và trạng thái hiển thị cuối cùng 'Đã xác nhận'
        approved_status = Status.query.filter_by(name='Đã duyệt').first()
        confirmed_status = Status.query.filter_by(name='Đã xác nhận').first()
        
        if not confirmed_status:
            confirmed_status = Status(name='Đã xác nhận')
            db.session.add(confirmed_status)
            db.session.commit()

        if not approved_status:
            flash('Không tìm thấy danh sách nào ở trạng thái "Đã duyệt" để generate!', 'warning')
            return redirect(url_for('admin_views.admin_scheduleList'))

        # 👉 QUAN TRỌNG: Chỉ lấy những lịch CỦA TUẦN NÀY và ĐÃ ĐƯỢC ADMIN DUYỆT trước đó
        approved_regs = Registration.query.filter_by(
            status_id=approved_status.id,
            week_number=current_week
        ).all()
        
        if not approved_regs:
            flash('Không có lịch nào đã duyệt của tuần này để generate!', 'warning')
            return redirect(url_for('admin_views.admin_scheduleList'))

        # Tiến hành chuyển tất cả lịch từ 'Đã duyệt' sang 'Đã xác nhận' (Hiển thị lên client)
        for reg in approved_regs:
            reg.status_id = confirmed_status.id
            
        db.session.commit()
        flash(f'Generate thành công {len(approved_regs)} lịch trực tuần {current_week} lên trang client!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi generate lịch: {str(e)}', 'danger')

    return redirect(url_for('admin_views.admin_scheduleList'))


@admin_views.route('/request')
@login_required
def admin_request():
    registrations = Registration.query.order_by(Registration.id.desc()).all()
    schedules_data = []
    
    for reg in registrations:
        user_info = User.query.get(reg.user_id)
        
        # Áp dụng logic chuyển đổi ngày làm việc cho trang request
        actual_days = get_working_days(reg.selected_days)
        
        schedules_data.append({
            "id": reg.id,
            "ho_ten": user_info.user_name if user_info else "Không rõ",
            "gmail": user_info.email if user_info else "Không rõ",
            "created_at": reg.created_at.strftime('%d/%m/%Y %H:%M') if reg.created_at else None,
            "selected_days": actual_days,  # Hiển thị các ngày làm việc thực tế lên bảng
            "session": reg.session,
            "status_name": reg.status_obj.name if reg.status_obj else "Chờ xác nhận"
        })
            
    return render_template(
        'admin/admin_request.html', 
        schedules=schedules_data, 
        user=current_user
    )
@admin_views.route('/user-detail/<int:id>')
@login_required
def admin_user_detail(id):
    if current_user.role_id != 1:
        flash('Bạn không có quyền truy cập!', 'danger')
        return redirect(url_for('admin_views.admin_home'))
        
    target_user = User.query.get_or_404(id)
    return render_template('admin/admin_user_detail.html', target_user=target_user, user=current_user)
# Route cho phép Admin cập nhật số ngày nghỉ của user
@admin_views.route('/update-off-days/<int:user_id>', methods=['POST'])
@login_required 
def update_off_days(user_id):
    user = User.query.get_or_404(user_id)
    
    new_limit = request.form.get('allowed_off_days', type=int)
    
    if new_limit is not None and new_limit >= 2:
        user.allowed_off_days = new_limit
        db.session.commit()
        flash(f'Đã cập nhật số ngày nghỉ cho {user.user_name} thành {new_limit} ngày.', 'success')
    else:
        flash('Giá trị ngày nghỉ không hợp lệ!', 'danger')
        
    # Sửa lại đoạn redirect về đúng tên trang hiển thị danh sách admin_usershift của em (Ví dụ: admin_users hoặc tên route tương ứng)
    return redirect(url_for('admin_views.admin_users'))

@admin_views.route('/users')
@login_required
def admin_users():
    if current_user.role_id != 1:
        flash('Bạn không có quyền truy cập!', 'danger')
        return redirect(url_for('admin_views.admin_home'))
    
    users = User.query.all()
    return render_template('admin/admin_usershift.html', users=users, user=current_user)