import io
import calendar
from flask import Blueprint, current_app, render_template, redirect, request, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from flask import send_file

from mailAgent.mailbox import send_email
from .models import ScheduleOutput, User, Registration, Status, db
from algorithms.schedule_agent import DayOfWeek, ScheduleAgent, UserData, convert_day_to_numeric

from sqlalchemy import func
from datetime import datetime, timedelta
import pytz
from firebase_admin import firestore
from website.utils import send_mail_based_on_admin_config
from google.cloud.firestore import SERVER_TIMESTAMP
import pandas as pd

admin_views = Blueprint('admin_views', __name__)

def get_db():
    return firestore.client()

def get_working_days(selected_days_str):
    if not selected_days_str or selected_days_str == "--":
        return "--"
    all_days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    excluded_days = [d.strip().upper() for d in selected_days_str.split(",")]
    working_days = [day for day in all_days if day not in excluded_days]
    return ", ".join(working_days) if working_days else "Không có ngày làm"

def get_week_date_range(year, week_number):
    try:
        start_of_week = datetime.strptime(f'{year}-W{week_number}-1', "%Y-W%W-%u")
    except ValueError:
        first_day_of_year = datetime(year, 1, 1)
        start_of_week = first_day_of_year + timedelta(days=(week_number - 1) * 7 - first_day_of_year.weekday())
    
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_week = start_of_week + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return start_of_week, end_of_week


@admin_views.route('/home')
@login_required
def admin_home():
    db = get_db()
    users_ref = db.collection('users').stream()
    all_users = []
    for doc in users_ref:
        u_data = doc.to_dict() or {}
        u_data['id'] = doc.id
        all_users.append(u_data)
        
    total_people = len(all_users)
    registered = 0
    not_registered = 0

    vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    current_week = datetime.now(vietnam_tz).isocalendar()[1]

    for user in all_users:
        regs_ref = db.collection('registrations').where('user_id', '==', user['id']).where('week_number', '==', current_week).limit(1).stream()
        reg_list = list(regs_ref)
        
        if reg_list:
            reg_data = reg_list[0].to_dict() or {}
            if reg_data.get('selected_days') and reg_data.get('session'):
                registered += 1
            else:
                not_registered += 1
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
    if current_user.role_id != 1:
        flash('Bạn không có quyền truy cập trang này!', 'danger')
        return redirect(url_for('admin_views.admin_home'))

    now = datetime.now()
    current_year = request.args.get('year', default=now.year, type=int)
    default_week = now.isocalendar()[1]
    current_week = request.args.get('week', default=default_week, type=int)
    
    start_date, end_date = get_week_date_range(current_year, current_week)
    
    db = get_db()
    users_ref = db.collection('users').where('role_id', '!=', 1).stream()
    schedules_data = []
    
    for u_doc in users_ref:
        user_info = u_doc.to_dict() or {}
        user_id = u_doc.id
        
        raw_name = user_info.get('full_name') or user_info.get('user_name', 'Không rõ')
        short_name = raw_name.strip().split(" ")[-1] if raw_name else "Thành viên"
        
        regs_ref = db.collection('registrations').where('user_id', '==', user_id).where('week_number', '==', current_week).limit(1).stream()
        reg_list = list(regs_ref)
        
        reg_data = reg_list[0].to_dict() if reg_list else None
        reg_id = reg_list[0].id if reg_list else None
        
        actual_days = get_working_days(reg_data.get('selected_days')) if reg_data and reg_data.get('selected_days') else "--"
        
        status_name = "Chưa đăng ký"
        if reg_data and reg_data.get('status_id'):
            status_doc = db.collection('statuses').document(str(reg_data.get('status_id'))).get()
            if status_doc.exists:
                status_dict = status_doc.to_dict() or {}
                status_name = status_dict.get('name', 'Chưa đăng ký')

        created_at_str = "--"
        if reg_data and reg_data.get('created_at'):
            created_at_val = reg_data.get('created_at')
            if isinstance(created_at_val, datetime):
                created_at_str = created_at_val.strftime('%d/%m/%Y %H:%M')

        schedules_data.append({
            "id": reg_id,
            "ho_ten": raw_name,
            "ten_rut_gon": short_name,
            "gmail": user_info.get('email'),
            "ngay_chon": created_at_str,
            "selected_days": actual_days,
            "session": reg_data.get('session') if reg_data else "--",
            "status_name": status_name
        })
        
    prev_week = current_week - 1
    prev_year = current_year
    if prev_week < 1:
        prev_week = 52
        prev_year -= 1
        
    next_week = current_week + 1
    next_year = current_year
    if next_week > 52:
        next_week = 1
        next_year += 1
        
    return render_template(
        'admin/admin_scheduleList.html', 
        users_schedules=schedules_data,
        user=current_user,
        current_week=current_week,
        current_year=current_year,
        start_date=start_date,
        end_date=end_date,
        prev_week=prev_week,
        prev_year=prev_year,
        next_week=next_week,
        next_year=next_year
    )


