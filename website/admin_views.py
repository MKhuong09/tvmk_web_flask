import io
import calendar
from datetime import datetime, timedelta, timezone 
from flask import send_file
from flask import Blueprint, current_app, render_template, redirect, request, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from flask import send_file

from .models import  User, Registration, Status, db
from algorithms.schedule_agent import DayOfWeek, ScheduleAgent, UserData, convert_day_to_numeric

from sqlalchemy import func
from datetime import datetime, timedelta
import pytz
from typing import Any, cast
from firebase_admin import firestore
from google.cloud.firestore_v1.client import Client as FirestoreClient
from google.cloud.firestore import SERVER_TIMESTAMP
from google.cloud.firestore_v1.base_document import DocumentSnapshot
import pandas as pd

# Import các hàm tiện ích và cơ chế cache từ utils.py
from website.utils import send_mail_based_on_admin_config, cache_result, clear_universal_cache

admin_views = Blueprint('admin_views', __name__)

def get_db() -> FirestoreClient:
    return cast(FirestoreClient, firestore.client())

db = get_db()

# --- CÁC HÀM LẤY DỮ LIỆU TỪ FIRESTORE (ÁP DỤNG DECORATOR CACHE 30 GIÂY) ---

@cache_result(ttl=30)
def get_schedules_from_db():
    """Lấy danh sách toàn bộ schedules có cache"""
    print("[DEBUG] Đang gọi Firestore lấy danh sách schedules...")
    docs = db.collection('schedules').stream()
    return [doc.to_dict() for doc in docs]

@cache_result(ttl=30)
def get_users_from_db():
    """Lấy danh sách toàn bộ users có cache"""
    print("[DEBUG] Đang gọi Firestore lấy danh sách users...")
    users_stream = db.collection('users').stream()
    users_list = []
    for doc in users_stream:
        u_data = doc.to_dict() or {}
        u_data['id'] = doc.id
        users_list.append(u_data)
    return users_list


