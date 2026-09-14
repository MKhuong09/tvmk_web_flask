from flask import Blueprint, render_template, redirect, request, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from .models import ScheduleOutput, User, Registration, Status, db
from algorithms.schedule_agent import DayOfWeek, ScheduleAgent, UserData, convert_day_to_numeric

from sqlalchemy import func
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
    
def get_user_registration_days(user_id: int) -> list:
    """
    Lấy danh sách các ngày mà người dùng đã đăng ký.
    
    Args:
        user_id (int): ID của người dùng.
        
    Returns:
        list: Danh sách các ngày đã đăng ký (dạng số nguyên).
    """
    reg = Registration.query.filter_by(user_id=user_id).first()
    registration_days = []
    day_names = {
        'T2': 'monday', 'T3': 'tuesday', 'T4': 'wednesday',
        'T5': 'thursday', 'T6': 'friday', 'T7': 'saturday', 'CN': 'sunday'
    }
    if reg and reg.selected_days:
        for day in reg.selected_days.split(','):
            normalized_day = day_names.get(day.strip().upper(), day)
            numeric_day = convert_day_to_numeric(normalized_day)
            if numeric_day >= DayOfWeek.MONDAY.value and numeric_day <= DayOfWeek.SUNDAY.value:
                registration_days.append(numeric_day)
    return registration_days

def get_users_data() -> list:
    users_data = []
    for user in User.query.all():
        users_data.append(UserData(
            name=user.user_name,
            email=user.email,
            userID=user.id,
            unavailable_days=get_user_registration_days(user.id),
            max_days_per_week=2
        ))
    return users_data

def RunScheduleAgent(num_days: int, num_users_per_day: int) -> ScheduleAgent:
    users_data = get_users_data()
    schedule_agent = ScheduleAgent(users=users_data, NumOfSchedDays=num_days, NumOfUsersPerDay=num_users_per_day)
    schedule_agent.create_schedule(max_days_per_user=2)
    return schedule_agent


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

    num_days = request.form.get('num_days', default=7, type=int)
    num_users_per_day = request.form.get('num_users_per_day', default=2, type=int)

    if num_days is None or num_days < 1:
        num_days = 7
    if num_users_per_day is None or num_users_per_day < 1:
        num_users_per_day = 2

    action = request.form.get('action_generate') or request.form.get('action_confirm') or request.form.get('action_cancel')
    print(f'generate_schedule action={action!r}, form={request.form.to_dict()}')

    try:
        vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        current_week = datetime.now(vietnam_tz).isocalendar()[1]

        approved_status = Status.query.filter_by(name='Đã duyệt').first()
        if action == 'generate':
            if not approved_status:
                flash('Không tìm thấy trạng thái "Đã duyệt"!', 'warning')
                return redirect(url_for('admin_views.admin_home'))

            approved_regs = Registration.query.filter_by(
                status_id=approved_status.id, week_number=current_week
            ).all()
            if not approved_regs:
                flash('Không có lịch nào đã duyệt của tuần này để generate!', 'warning')
                return redirect(url_for('admin_views.admin_home'))

            schedule = RunScheduleAgent(num_days, num_users_per_day).get_schedule()
            session['pending_schedule'] = {
                'week': current_week,
                'registrations': [reg.id for reg in approved_regs],
                'items': {
                    str(date): [user.userID for user in users]
                    for date, users in schedule.items()
                }
            }
            session.modified = True
            flash(f'Đã generate lịch tuần {current_week}. Nhấn OK để lưu hoặc Hủy để bỏ.', 'info')

        elif action == 'confirm':
            pending = session.get('pending_schedule')
            if not pending:
                flash('Không có kết quả lịch để lưu. Vui lòng generate trước.', 'warning')
                return redirect(url_for('admin_views.admin_home'))

            confirmed_status = Status.query.filter_by(name='Đã xác nhận').first()
            if not confirmed_status:
                confirmed_status = Status(name='Đã xác nhận')
                db.session.add(confirmed_status)
                db.session.flush()

            for date, user_ids in pending['items'].items():
                db.session.merge(ScheduleOutput(
                    date=date, userlist=','.join(map(str, user_ids))
                ))
            Registration.query.filter(Registration.id.in_(pending['registrations'])).update(
                {'status_id': confirmed_status.id}, synchronize_session=False
            )
            db.session.commit()
            session.pop('pending_schedule', None)
            flash(f'Đã lưu lịch tuần {pending["week"]} và xác nhận đăng ký.', 'success')

        elif action == 'cancel':
            session.pop('pending_schedule', None)
            flash('Đã hủy generate lịch.', 'warning')
        else:
            flash('Hành động không hợp lệ!', 'danger')
        
        
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi generate lịch: {str(e)}', 'danger')

    return redirect(url_for('admin_views.admin_home'))


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
    
@admin_views.route('/my-registration')
@login_required
def admin_registration():
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
        'admin/admin_registration.html',
        user=current_user,
        working_counts=working_counts,
        total_capacity=total_capacity,
        allowed_off_days=allowed_off_days
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
