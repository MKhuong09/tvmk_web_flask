from flask import Blueprint, render_template
from flask_login import login_required, current_user
from .models import User, Registration
from algorithms.schedule_agent import DayOfWeek, ScheduleAgent, UserData, convert_day_to_numeric


admin_views = Blueprint('admin_views', __name__)
@admin_views.route('/admin/home')
@login_required
def admin_home():
    # 1. Tổng số dân quân hệ thống (Đếm tổng tài khoản)
    total_people = User.query.count()
    
    # Lấy toàn bộ danh sách tài khoản để duyệt trạng thái đăng ký thực tế
    all_users = User.query.all()
    
    registered = 0
    not_registered = 0

    for user in all_users:
        # Lấy thông tin đăng ký của từng người
        reg = Registration.query.filter_by(user_id=user.id).first()
        
        # Một người chỉ được tính là ĐÃ ĐĂNG KÝ 
        # khi có bản ghi VÀ các trường chọn ngày (selected_days), chọn buổi (session) KHÔNG BỊ TRỐNG
        if reg and reg.selected_days and reg.session:
            registered += 1
        else:
            not_registered += 1

    # 2. Các ô chỉ số tiến độ phân công lịch làm
    total_schedule = total_people  # Tổng số lịch cần quản lý dựa trên danh sách người
    week_schedule = total_people   # Tiến độ lịch làm trong tuần

    return render_template(
        'admin/admin_home.html', 
        user=current_user,
        total_people=total_people,
        total_schedule=total_schedule,
        week_schedule=week_schedule,
        registered=registered,
        not_registered=not_registered
    )


@admin_views.route('/admin/scheduleList')
@login_required
def admin_scheduleList():
    all_users = User.query.all()
    schedules_data = []
    
    for user in all_users:
        reg = Registration.query.filter_by(user_id=user.id).order_by(Registration.id.desc()).first()
        if reg:
            schedules_data.append({
                "ho_ten": user.user_name,
                "gmail": user.email,
                "created_at": reg.created_at.strftime('%d/%m/%Y %H:%M') if reg.created_at else None,
                "selected_days": reg.selected_days,
                "session": reg.session
            })
        else:
            schedules_data.append({
                "ho_ten": user.user_name,
                "gmail": user.email,
                "created_at": None,
                "selected_days": None,
                "session": None
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
    if reg and reg.selected_days:
        for day in reg.selected_days.split(','):
            numeric_day = convert_day_to_numeric(day)
            if numeric_day >= DayOfWeek.MONDAY.value and numeric_day <= DayOfWeek.SUNDAY.value:
                registration_days.append(numeric_day)
    return registration_days

def get_users_data() -> list:
    users_data = []
    for user in User.query.all():
        users_data.append(UserData(
            name=user.user_name,
            email=user.email,
            role_id=user.role_id,
            userID=user.id,
            unavailable_days=get_user_registration_days(user.id)
        ))
    return users_data

def generate_schedule(num_days: int, num_users_per_day: int) -> dict:
    users_data = get_users_data()
    schedule_agent = ScheduleAgent(users=users_data, NumOfSchedDays=num_days, NumOfUsersPerDay=num_users_per_day)
    schedule = schedule_agent.create_schedule(max_days_per_user=2)
    return schedule