def get_working_days(selected_days):
    if selected_days is None or selected_days == "" or selected_days == "--":
        return "--"

    all_days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

    if isinstance(selected_days, str):
        excluded_values = selected_days.split(",")
    elif isinstance(selected_days, (list, tuple, set)):
        excluded_values = selected_days
    else:
        return "--"

    day_aliases = {
        "THỨ HAI": "T2",
        "THỨ BA": "T3",
        "THỨ TƯ": "T4",
        "THỨ NĂM": "T5",
        "THỨ SÁU": "T6",
        "THỨ BẢY": "T7",
        "CHỦ NHẬT": "CN",
    }

    excluded_days = set()

    for value in excluded_values:
        if not isinstance(value, str):
            continue

        normalized = value.strip().upper()
        normalized = day_aliases.get(normalized, normalized)
        excluded_days.add(normalized)

    working_days = [
        day for day in all_days
        if day not in excluded_days
    ]

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
    all_users = get_users_from_db()  # Dùng hàm có cache
    total_people = len(all_users)
    registered = 0
    not_registered = 0

    vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    current_week = datetime.now(vietnam_tz).isocalendar()[1]

    week_regs = (
        db.collection('registrations')
        .where('week_number', '==', current_week)
        .stream()
    )

    registered_user_ids = set()

    for doc in week_regs:
        reg_data = doc.to_dict() or {}
        if reg_data.get('selected_days') and reg_data.get('session'):
            registered_user_ids.add(reg_data.get('user_id'))

    for user in all_users:
        if user['id'] in registered_user_ids:
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
    if current_user.role_id != 1:
        flash('Bạn không có quyền truy cập trang này!', 'danger')
        return redirect(url_for('admin_views.admin_home'))

    now = datetime.now()
    current_year = request.args.get('year', default=now.year, type=int)
    default_week = now.isocalendar()[1]
    current_week = request.args.get('week', default=default_week, type=int)

    start_date, end_date = get_week_date_range(current_year, current_week)

    all_users = get_users_from_db()
    schedules_data = []

    for user_info in all_users:
        if user_info.get('role_id') == 1:
            continue

        user_id = user_info['id']
        raw_name = user_info.get('full_name') or user_info.get('user_name', 'Không rõ')
        short_name = raw_name.strip().split(' ')[-1] if raw_name else 'Thành viên'

        regs_ref = (
            db.collection('registrations')
            .where('user_id', '==', user_id)
            .where('week_number', '==', current_week)
            .limit(1)
            .stream()
        )
        reg_list = list(regs_ref)

        reg_data = reg_list[0].to_dict() if reg_list else None
        reg_id = reg_list[0].id if reg_list else None

        actual_days = (
            get_working_days(reg_data.get('selected_days'))
            if reg_data and reg_data.get('selected_days')
            else '--'
        )

        status_name = 'Chưa đăng ký'
        if reg_data and reg_data.get('status_id'):
            status_doc = cast(
                DocumentSnapshot,
                db.collection('statuses')
                .document(str(reg_data.get('status_id')))
                .get(),
            )

            if status_doc.exists:
                status_dict = status_doc.to_dict() or {}
                status_name = status_dict.get('name', 'Chưa đăng ký')

        created_at_str = '--'
        if reg_data and reg_data.get('created_at'):
            created_at_val = reg_data.get('created_at')
            if isinstance(created_at_val, datetime):
                created_at_str = created_at_val.strftime('%d/%m/%Y %H:%M')

        schedules_data.append({
            'id': reg_id,
            'ho_ten': raw_name,
            'ten_rut_gon': short_name,
            'gmail': user_info.get('email'),
            'ngay_chon': created_at_str,
            'selected_days': actual_days,
            'session': reg_data.get('session') if reg_data else '--',
            'status_name': status_name,
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
        next_year=next_year,
    )


@admin_views.route('/approve-schedule/<string:reg_id>', methods=['POST'])
@login_required
def approve_schedule(reg_id):
    if current_user.role_id != 1:
        return jsonify({
            'status': 'error',
            'message': 'Bạn không có quyền thực hiện thao tác này!'
        }), 403

    try:
        reg_ref = db.collection('registrations').document(reg_id)
        reg_doc = reg_ref.get()

        reg_doc = cast(Any, reg_ref.get())

        if not reg_doc.exists:
            return jsonify({
                'status': 'error',
                'message': 'Không tìm thấy thông tin đăng ký!'
            }), 404

        statuses_ref = (
            db.collection('statuses')
            .where('name', '==', 'Đã duyệt')
            .limit(1)
            .stream()
        )
        status_list = list(statuses_ref)

        if not status_list:
            return jsonify({
                'status': 'error',
                'message': 'Không tìm thấy trạng thái "Đã duyệt" trong CSDL!'
            }), 400

        approved_status_id = status_list[0].id
        reg_ref.update({'status_id': approved_status_id})

        clear_universal_cache()

        return jsonify({
            'status': 'success',
            'message': 'Đã duyệt lịch thành công!'
        })

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@admin_views.route(
    "/decline-schedule/<string:reg_id>",
    methods=["POST"],
)
@login_required
def decline_schedule(reg_id):
    if current_user.role_id != 1:
        return jsonify({
            "status": "error",
            "message": "Bạn không có quyền thực hiện thao tác này!",
        }), 403

    db = get_db()

    try:
        registration_ref = db.collection("registrations").document(reg_id)
        registration = cast(DocumentSnapshot, registration_ref.get())

        if not registration.exists:
            return jsonify({
                "status": "error",
                "message": "Không tìm thấy thông tin đăng ký!",
            }), 404

        registration_data = registration.to_dict() or {}

        declined_statuses = list(
            db.collection("statuses")
            .where("name", "==", "Đã từ chối")
            .limit(1)
            .stream()
        )

        if declined_statuses:
            declined_status_id = declined_statuses[0].id
        else:
            declined_status_ref = db.collection("statuses").document()
            declined_status_ref.set({"name": "Đã từ chối"})
            declined_status_id = declined_status_ref.id

        registration_ref.update({"status_id": declined_status_id})
        clear_universal_cache()

        user_id = registration_data.get("user_id")
        user_data = {}

        if user_id:
            user_ref = db.collection("users").document(str(user_id))
            user_doc = cast(DocumentSnapshot, user_ref.get())

            if user_doc.exists:
                user_data = user_doc.to_dict() or {}

        email = (user_data.get("email") or "").strip()

        if email:
            subject = "Thông báo từ chối đăng ký"
            body = (
                f"Xin chào {user_data.get('user_name', '')},\n\n"
                "Đơn đăng ký lịch trực của bạn đã bị từ chối. "
                "Vui lòng liên hệ để biết thêm chi tiết.\n\n"
                f"Link đăng ký lịch: "
                f"{url_for('client_views.client_shift', _external=True)}\n\n"
                "Trân trọng."
            )

            send_mail_based_on_admin_config(subject, [email], body)

        return jsonify({
            "status": "success",
            "message": "Đã từ chối đơn thành công!",
        }), 200

    except Exception as exc:
        return jsonify({
            "status": "error",
            "message": str(exc),
        }), 500
@admin_views.route('/approve-change/<string:reg_id>', methods=['POST'])
@login_required
def approve_change(reg_id):
    if current_user.role_id != 1:
        return jsonify({
            'status': 'error',
            'message': 'Bạn không có quyền thực hiện thao tác này!'
        }), 403

    try:
        reg_ref = db.collection('registrations').document(reg_id)
        reg_doc = cast(Any, reg_ref.get())

        if not reg_doc.exists:
            return jsonify({
                'status': 'error',
                'message': 'Không tìm thấy lịch trực!'
            }), 404

        reg = reg_doc.to_dict() or {}
        new_days = reg.get('pending_selected_days')

        if not reg.get('has_pending_change') or not new_days:
            return jsonify({
                'status': 'error',
                'message': 'Lịch này không có yêu cầu đổi nào!'
            }), 400

        confirmed_statuses = list(
            db.collection('statuses')
            .where('name', '==', 'Đã xác nhận')
            .limit(1)
            .stream()
        )

        if not confirmed_statuses:
            return jsonify({
                'status': 'error',
                'message': 'Không tìm thấy trạng thái "Đã xác nhận" trong CSDL!'
            }), 400

        reg_ref.update({
            'selected_days': new_days,
            'session': reg.get('pending_session') or reg.get('session'),
            'status_id': confirmed_statuses[0].id,
            'has_pending_change': False,
            'pending_selected_days': None,
            'pending_session': None,
            'change_requested_at': None,
            'confirmed_at': SERVER_TIMESTAMP,
        })
        clear_universal_cache()

        db.collection('notifications').add({
            'user_id': reg.get('user_id'),
            'title': 'Yêu cầu đổi lịch đã được duyệt',
            'message': (
                f"Admin đã duyệt yêu cầu đổi lịch tuần "
                f"{reg.get('week_number')} của bạn."
            ),
            'status': 'approved',
            'is_read': False,
            'created_at': datetime.now(),
        })

        return jsonify({
            'status': 'success',
            'message': 'Đã duyệt yêu cầu đổi lịch!'
        })

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@admin_views.route('/reject-change/<string:reg_id>', methods=['POST'])
@login_required
def reject_change(reg_id):
    if current_user.role_id != 1:
        return jsonify({
            'status': 'error',
            'message': 'Bạn không có quyền thực hiện thao tác này!'
        }), 403

    try:
        reg_ref = db.collection('registrations').document(reg_id)
        reg_doc = cast(Any, reg_ref.get())

        if not reg_doc.exists:
            return jsonify({
                'status': 'error',
                'message': 'Không tìm thấy lịch trực!'
            }), 404

        reg = reg_doc.to_dict() or {}

        if not reg.get('has_pending_change'):
            return jsonify({
                'status': 'error',
                'message': 'Lịch này không có yêu cầu đổi nào!'
            }), 400

        reg_ref.update({
            'has_pending_change': False,
            'pending_selected_days': None,
            'pending_session': None,
            'change_requested_at': None,
        })
        clear_universal_cache()

        db.collection('notifications').add({
            'user_id': reg.get('user_id'),
            'title': 'Yêu cầu đổi lịch bị từ chối',
            'message': (
                f"Admin đã từ chối yêu cầu đổi lịch tuần "
                f"{reg.get('week_number')} của bạn. Lịch cũ được giữ nguyên."
            ),
            'status': 'rejected',
            'is_read': False,
            'created_at': datetime.now(),
        })

        return jsonify({
            'status': 'success',
            'message': 'Đã từ chối yêu cầu đổi lịch!'
        })

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500
@admin_views.route('/generate-schedule', methods=['POST'])
@login_required
def generate_schedule():
    if current_user.role_id != 1:
        flash('Bạn không có quyền thực hiện chức năng này!', 'danger')
        return redirect(url_for('admin_views.admin_home'))

    action = request.form.get('action_generate') or request.form.get('action_confirm') or request.form.get('action_cancel')

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
            
            # Xóa sạch toàn bộ cache chung sau khi xác nhận lịch
            clear_universal_cache()

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

    now = datetime.now()
    selected_month = request.args.get('month', default=now.month, type=int)
    selected_year = request.args.get('year', default=now.year, type=int)

    if selected_month not in range(1, 13):
        selected_month = now.month
    if selected_year < 2000 or selected_year > 2100:
        selected_year = now.year

    month_weeks = build_month_weeks_matrix(selected_year, selected_month)
    allowed_keys = {(w['week_year'], w['week_number']) for w in month_weeks}

    # Nạp trước user/status để không đọc Firestore lặp lại cho từng đơn
    users_cache = {}
    for u in get_users_from_db():
        users_cache[str(u.get('id'))] = u

    statuses_cache = {}
    for s_doc in db.collection('statuses').stream():
        statuses_cache[str(s_doc.id)] = (s_doc.to_dict() or {}).get('name', 'Chờ xác thực')

    regs_by_week = {}

    for reg_doc in db.collection('registrations').stream():
        reg = reg_doc.to_dict() or {}
        selected_days = reg.get('selected_days')

        if not selected_days:
            continue
        if isinstance(selected_days, str) and selected_days.strip() in ('', '--'):
            continue
        if not isinstance(selected_days, (str, list, tuple, set)):
            continue

        week_key = _resolve_registration_week(reg)
        if week_key not in allowed_keys:
            continue

        user_info = users_cache.get(str(reg.get('user_id'))) or {}
        raw_name = user_info.get('full_name') or user_info.get('user_name') or 'Không rõ'

        status_id = reg.get('status_id')
        status_name = statuses_cache.get(str(status_id), 'Chờ xác thực') if status_id else 'Chờ xác thực'

        created_at_dt = reg.get('created_at')
        if isinstance(created_at_dt, datetime):
            created_at_str = created_at_dt.strftime('%d/%m/%Y %H:%M')
            created_at_ts = created_at_dt.timestamp()
        else:
            created_at_str = '--'
            created_at_ts = 0

        regs_by_week.setdefault(week_key, []).append({
            'id': reg_doc.id,
            'ho_ten': raw_name,
            'gmail': user_info.get('email') or 'Không rõ',
            'created_at': created_at_str,
            'created_at_ts': created_at_ts,
            'selected_days': get_working_days(selected_days),
            'status_name': status_name,
        })

    weeks_data = []
    total_pending = 0
    total_done = 0

    for week in month_weeks:
        key = (week['week_year'], week['week_number'])
        schedules = regs_by_week.get(key)
        if not schedules:
            continue

        schedules.sort(key=lambda item: item['created_at_ts'], reverse=True)
        pending_count = sum(
            1 for item in schedules if item['status_name'] in PENDING_STATUS_NAMES
        )
        total_pending += pending_count
        total_done += len(schedules) - pending_count

        weeks_data.append({
            'week_number': week['week_number'],
            'week_year': week['week_year'],
            'start_date': week['start_date'],
            'end_date': week['end_date'],
            'schedules': schedules,
            'pending_count': pending_count,
            'is_open': False,
        })

    iso = now.isocalendar()
    current_key = (iso[0], iso[1])
    if weeks_data:
        week_keys = [(w['week_year'], w['week_number']) for w in weeks_data]
        if current_key in week_keys:
            weeks_data[week_keys.index(current_key)]['is_open'] = True
        else:
            weeks_data[0]['is_open'] = True

    return render_template(
        'admin/admin_request.html',
        weeks_data=weeks_data,
        selected_month=selected_month,
        selected_year=selected_year,
        total_pending=total_pending,
        total_done=total_done,
        user=current_user,
    )
@admin_views.route('/my-registration')
@login_required
def admin_registration():
    vietnam_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    current_week = datetime.now(vietnam_tz).isocalendar()[1]
    
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
        raw_off_days = reg.get('selected_days')
        if isinstance(raw_off_days, str):
            raw_values = raw_off_days.split(",")
        elif isinstance(raw_off_days, (list, tuple, set)):
            raw_values = raw_off_days
        else:
            raw_values = []

        off_days_list = [
            str(d).strip().replace('Thứ ', 'T').replace('Chủ Nhật', 'CN')
            for d in raw_values
            if str(d).strip()
        ]
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
def admin_user_detail(id: str):
    if current_user.role_id != 1:
        flash('Bạn không có quyền truy cập!', 'danger')
        return redirect(url_for('admin_views.admin_home'))

    u_doc = cast(
        DocumentSnapshot,
        db.collection('users').document(id).get(),
    )

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

    return render_template(
        'admin/admin_user_detail.html',
        target_user=target_user,
        user=current_user,
    )


@admin_views.route('/update-off-days/<string:user_id>', methods=['POST'])
@login_required
def update_off_days(user_id: str):
    if current_user.role_id != 1:
        flash("Bạn không có quyền thực hiện thao tác này!", "danger")
        return redirect(url_for("admin_views.admin_home"))

    new_limit = request.form.get("allowed_off_days", type=int)

    u_ref = db.collection("users").document(user_id)
    u_doc = cast(DocumentSnapshot, u_ref.get())

    if not u_doc.exists:
        flash("Không tìm thấy người dùng!", "danger")
        return redirect(url_for("admin_views.admin_users"))

    user_data = u_doc.to_dict() or {}

    if new_limit is None or new_limit < 0:
        flash("Giá trị ngày nghỉ không hợp lệ!", "danger")
        return redirect(url_for("admin_views.admin_users"))

    u_ref.update({"allowed_off_days": new_limit})
    clear_universal_cache()
    
    notification_time = datetime.now(timezone.utc)
    db.collection("notifications").add({
        "user_id": user_id,
        "title": "Cập nhật hạn mức ngày nghỉ",
        "message": (
            f"Quản trị viên vừa cập nhật hạn mức ngày nghỉ "
            f"của bạn thành {new_limit} ngày."
        ),
        "status": "pending",
        "is_read": False,
        'created_at': notification_time,
        'expires_at': notification_time + timedelta(hours=1),
    })

    email = (user_data.get("email") or "").strip()
    email_sent = False

    if email:
        email_subject = "[HỆ THỐNG] Cập nhật hạn mức ngày nghỉ phép"
        email_body = (
            f"Xin chào {user_data.get('user_name')},\n\n"
            f"Quản trị viên vừa cập nhật hạn mức ngày nghỉ phép "
            f"của bạn thành: {new_limit} ngày.\n\n"
            "Trân trọng!"
        )

        try:
            email_sent = send_mail_based_on_admin_config(
                email_subject,
                [email],
                email_body,
            )
        except Exception as exc:
            print(f"Lỗi gửi email: {exc}")

    flash(
        f"Đã cập nhật số ngày nghỉ cho "
        f"{user_data.get('user_name')} thành {new_limit} ngày!",
        "success",
    )

    if email_sent:
        flash("Đã gửi email thông báo cho client.", "success")
    elif email:
        flash(
            "Đã cập nhật hạn mức, nhưng email chưa gửi được. "
            "Hãy kiểm tra lỗi SMTP trong Terminal.",
            "warning",
        )
    else:
        flash(
            "Đã cập nhật hạn mức, nhưng tài khoản này chưa có email.",
            "warning",
        )

    return redirect(url_for("admin_views.admin_users"))


@admin_views.route('/users')
@login_required
def admin_users():
    if current_user.role_id != 1:
        flash('Bạn không có quyền truy cập!', 'danger')
        return redirect(url_for('admin_views.admin_home'))
    
    users_list = get_users_from_db()  # Dùng hàm có cache
    
    class UserObj:
        def __init__(self, uid, data):
            self.id = uid
            self.user_name = data.get('user_name')
            self.email = data.get('email')
            self.allowed_off_days = data.get('allowed_off_days', 2)
            self.role_id = data.get('role_id')

    users = [UserObj(u['id'], u) for u in users_list]
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
        week_year, week_number, _ = monday.isocalendar()

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
            'week_year': week_year,
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


CONFIRMED_STATUS_NAME = 'Đã xác nhận'
PENDING_STATUS_NAMES = {'Chờ xác nhận', 'Chờ xác thực'}
WORKING_DAY_CODES = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']


def _resolve_registration_week(reg):
    """Trả về (năm ISO, số tuần) của tuần làm việc mà đơn đăng ký hướng tới."""
    created_at = reg.get('created_at')
    week_year = reg.get('week_year')
    week_number = reg.get('week_number')

    # Đơn cũ có thể thiếu week_year/week_number; đơn luôn gửi trước 1 tuần.
    if (week_year is None or week_number is None) and isinstance(created_at, datetime):
        derived_year, derived_week, _ = (created_at + timedelta(days=7)).isocalendar()
        week_year = derived_year if week_year is None else week_year
        week_number = derived_week if week_number is None else week_number

    try:
        return int(week_year), int(week_number)
    except (TypeError, ValueError):
        return None


@admin_views.route('/history', methods=['GET'])
@login_required
def admin_history():
    if current_user.role_id != 1:
        flash('Bạn không có quyền truy cập trang này!', 'danger')
        return redirect(url_for('admin_views.admin_home'))

    now = datetime.now()
    selected_month = request.args.get('month', default=now.month, type=int)
    selected_year = request.args.get('year', default=now.year, type=int)

    weeks_data = []
    total_active_personnel = 0
    total_registrations = 0
    total_pending_changes = 0

    try:
        users_list = get_users_from_db()  # Dùng hàm có cache
        users_cache = {}
        for u_data in users_list:
            u_id = u_data['id']
            raw_name = u_data.get('full_name') or u_data.get('user_name', 'Không rõ')
            short_name = raw_name.strip().split(" ")[-1] if raw_name else "Thành viên"
            users_cache[u_id] = {
                'ho_ten': raw_name,
                'ten_rut_gon': short_name,
                'gmail': u_data.get('email', 'Không rõ')
            }

        statuses_cache = {}
        for s_doc in db.collection('statuses').stream():
            s_data = s_doc.to_dict() or {}
            statuses_cache[s_doc.id] = s_data.get('name', 'Chưa xác thực')

        all_weeks = build_month_weeks_matrix(selected_year, selected_month)
        week_lookup = {
            (week['week_year'], week['week_number']): week
            for week in all_weeks
        }

        registrations = []

        for reg_doc in db.collection('registrations').stream():
            reg = reg_doc.to_dict() or {}
            week_key = _resolve_registration_week(reg)

            if week_key is None or week_key not in week_lookup:
                continue

            created_at_dt = reg.get('created_at')
            if isinstance(created_at_dt, datetime):
                created_at_str = created_at_dt.strftime('%d/%m/%Y %H:%M')
                sort_ts = created_at_dt.timestamp()
            else:
                created_at_str = "--"
                sort_ts = 0.0

            user_id = str(reg.get('user_id', ''))
            user_info = users_cache.get(user_id, {'ho_ten': 'Không rõ', 'ten_rut_gon': 'Thành viên', 'gmail': 'Không rõ'})

            actual_working_days = get_working_days(reg.get('selected_days'))

            status_id = str(reg.get('status_id', ''))
            status_name = statuses_cache.get(status_id, "Chưa xác thực")

            # Gộp "Đã duyệt" vào "Đã xác nhận": chỉ còn một trạng thái chốt lịch.
            if status_name == "Đã duyệt":
                status_name = CONFIRMED_STATUS_NAME

            pending_raw_days = reg.get('pending_selected_days')
            has_pending_change = bool(reg.get('has_pending_change')) and bool(pending_raw_days)

            badge_class = "badge-status-warning"
            if status_name == CONFIRMED_STATUS_NAME:
                badge_class = "badge-status-success"
            elif status_name == "Đã từ chối":
                badge_class = "badge-status-danger"

            registrations.append({
                'week_key': week_key,
                'sort_ts': sort_ts,
                'item': {
                    "id": reg_doc.id,
                    "ho_ten": user_info['ho_ten'],
                    "ten_rut_gon": user_info['ten_rut_gon'],
                    "gmail": user_info['gmail'],
                    "created_at": created_at_str,
                    "ngay_chon": created_at_str,
                    "selected_days": actual_working_days or "--",
                    "session": reg.get('session') or "--",
                    "status_name": status_name,
                    "status_badge_class": badge_class,
                    "is_confirmed": status_name == CONFIRMED_STATUS_NAME,
                    "is_pending": status_name in PENDING_STATUS_NAMES,
                    "has_pending_change": has_pending_change,
                    "pending_selected_days": get_working_days(pending_raw_days) if has_pending_change else "--",
                    "pending_session": reg.get('pending_session') or "--",
                },
            })

        registrations.sort(key=lambda entry: entry['sort_ts'], reverse=True)

        for entry in registrations:
            week = week_lookup[entry['week_key']]
            item = entry['item']

            week['raw_registrations'].append(item)

            if not item['is_confirmed']:
                continue

            working_day_codes = [
                d.strip() for d in item['selected_days'].split(",")
                if d.strip() in WORKING_DAY_CODES
            ]

            person_obj = {
                'id': item['id'],
                'ho_ten': item['ho_ten'],
                'ten_rut_gon': item['ten_rut_gon'],
                'gmail': item['gmail'],
                'status_name': item['status_name'],
                'status_badge_class': item['status_badge_class'],
                'has_pending_change': item['has_pending_change'],
            }

            for day in week['days']:
                if day['day_code'] in working_day_codes:
                    day['personnel'].append(person_obj)
                    week['total_slots'] += 1

        for week in all_weeks:
            week['empty_days_count'] = sum(1 for d in week['days'] if not d['personnel'])

        # Lịch sử chỉ hiện tuần đã generate (có ít nhất một lịch Đã xác nhận).
        weeks_data = [week for week in all_weeks if week['total_slots'] > 0]

        total_active_personnel = sum(week['total_slots'] for week in weeks_data)
        total_registrations = sum(
            1
            for week in weeks_data
            for reg in week['raw_registrations']
            if reg['is_confirmed']
        )
        total_pending_changes = sum(
            1
            for week in weeks_data
            for reg in week['raw_registrations']
          if reg['is_pending'] or reg['has_pending_change']
        )

    except Exception as e:
        print(f"Lỗi tải lịch sử: {e}")
        weeks_data = []
        total_active_personnel = 0
        total_registrations = 0
        total_pending_changes = 0

    return render_template(
        'admin/admin_history.html',
        weeks_data=weeks_data,
        selected_month=selected_month,
        selected_year=selected_year,
        total_active_personnel=total_active_personnel,
        total_registrations=total_registrations,
        total_pending_changes=total_pending_changes,
        user=current_user
    )


@admin_views.route('/export-excel', methods=['GET'])
@login_required
def export_excel():
    if current_user.role_id != 1:
        flash('Bạn không có quyền truy cập thao tác này!', 'danger')
        return redirect(url_for('admin_views.admin_home'))
         
    selected_month = request.args.get('month', default=None, type=int)
    selected_year = request.args.get('year', default=None, type=int)
    
    regs_stream = db.collection('registrations').stream()
    
    users_list = get_users_from_db()  # Dùng hàm có cache
    users_map = {u['id']: (u.get('full_name') or u.get('user_name', 'Không rõ')) for u in users_list}
    
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
        user_name = users_map.get(str(user_id), "Không rõ") if user_id else "Không rõ"
                
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
@admin_views.route('/client-accounts')
@login_required
def admin_client_accounts():
    if current_user.role_id != 1:
        flash('Bạn không có quyền truy cập!', 'danger')
        return redirect(url_for('admin_views.admin_home'))

    clients = [
        client
        for client in get_users_from_db()
        if client.get('role_id') == 2
    ]

    return render_template(
        'admin/client_accounts.html',
        clients=clients,
        user=current_user,
    )


@admin_views.route(
    '/client-accounts/<string:user_id>/delete',
    methods=['POST'],
)
@login_required
def delete_client_account(user_id: str):
    if current_user.role_id != 1:
        flash('Bạn không có quyền thực hiện thao tác này!', 'danger')
        return redirect(url_for('admin_views.admin_home'))

    user_ref = db.collection('users').document(user_id)
    user_doc = cast(DocumentSnapshot, user_ref.get())

    if not user_doc.exists:
        flash('Không tìm thấy tài khoản client!', 'danger')
        return redirect(url_for('admin_views.admin_client_accounts'))

    user_data = user_doc.to_dict() or {}

    # Chỉ cho phép xóa tài khoản client, không xóa tài khoản admin
    if user_data.get('role_id') != 2:
        flash('Chỉ có thể xóa tài khoản client.', 'danger')
        return redirect(url_for('admin_views.admin_client_accounts'))

    user_ref.delete()
    clear_universal_cache()

    flash(
        f"Đã xóa tài khoản '{user_data.get('user_name', user_id)}'.",
        'success',
    )
    return redirect(url_for('admin_views.admin_client_accounts'))