@admin_views.route('/approve-schedule/<string:reg_id>', methods=['POST'])
@login_required
def approve_schedule(reg_id):
    if current_user.role_id != 1:
        return jsonify({'status': 'error', 'message': 'Bạn không có quyền thực hiện thao tác này!'}), 403

    try:
        db = get_db()
        reg_ref = db.collection('registrations').document(reg_id)
        if not reg_ref.get().exists:
            return jsonify({'status': 'error', 'message': 'Không tìm thấy thông tin đăng ký!'}), 404
        
        statuses_ref = db.collection('statuses').where('name', '==', 'Đã duyệt').limit(1).stream()
        status_list = list(statuses_ref)
        if not status_list:
            return jsonify({'status': 'error', 'message': 'Không tìm thấy trạng thái "Đã duyệt" trong CSDL!'}), 400
            
        approved_status_id = status_list[0].id
        reg_ref.update({'status_id': approved_status_id})
        
        return jsonify({'status': 'success', 'message': 'Đã duyệt lịch thành công!'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@admin_views.route('/decline-schedule/<int:reg_id>', methods=['POST'])
@login_required
def decline_schedule(reg_id):
    registration = Registration.query.get_or_404(reg_id)

    # 1. Tìm/tạo trạng thái 'Đã từ chối'
    declined_status = Status.query.filter_by(name='Đã từ chối').first()
    if not declined_status:
        declined_status = Status(name='Đã từ chối')
        db.session.add(declined_status)
        db.session.commit()

    try:
        # 2. Chuyển trạng thái đơn này thành 'Đã từ chối' (chưa hiện lên client vội)
        registration.status_id = declined_status.id
        db.session.commit()
        # Gửi email thông báo từ chối đến người dùng
        user = User.query.get(registration.user_id)
        if user and user.email:
            subject = "Thông báo từ chối đăng ký"
            body = f"Xin chào {user.user_name},\n\nĐơn đăng ký của bạn đã bị từ chối. Vui lòng liên hệ Ấp Đội Trưởng để biết thêm chi tiết. \
                Link đăng ký lịch: {url_for('main_views.register_schedule', _external=True)}\
                \n\nTrân trọng."
            send_email(current_app, [user.email], subject, body)
            
        return jsonify({'status': 'success', 'message': 'Đã từ chối đơn thành công!'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@admin_views.route('/generate-schedule', methods=['POST'])
@login_required
def generate_schedule():
    if current_user.role_id != 1:
        flash('Bạn không có quyền thực hiện chức năng này!', 'danger')
        return redirect(url_for('admin_views.admin_home'))

    action = request.form.get('action_generate') or request.form.get('action_confirm') or request.form.get('action_cancel')
    db = get_db()

    try:
        vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
        current_week = datetime.now(vietnam_tz).isocalendar()[1]

        statuses_ref = db.collection('statuses').where('name', '==', 'Đã duyệt').limit(1).stream()
        status_list = list(statuses_ref)
        approved_status_id = status_list[0].id if status_list else None

        if action == 'generate':
            if not approved_status_id:
                flash('Không tìm thấy trạng thái "Đã duyệt"!', 'warning')
                return redirect(url_for('admin_views.admin_home'))

            approved_regs = list(db.collection('registrations').where('status_id', '==', approved_status_id).where('week_number', '==', current_week).stream())
            if not approved_regs:
                flash('Không có lịch nào đã duyệt của tuần này để generate!', 'warning')
                return redirect(url_for('admin_views.admin_home'))

            session.modified = True
            flash(f'Đã generate lịch tuần {current_week}. Nhấn Xác nhận để lưu hoặc Hủy để bỏ.', 'info')
            return redirect(url_for('admin_views.admin_home'))

        elif action == 'confirm':
            conf_ref = db.collection('statuses').where('name', '==', 'Đã xác nhận').limit(1).stream()
            conf_list = list(conf_ref)
            if not conf_list:
                new_status_ref = db.collection('statuses').document()
                new_status_ref.set({'name': 'Đã xác nhận'})
                confirmed_status_id = new_status_ref.id
            else:
                confirmed_status_id = conf_list[0].id

            batch = db.batch()
            regs_to_update = db.collection('registrations').where('status_id', '==', approved_status_id).where('week_number', '==', current_week).stream()
            
            updated_count = 0
            for doc in regs_to_update:
                batch.update(doc.reference, {'status_id': confirmed_status_id})
                updated_count += 1
            batch.commit()
            
            flash(f'Lưu thành công {updated_count} lịch trực tuần {current_week} lên trang client!', 'success')
            return redirect(url_for('admin_views.admin_home'))

        elif action == 'cancel':
            flash('Đã hủy thao tác tạo lịch.', 'info')
            return redirect(url_for('admin_views.admin_home'))

    except Exception as e:
        flash(f'Lỗi khi generate lịch: {str(e)}', 'danger')

    return redirect(url_for('admin_views.admin_home'))


@admin_views.route('/request', methods=['GET'])
@login_required
def admin_request():
    if current_user.role_id != 1:
        flash('Bạn không có quyền truy cập trang này!', 'danger')
        return redirect(url_for('admin_views.admin_home'))

    current_year = request.args.get('year', default=datetime.now().year, type=int)
    current_week = request.args.get('week', default=datetime.now().isocalendar()[1], type=int)

    start_date, end_date = get_week_date_range(current_year, current_week)
    prev_week_date = start_date - timedelta(days=7)
    next_week_date = start_date + timedelta(days=7)
    
    prev_year, prev_week, _ = prev_week_date.isocalendar()
    next_year, next_week, _ = next_week_date.isocalendar()

    db = get_db()
    registrations = db.collection('registrations').where('week_number', '==', current_week).order_by('created_at', direction='DESCENDING').stream()

    schedules_data = []
    for reg_doc in registrations:
        reg = reg_doc.to_dict() or {}
        selected_days = reg.get('selected_days', '')
        if not selected_days or selected_days.strip() == '--':
            continue

        user_id = reg.get('user_id')
        user_info = None
        if user_id:
            u_doc = db.collection('users').document(str(user_id)).get()
            if u_doc.exists:
                user_info = u_doc.to_dict() or {}

        raw_name = (user_info.get('full_name') or user_info.get('user_name', 'Không rõ')) if user_info else "Không rõ"
        short_name = raw_name.strip().split(" ")[-1] if raw_name else "Thành viên"
        
        actual_days = get_working_days(selected_days)
        
        status_name = "Chờ xác thực"
        status_id = reg.get('status_id')
        if status_id:
            s_doc = db.collection('statuses').document(str(status_id)).get()
            if s_doc.exists:
             s_data = s_doc.to_dict()
             if s_data:
                status_name = s_data.get('name', 'Chờ xác thực')

        created_at_dt = reg.get('created_at')
        created_at_str = created_at_dt.strftime('%d/%m/%Y %H:%M') if isinstance(created_at_dt, datetime) else "--"

        schedules_data.append({
            "id": reg_doc.id,
            "ho_ten": raw_name,
            "ten_rut_gon": short_name,
            "gmail": user_info.get('email') if user_info else "Không rõ",
            "created_at": created_at_str,
            "selected_days": actual_days or "--",
            "session": reg.get('session') or "--",
            "status_name": status_name
        })

    return render_template(
        'admin/admin_request.html',
        schedules=schedules_data,
        current_week=current_week,
        current_year=current_year,
        start_date=start_date,
        end_date=end_date,
        prev_week=prev_week,
        prev_year=prev_year,
        next_week=next_week,
        next_year=next_year,
        user=current_user
    )


@admin_views.route('/my-registration')
@login_required
def admin_registration():
    vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    current_week = datetime.now(vietnam_tz).isocalendar()[1]
    
    db = get_db()
    conf_ref = db.collection('statuses').where('name', '==', 'Đã xác nhận').limit(1).stream()
    conf_list = list(conf_ref)
    
    registrations = []
    if conf_list:
        confirmed_status_id = conf_list[0].id
        regs_stream = db.collection('registrations').where('week_number', '==', current_week).where('status_id', '==', confirmed_status_id).stream()
        registrations = [doc.to_dict() or {} for doc in regs_stream]

    all_days_in_week = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    working_counts = {day: 0 for day in all_days_in_week}
    total_capacity = 4  

    for reg in registrations:
        raw_off_days = reg.get('selected_days', '')
        off_days_list = [d.strip().replace('Thứ ', 'T').replace('Chủ Nhật', 'CN') for d in raw_off_days.split(",")] if raw_off_days else []
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


@admin_views.route('/user-detail/<string:id>')
@login_required
def admin_user_detail(id):
    if current_user.role_id != 1:
        flash('Bạn không có quyền truy cập!', 'danger')
        return redirect(url_for('admin_views.admin_home'))
        
    db = get_db()
    u_doc = db.collection('users').document(id).get()
    if not u_doc.exists:
        flash('Không tìm thấy người dùng!', 'danger')
        return redirect(url_for('admin_views.admin_home'))
        
    class TargetUser:
        def __init__(self, uid, data):
            self.id = uid
            self.user_name = data.get('user_name')
            self.email = data.get('email')
            self.allowed_off_days = data.get('allowed_off_days', 2)
            self.role_id = data.get('role_id')

    target_user = TargetUser(id, u_doc.to_dict() or {})
    return render_template('admin/admin_user_detail.html', target_user=target_user, user=current_user)


@admin_views.route('/update-off-days/<string:user_id>', methods=['POST'])
@login_required 
def update_off_days(user_id):
    new_limit = request.form.get('allowed_off_days', type=int)
    db = get_db()
    
    u_ref = db.collection('users').document(user_id)
    u_doc = u_ref.get()
    
    if not u_doc.exists:
        flash('Không tìm thấy người dùng!', 'danger')
        return redirect(url_for('admin_views.admin_users'))
        
    user_data = u_doc.to_dict() or {}
    
    if new_limit is not None and new_limit >= 0: # Cho phép chỉnh mức ngày nghỉ hợp lý
        u_ref.update({'allowed_off_days': new_limit})
        
        # Thêm thông báo vào collection cho client đọc
        db.collection('notifications').add({
            'user_id': user_id, # Phải khớp chính xác ID của user được nhận
            'title': "Cập nhật hạn mức ngày nghỉ",
            'message': f"Quản trị viên vừa cập nhật hạn mức ngày nghỉ của bạn thành {new_limit} ngày.",
            'status': 'pending',
            'is_read': False,
            'created_at': SERVER_TIMESTAMP  
        })
        
        try:
            email_subject = "[HỆ THỐNG] Cập nhật hạn mức ngày nghỉ phép"
            email_body = (
                f"Xin chào {user_data.get('user_name')},\n\n"
                f"Quản trị viên vừa cập nhật hạn mức ngày nghỉ phép của bạn thành: {new_limit} ngày.\n\n"
                f"Trân trọng!"
            )
            send_mail_based_on_admin_config(email_subject, [user_data.get('email')], email_body)
        except Exception as e:
            print(f"Lỗi gửi email: {e}")
        
        flash(f'Đã cập nhật số ngày nghỉ cho {user_data.get("user_name")} thành {new_limit} ngày!', 'success')
    else:
        flash('Giá trị ngày nghỉ không hợp lệ!', 'danger')
        
    return redirect(url_for('admin_views.admin_users'))


@admin_views.route('/users')
@login_required
def admin_users():
    if current_user.role_id != 1:
        flash('Bạn không có quyền truy cập!', 'danger')
        return redirect(url_for('admin_views.admin_home'))
    
    db = get_db()
    users_stream = db.collection('users').stream()
    
    class UserObj:
        def __init__(self, uid, data):
            self.id = uid
            self.user_name = data.get('user_name')
            self.email = data.get('email')
            self.allowed_off_days = data.get('allowed_off_days', 2)
            self.role_id = data.get('role_id')

    users = [UserObj(doc.id, doc.to_dict() or {}) for doc in users_stream]
    return render_template('admin/admin_usershift.html', users=users, user=current_user)


def build_month_weeks_matrix(year, month):
    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdatescalendar(year, month)
    
    weeks = []
    day_codes = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    day_names = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"]
    
    today = datetime.now().date()
    
    for week_idx, week_dates in enumerate(month_days, start=1):
        monday = week_dates[0]
        sunday = week_dates[-1]
        week_number = monday.isocalendar()[1]
        
        days_struct = []
        for i, d in enumerate(week_dates):
            days_struct.append({
                'day_code': day_codes[i],
                'day_name': day_names[i],
                'date_str': d.strftime('%d/%m'),
                'full_date': d.strftime('%Y-%m-%d'),
                'is_current_month': (d.month == month),
                'is_today': (d == today),
                'personnel': []
            })
            
        weeks.append({
            'week_number': week_number,
            'week_index': week_idx,
            'date_range_label': f"Tuần {week_idx} (Tháng {month})",
            'start_date': monday.strftime('%d/%m/%Y'),
            'end_date': sunday.strftime('%d/%m/%Y'),
            'days': days_struct,
            'total_slots': 0,
            'empty_days_count': 0,
            'raw_registrations': []
        })
    return weeks


@admin_views.route('/history', methods=['GET'])
@login_required
def admin_history():
    if current_user.role_id != 1:
        flash('Bạn không có quyền truy cập trang này!', 'danger')
        return redirect(url_for('admin_views.admin_home'))

    now = datetime.now()
    selected_month = request.args.get('month', default=now.month, type=int)
    selected_year = request.args.get('year', default=now.year, type=int)

    db = get_db()
    try:
        # Cache Users để loại bỏ hoàn toàn N+1 query
        users_cache = {}
        for u_doc in db.collection('users').stream():
            u_data = u_doc.to_dict() or {}
            raw_name = u_data.get('full_name') or u_data.get('user_name', 'Không rõ')
            short_name = raw_name.strip().split(" ")[-1] if raw_name else "Thành viên"
            users_cache[u_doc.id] = {
                'ho_ten': raw_name,
                'ten_rut_gon': short_name,
                'gmail': u_data.get('email', 'Không rõ')
            }

        # Cache Statuses
        statuses_cache = {}
        for s_doc in db.collection('statuses').stream():
            s_data = s_doc.to_dict() or {}
            statuses_cache[s_doc.id] = s_data.get('name', 'Chưa xác thực')

        weeks_data = build_month_weeks_matrix(selected_year, selected_month)
        regs_stream = db.collection('registrations').order_by('created_at', direction='DESCENDING').stream()

        schedules_data = []
        total_active_personnel = 0

        for reg_doc in regs_stream:
            reg = reg_doc.to_dict() or {}
            created_at_dt = reg.get('created_at')
            if isinstance(created_at_dt, datetime):
                if created_at_dt.month != selected_month or created_at_dt.year != selected_year:
                    continue
                created_at_str = created_at_dt.strftime('%d/%m/%Y %H:%M')
            else:
                created_at_str = "--"

            user_id = str(reg.get('user_id', ''))
            user_info = users_cache.get(user_id, {'ho_ten': 'Không rõ', 'ten_rut_gon': 'Thành viên', 'gmail': 'Không rõ'})

            selected_days = reg.get('selected_days', '')
            actual_working_days = get_working_days(selected_days)

            status_id = str(reg.get('status_id', ''))
            status_name = statuses_cache.get(status_id, "Chưa xác thực")
            
            badge_class = "badge-status-warning"
            if status_name == "Đã xác nhận":
                badge_class = "badge-status-success"
            elif status_name == "Đã duyệt":
                badge_class = "badge-status-primary"

            reg_item = {
                "id": reg_doc.id,
                "ho_ten": user_info['ho_ten'],
                "ten_rut_gon": user_info['ten_rut_gon'],
                "gmail": user_info['gmail'],
                "created_at": created_at_str,
                "ngay_chon": created_at_str,
                "selected_days": actual_working_days or "--",
                "session": reg.get('session') or "--",
                "status_name": status_name,
                "status_badge_class": badge_class
            }
            schedules_data.append(reg_item)

            working_day_codes = [d.strip() for d in actual_working_days.split(",") if d.strip() in ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]]
            target_week_num = reg.get('week_number')

            person_obj = {
                'id': reg_doc.id,
                'ho_ten': user_info['ho_ten'],
                'ten_rut_gon': user_info['ten_rut_gon'],
                'gmail': user_info['gmail'],
                'status_name': status_name,
                'status_badge_class': badge_class
            }

            for week in weeks_data:
                if target_week_num and week['week_number'] != target_week_num:
                    continue

                week['raw_registrations'].append(reg_item)

                for day in week['days']:
                    if day['day_code'] in working_day_codes:
                        day['personnel'].append(person_obj)
                        week['total_slots'] += 1
                        total_active_personnel += 1

        for week in weeks_data:
            week['empty_days_count'] = sum(1 for d in week['days'] if len(d['personnel']) == 0)

    except Exception as e:
        print(f"Lỗi tải lịch sử: {e}")
        schedules_data = []
        weeks_data = []
        total_active_personnel = 0

    return render_template(
        'admin/admin_history.html',
        weeks_data=weeks_data,                       
        schedules=schedules_data,                    
        selected_month=selected_month,
        selected_year=selected_year,
        total_active_personnel=total_active_personnel,
        total_registrations=len(schedules_data),
        user=current_user
    )



@admin_views.route('/export-excel', methods=['GET'])
@login_required
def export_excel():
    if current_user.role_id != 1:
        flash('Bạn không có quyền thực hiện thao tác này!', 'danger')
        return redirect(url_for('admin_views.admin_home'))
         
    selected_month = request.args.get('month', default=None, type=int)
    selected_year = request.args.get('year', default=None, type=int)
    
    db = get_db()
    regs_stream = db.collection('registrations').stream()
    
    data_list = []
    for reg_doc in regs_stream:
        reg = reg_doc.to_dict() or {}
        created_at_dt = reg.get('created_at')
        if isinstance(created_at_dt, datetime):
            if selected_month and created_at_dt.month != selected_month:
                continue
            if selected_year and created_at_dt.year != selected_year:
                continue
        
        user_id = reg.get('user_id')
        user_name = "Không rõ"
        if user_id:
            u_doc = db.collection('users').document(str(user_id)).get()
            if u_doc.exists:
                u_data = u_doc.to_dict() or {}
                user_name = u_data.get('full_name') or u_data.get('user_name', 'Không rõ')
                
        data_list.append({
            "Họ và tên": user_name,
            "Ca trực": reg.get('session', '--'),
            "Ngày làm việc thực tế": get_working_days(reg.get('selected_days', '')),
            "Ngày đăng ký": created_at_dt.strftime('%d/%m/%Y %H:%M') if isinstance(created_at_dt, datetime) else '--'
        })
        
    df = pd.DataFrame(data_list)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='LichSuTruc')
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'LichSuTruc_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )