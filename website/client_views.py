from datetime import datetime, timedelta,date
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from google.cloud.firestore import Query  # Import trực tiếp Query từ google.cloud để tránh lỗi Pylance
from typing import Any, cast
from google.cloud.firestore_v1.client import Client as FirestoreClient
from google.cloud.firestore_v1.base_query import FieldFilter


from firebase_admin import firestore
from website.utils import send_mail_based_on_admin_config
import pytz
client_views = Blueprint("client_views", __name__)


def get_db() -> FirestoreClient:
    return cast(FirestoreClient, firestore.client())

@client_views.route("/")
@login_required
def home():
    vietnam_tz = pytz.timezone("Asia/Ho_Chi_Minh")
    current_week = datetime.now(vietnam_tz).isocalendar()[1]

    db = get_db()
    all_days_in_week = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    schedule_by_day = {day: [] for day in all_days_in_week}

    conf_ref = (
        db.collection("statuses")
        .where(filter=FieldFilter("name", "==", "Đã xác nhận"))
        .limit(1)
        .stream()
    )
    conf_list = list(conf_ref)

    registrations = []
    if conf_list:
        approved_status_id = conf_list[0].id
        regs_stream = (
            db.collection("registrations")
            .where(filter=FieldFilter("week_number", "==", current_week))
            .where(filter=FieldFilter("status_id", "==", approved_status_id))
            .stream()
        )
        registrations = [doc.to_dict() or {} for doc in regs_stream]

    for reg in registrations:
        user_id = reg.get("user_id")
        if not user_id:
            continue

        u_doc = cast(
            Any,
            db.collection("users").document(str(user_id)).get(),
        )
        if not u_doc.exists:
            continue

        user_info = u_doc.to_dict() or {}
        user_name = user_info.get(
            "user_name",
            user_info.get("username", "Thành viên"),
        )
        raw_off_days = reg.get("selected_days")

        off_days_list = (
            [
                day.strip()
                .replace("Thứ ", "T")
                .replace("Chủ Nhật", "CN")
                .replace("Thứ Hai", "T2")
                .replace("Thứ Ba", "T3")
                .replace("Thứ Tư", "T4")
                .replace("Thứ Năm", "T5")
                .replace("Thứ Sáu", "T6")
                .replace("Thứ Bảy", "T7")
                for day in raw_off_days.split(",")
            ]
            if raw_off_days
            else []
        )

        working_days = [
            day for day in all_days_in_week
            if day not in off_days_list
        ]

        for day in working_days:
            if day in schedule_by_day and user_name not in schedule_by_day[day]:
                schedule_by_day[day].append(user_name)

    # Dữ liệu mẫu khi tuần hiện tại chưa có lịch
    if not any(schedule_by_day.values()):
        schedule_by_day = {
            "T2": ["Nguyễn Văn An", "Trần Văn Bình"],
            "T3": ["Lê Văn Cường"],
            "T4": ["Phạm Văn Dũng", "Hoàng Văn Em", "Đỗ Văn Phong"],
            "T5": ["Vũ Văn Giang"],
            "T6": ["Bùi Văn Hải", "Ngô Văn Hùng"],
            "T7": ["Dương Văn Khải"],
            "CN": ["Lý Văn Long", "Hồ Văn Minh"],
        }

    unique_users_in_week = {
        name
        for day_list in schedule_by_day.values()
        for name in day_list
    }

    return render_template(
        "clients/client_home.html",
        user=current_user,
        schedule_by_day=schedule_by_day,
        total_personnel=len(unique_users_in_week),
    )


@client_views.route("/shift")
@login_required
def client_shift():
    vietnam_tz = pytz.timezone("Asia/Ho_Chi_Minh")
    now = datetime.now(vietnam_tz)

    # Lịch mặc định là tuần tới.
    target_date = now + timedelta(days=7)
    target_year, target_week, _ = target_date.isocalendar()
    target_key = (target_year, target_week)

    db = get_db()

    user_doc = cast(
        Any,
        db.collection("users")
        .document(str(current_user.id))
        .get(),
    )
    user_data = user_doc.to_dict() or {}

    try:
        allowed_off_days = int(
            user_data.get(
                "allowed_off_days",
                getattr(current_user, "allowed_off_days", 2),
            )
        )
    except (TypeError, ValueError):
        allowed_off_days = 2

    def parse_days(raw_days):
        if isinstance(raw_days, str):
            values = raw_days.split(",")
        elif isinstance(raw_days, (list, tuple, set)):
            values = raw_days
        else:
            values = []

        return [
            str(day).strip()
            for day in values
            if str(day).strip()
        ]

    # Đọc các lịch đã đăng ký của user.
    user_regs = (
        db.collection("registrations")
        .where(filter=FieldFilter("user_id", "==", current_user.id))
        .stream()
    )

    registrations_by_week = {}

    for doc in user_regs:
        reg_data = doc.to_dict() or {}
        reg_year = reg_data.get("week_year")
        reg_week = reg_data.get("week_number")

        if reg_week is None:
            continue

        # Bổ sung week_year cho lịch cũ nếu thiếu.
        if reg_year is None:
            created_at = reg_data.get("created_at")

            if not isinstance(created_at, datetime):
                continue

            reg_year = created_at.isocalendar().year
            doc.reference.update({"week_year": reg_year})

        try:
            week_key = (int(reg_year), int(reg_week))
        except (TypeError, ValueError):
            continue

        registrations_by_week[week_key] = {
            **reg_data,
            "id": doc.id,
        }

    target_registration = registrations_by_week.get(target_key)

    # Chỉ cho đăng ký thứ Bảy và Chủ nhật đến 16:00.
    registration_window_open = (
        now.weekday() == 5
        or (
            now.weekday() == 6
            and (now.hour, now.minute, now.second) <= (16, 0, 0)
        )
    )

    can_register = (
        target_registration is None
        and registration_window_open
    )

    if target_registration:
        selected_days = parse_days(
            target_registration.get("selected_days")
        )
        readonly_message = "Bạn đã đăng ký tuần tới rồi. Lịch này chỉ xem."
    else:
        selected_days = []

        if not registration_window_open and now.weekday() < 5:
            readonly_message = "Đăng ký tuần tới sẽ mở từ thứ Bảy."
        elif not registration_window_open:
            readonly_message = "Đã hết hạn đăng ký tuần tới."
        else:
            readonly_message = ""

    # Lấy lịch gần nhất trước tuần tới.
    previous_week_keys = [
        week_key
        for week_key in registrations_by_week
        if week_key < target_key
    ]

    nearest_registration = None

    if previous_week_keys:
        previous_year, previous_week = max(previous_week_keys)
        previous_data = registrations_by_week[
            (previous_year, previous_week)
        ]

        previous_monday = date.fromisocalendar(
            previous_year,
            previous_week,
            1,
        )
        previous_sunday = previous_monday + timedelta(days=6)

        nearest_registration = {
            "week_label": (
                f"Tuần {previous_week}/{previous_year} "
                f"({previous_monday.strftime('%d/%m')} - "
                f"{previous_sunday.strftime('%d/%m')})"
            ),
            "selected_days": parse_days(
                previous_data.get("selected_days")
            ),
        }

    # Ngày của tuần đăng ký và thời gian mở đăng ký.
    target_monday = date.fromisocalendar(target_year, target_week, 1)
    target_sunday = target_monday + timedelta(days=6)

    day_codes = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    target_day_dates = {
        code: (
            target_monday + timedelta(days=index)
        ).strftime("%d/%m/%Y")
        for index, code in enumerate(day_codes)
    }

    registration_start = target_monday - timedelta(days=2)
    registration_end = target_monday - timedelta(days=1)

    registration_window_label = (
        f"{registration_start.strftime('%d/%m/%Y')} "
        f"đến {registration_end.strftime('%d/%m/%Y')} lúc 16:00"
    )

    target_week_label = f"Tuần {target_week}/{target_year}"
    target_week_range = (
        f"{target_monday.strftime('%d/%m')} - "
        f"{target_sunday.strftime('%d/%m')}"
    )

    # Đếm số người đã được xác nhận trong tuần tới.
    all_days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    working_counts = {day: 0 for day in all_days}
    total_capacity = 4

    status_docs = list(
        db.collection("statuses")
        .where(filter=FieldFilter("name", "==", "Đã xác nhận"))
        .limit(1)
        .stream()
    )

    if status_docs:
        confirmed_status_id = status_docs[0].id

        confirmed_regs = (
            db.collection("registrations")
            .where(filter=FieldFilter("week_year", "==", target_year))
            .where(filter=FieldFilter("week_number", "==", target_week))
            .where(
                filter=FieldFilter(
                    "status_id",
                    "==",
                    confirmed_status_id,
                )
            )
            .stream()
        )

        day_aliases = {
            "THỨ HAI": "T2",
            "THỨ BA": "T3",
            "THỨ TƯ": "T4",
            "THỨ NĂM": "T5",
            "THỨ SÁU": "T6",
            "THỨ BẢY": "T7",
            "CHỦ NHẬT": "CN",
        }

        for doc in confirmed_regs:
            reg_data = doc.to_dict() or {}
            off_days = {
                day_aliases.get(day.upper(), day.upper())
                for day in parse_days(reg_data.get("selected_days"))
            }

            for day in all_days:
                if day not in off_days:
                    working_counts[day] += 1

    return render_template(
        "clients/client_shift.html",
        user=current_user,
        allowed_off_days=allowed_off_days,
        working_counts=working_counts,
        total_capacity=total_capacity,
        target_year=target_year,
        target_week=target_week,
        target_week_label=target_week_label,
        target_week_range=target_week_range,
        target_day_dates=target_day_dates,
        registration_window_label=registration_window_label,
        selected_days=selected_days,
        can_register=can_register,
        readonly_message=readonly_message,
        nearest_registration=nearest_registration,
    )
@client_views.route("/register-schedule", methods=["POST"])
@login_required
def register_schedule():
    vietnam_tz = pytz.timezone("Asia/Ho_Chi_Minh")
    current_date = datetime.now(vietnam_tz)

    # Mở đăng ký thứ Bảy và Chủ nhật đến 16:00.
    is_saturday = current_date.weekday() == 5
    is_sunday_before_deadline = (
        current_date.weekday() == 6
        and (
            current_date.hour,
            current_date.minute,
            current_date.second,
        ) <= (16, 0, 0)
    )

    if not (is_saturday or is_sunday_before_deadline):
        return jsonify({
            "status": "error",
            "message": (
                "Chỉ được đăng ký lịch tuần tới từ thứ Bảy "
                "đến Chủ nhật lúc 16:00."
            ),
        }), 403

    try:
        db = get_db()

        data = request.get_json(silent=True) or {}
        selected_off_days = data.get("days", [])

        if not isinstance(selected_off_days, list):
            return jsonify({
                "status": "error",
                "message": "Danh sách ngày nghỉ không hợp lệ.",
            }), 400

        day_aliases = {
            "T2": "T2",
            "THỨ HAI": "T2",
            "T3": "T3",
            "THỨ BA": "T3",
            "T4": "T4",
            "THỨ TƯ": "T4",
            "T5": "T5",
            "THỨ NĂM": "T5",
            "T6": "T6",
            "THỨ SÁU": "T6",
            "T7": "T7",
            "THỨ BẢY": "T7",
            "CN": "CN",
            "CHỦ NHẬT": "CN",
        }

        normalized_days = []
        for value in selected_off_days:
            if not isinstance(value, str):
                continue

            normalized = day_aliases.get(value.strip().upper())
            if normalized and normalized not in normalized_days:
                normalized_days.append(normalized)

        all_days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

        if len(normalized_days) != len(selected_off_days):
            return jsonify({
                "status": "error",
                "message": "Có ngày nghỉ không hợp lệ hoặc bị trùng.",
            }), 400

        # Lấy hạn mức ngày nghỉ mới nhất của user.
        user_doc = cast(
            Any,
            db.collection("users")
            .document(str(current_user.id))
            .get(),
        )
        user_data = user_doc.to_dict() or {}

        try:
            allowed_limit = int(
                user_data.get(
                    "allowed_off_days",
                    getattr(current_user, "allowed_off_days", 2),
                )
            )
        except (TypeError, ValueError):
            allowed_limit = 2

        if len(normalized_days) > allowed_limit:
            return jsonify({
                "status": "error",
                "message": (
                    f"Vui lòng chọn không quá {allowed_limit} "
                    "ngày không trực."
                ),
            }), 400

        # Chọn tuần tới, có cả năm ISO để phân biệt tuần qua năm mới.
        target_date = current_date + timedelta(days=7)
        target_year, target_week, _ = target_date.isocalendar()

        # Chặn đăng ký trùng cho user trong tuần mục tiêu,
        # bất kể lịch cũ đang ở trạng thái nào.
        user_regs = (
            db.collection("registrations")
            .where(
                filter=FieldFilter(
                    "user_id",
                    "==",
                    current_user.id,
                )
            )
            .stream()
        )

        for reg_doc in user_regs:
            reg_data = reg_doc.to_dict() or {}

            try:
                same_week = (
                    int(reg_data.get("week_year")) == target_year
                    and int(reg_data.get("week_number")) == target_week
                )
            except (TypeError, ValueError):
                same_week = False

            if same_week:
                return jsonify({
                    "status": "error",
                    "message": "Bạn đã đăng ký lịch tuần này rồi!",
                }), 400

        user_working_days = [
            day for day in all_days
            if day not in normalized_days
        ]

        # Tìm trạng thái đã xác nhận để tính sức chứa tuần tới.
        confirmed_statuses = list(
            db.collection("statuses")
            .where(
                filter=FieldFilter(
                    "name",
                    "==",
                    "Đã xác nhận",
                )
            )
            .limit(1)
            .stream()
        )

        if confirmed_statuses:
            confirmed_status_id = confirmed_statuses[0].id

            confirmed_regs = (
                db.collection("registrations")
                .where(
                    filter=FieldFilter(
                        "week_year",
                        "==",
                        target_year,
                    )
                )
                .where(
                    filter=FieldFilter(
                        "week_number",
                        "==",
                        target_week,
                    )
                )
                .where(
                    filter=FieldFilter(
                        "status_id",
                        "==",
                        confirmed_status_id,
                    )
                )
                .stream()
            )

            current_counts = {day: 0 for day in all_days}

            for reg_doc in confirmed_regs:
                reg_data = reg_doc.to_dict() or {}
                raw_off_days = reg_data.get("selected_days") or []

                if isinstance(raw_off_days, str):
                    off_values = raw_off_days.split(",")
                elif isinstance(raw_off_days, (list, tuple, set)):
                    off_values = raw_off_days
                else:
                    off_values = []

                off_days = set()
                for value in off_values:
                    if isinstance(value, str):
                        day = day_aliases.get(value.strip().upper())
                        if day:
                            off_days.add(day)

                for day in all_days:
                    if day not in off_days:
                        current_counts[day] += 1

            max_capacity = 4

            for day in user_working_days:
                if current_counts[day] >= max_capacity:
                    return jsonify({
                        "status": "error",
                        "message": (
                            f"Ngày {day} đã đủ số lượng tối đa "
                            f"({max_capacity} người). "
                            "Vui lòng chọn ngày nghỉ khác!"
                        ),
                    }), 400

        # Tìm hoặc tạo trạng thái chờ xác nhận.
        pending_statuses = list(
            db.collection("statuses")
            .where(
                filter=FieldFilter(
                    "name",
                    "==",
                    "Chờ xác nhận",
                )
            )
            .limit(1)
            .stream()
        )

        if pending_statuses:
            pending_status_id = pending_statuses[0].id
        else:
            pending_status_ref = db.collection("statuses").document()
            pending_status_ref.set({"name": "Chờ xác nhận"})
            pending_status_id = pending_status_ref.id

        db.collection("registrations").add({
            "selected_days": ",".join(normalized_days),
            "session": "Cả tuần",
            "week_year": target_year,
            "week_number": target_week,
            "created_at": current_date,
            "user_id": current_user.id,
            "status_id": pending_status_id,
        })

        return jsonify({
            "status": "success",
            "message": (
                f"Đăng ký thành công cho tuần "
                f"{target_week}/{target_year}!"
            ),
        }), 200

    except Exception as exc:
        return jsonify({
            "status": "error",
            "message": str(exc),
        }), 500

@client_views.route("/DetailShift")
@login_required
def client_detailshift():
    vietnam_tz = pytz.timezone("Asia/Ho_Chi_Minh")
    now = datetime.now(vietnam_tz)
    current_iso_year, current_week, _ = now.isocalendar()

    db = get_db()
    regs_stream = (
        db.collection("registrations")
        .where(filter=FieldFilter("user_id", "==", current_user.id))
        .stream()
    )

    all_days_in_week = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    day_aliases = {
        "THỨ HAI": "T2",
        "THỨ BA": "T3",
        "THỨ TƯ": "T4",
        "THỨ NĂM": "T5",
        "THỨ SÁU": "T6",
        "THỨ BẢY": "T7",
        "CHỦ NHẬT": "CN",
    }

    class StatusObj:
        def __init__(self, name):
            self.name = name

    class RegObj:
        def __init__(self, data):
            self.__dict__.update(data)

    all_regs = []

    for doc in regs_stream:
        r_data = doc.to_dict() or {}
        r_data["id"] = doc.id

        # Hỗ trợ selected_days dạng "T3,T4,CN" hoặc ["T3", "T4", "CN"].
        raw_off = r_data.get("selected_days") or ""
        if isinstance(raw_off, str):
            off_days = raw_off.split(",")
        elif isinstance(raw_off, (list, tuple, set)):
            off_days = raw_off
        else:
            off_days = []

        off_days_normalized = set()
        for value in off_days:
            if isinstance(value, str):
                day = value.strip().upper()
                off_days_normalized.add(day_aliases.get(day, day))

        r_data["working_days"] = [
            day for day in all_days_in_week
            if day not in off_days_normalized
        ]

        status_name = ""
        status_id = r_data.get("status_id")

        if status_id:
            status_doc = cast(
                Any,
                db.collection("statuses")
                .document(str(status_id))
                .get(),
            )

            if status_doc.exists:
                status_data = status_doc.to_dict() or {}
                status_name = status_data.get("name", "")

        r_data["status_obj"] = StatusObj(status_name)

        # Với lịch cũ chưa có week_year, suy ra từ created_at.
        week_year = r_data.get("week_year")
        if week_year is None:
            created_at = r_data.get("created_at")
            if isinstance(created_at, datetime):
                week_year = created_at.isocalendar().year

        try:
            r_data["week_year"] = int(week_year)
            r_data["week_number"] = int(r_data.get("week_number"))
        except (TypeError, ValueError):
            # Bỏ qua bản ghi thiếu năm hoặc số tuần hợp lệ.
            continue

        all_regs.append(RegObj(r_data))

    all_regs.sort(
        key=lambda reg: (reg.week_year, reg.week_number),
        reverse=True,
    )

    upcoming_regs = []
    history_regs = []

    for reg in all_regs:
        is_confirmed = reg.status_obj.name == "Đã xác nhận"
        is_past_week = (
            (reg.week_year, reg.week_number)
            < (current_iso_year, current_week)
        )

        if is_confirmed or is_past_week:
            history_regs.append(reg)
        else:
            upcoming_regs.append(reg)

    return render_template(
        "clients/client_DetailShift.html",
        user=current_user,
        upcoming_regs=upcoming_regs,
        history_regs=history_regs,
    )


@client_views.route("/request-change/<string:id>", methods=["POST"])
@login_required
def request_change_shift(id: str):
    db = get_db()
    reg_doc = cast(
        Any,
        db.collection("registrations").document(id).get(),
    )

    if not reg_doc.exists:
        flash("Không tìm thấy lịch trực.", "danger")
        return redirect(url_for("client_views.client_detailshift"))

    reg = reg_doc.to_dict() or {}
    if reg.get("user_id") != current_user.id:
        flash("Bạn không có quyền thực hiện thao tác này.", "danger")
        return redirect(url_for("client_views.client_detailshift"))

    flash(
        f'Đã gửi phiếu thay đổi lịch tuần {reg.get("week_number")} thành công đến Admin!',
        "success",
    )
    return redirect(url_for("client_views.client_detailshift"))

@client_views.route("/edit-shift/<string:id>", methods=["GET", "POST"])
@login_required
def edit_shift(id: str):
    db = get_db()
    reg_ref = db.collection("registrations").document(id)
    reg_doc = cast(Any, reg_ref.get())

    if not reg_doc.exists:
        flash("Không tìm thấy lịch trực.", "danger")
        return redirect(url_for("client_views.client_detailshift"))

    reg_data = reg_doc.to_dict() or {}
    reg_data["id"] = reg_doc.id

    if reg_data.get("user_id") != current_user.id:
        flash("Bạn không có quyền chỉnh sửa lịch này.", "danger")
        return redirect(url_for("client_views.client_detailshift"))

    if request.method == "POST":
        u_doc = cast(
            Any,
            db.collection("users").document(str(current_user.id)).get(),
        )

        max_off = getattr(current_user, "allowed_off_days", 2)
        if u_doc.exists:
            u_info = u_doc.to_dict() or {}
            max_off = u_info.get("allowed_off_days", max_off)

        max_off = int(max_off)
        days_list = []

        for i in range(max_off):
            day_val = request.form.get(f"day_{i + 1}")
            if day_val and day_val not in days_list:
                days_list.append(day_val)

        selected_days_str = ", ".join(days_list) if days_list else ""
        session_val = request.form.get("session", "Cả tuần")

        current_status_name = ""
        current_status_id = reg_data.get("status_id")
        if current_status_id:
            status_doc = cast(
                Any,
                db.collection("statuses").document(str(current_status_id)).get(),
            )
            if status_doc.exists:
                current_status_name = (status_doc.to_dict() or {}).get("name", "")

        if current_status_name == "Đã xác nhận":
            # Lịch đã chốt: giữ nguyên lịch cũ, chỉ ghi yêu cầu đổi để admin duyệt.
            reg_ref.update({
                "pending_selected_days": selected_days_str,
                "pending_session": session_val,
                "has_pending_change": True,
                "change_requested_at": datetime.now(),
            })
            action_label = "gửi yêu cầu đổi lịch"
        else:
            pend_ref = (
                db.collection("statuses")
                .where(filter=FieldFilter("name", "==", "Chờ xác nhận"))
                .limit(1)
                .stream()
            )
            pend_list = list(pend_ref)
            pending_status_id = pend_list[0].id if pend_list else None

            reg_ref.update({
                "selected_days": selected_days_str,
                "session": session_val,
                "status_id": pending_status_id,
                "has_pending_change": False,
                "pending_selected_days": None,
                "pending_session": None,
                "change_requested_at": None,
            })
            action_label = "cập nhật lịch"

        current_time_str = datetime.now().strftime("%d/%m/%Y lúc %H:%M")

        db.collection("notifications").add({
            "user_id": current_user.id,
            "title": "Yêu cầu sửa lịch trực (Chờ duyệt)",
            "message": (
                f"{current_user.user_name} vừa thay đổi lịch trực "
                f"tuần {reg_data.get('week_number')} vào lúc {current_time_str}."
            ),
            "status": "pending",
            "is_read": False,
            "created_at": datetime.now(),
        })

        try:
            email_subject = (
                f"[HỆ THỐNG] Xác nhận yêu cầu sửa lịch trực "
                f"tuần {reg_data.get('week_number')}"
            )
            email_body = (
                f"Xin chào {current_user.user_name},\n\n"
                f"Bạn vừa cập nhật lại lịch trực tuần "
                f"{reg_data.get('week_number')} vào lúc {current_time_str}.\n"
                f"- Ca trực: {session_val}\n"
                f"- Các ngày nghỉ đăng ký: {selected_days_str}\n\n"
                "Yêu cầu của bạn đang ở trạng thái chờ duyệt từ quản trị viên.\n\n"
                "Trân trọng!"
            )
            if current_user.email:
                send_mail_based_on_admin_config(
                    email_subject,
                    [current_user.email],
                    email_body,
                )
        except Exception as e:
            print(f"Lỗi gửi email: {e}")

        flash(
            f"Đã {action_label} và gửi thông báo đến admin!",
            "success",
        )
        return redirect(url_for("client_views.client_detailshift"))

    class RegObj:
        def __init__(self, data):
            self.__dict__.update(data)

    return render_template(
        "clients/client_edit_shift.html",
        reg=RegObj(reg_data),
    )

@client_views.route("/notifications")
@login_required
def notifications():
    vietnam_tz = pytz.timezone("Asia/Ho_Chi_Minh")
    now = datetime.now(vietnam_tz)
    db = get_db()

    notifs_stream = (
        db.collection("notifications")
        .where(filter=FieldFilter("user_id", "==", current_user.id))
        .stream()
    )

    user_notifications = []
    one_hour_ago = now - timedelta(hours=1)

    batch = db.batch()
    has_deletes = False

    for doc in notifs_stream:
        n_data = doc.to_dict() or {}
        n_data["id"] = doc.id
        created_at = n_data.get("created_at")

        if isinstance(created_at, datetime) and created_at < one_hour_ago:
            batch.delete(doc.reference)
            has_deletes = True
            continue

        if not n_data.get("is_read", False):
            batch.update(doc.reference, {"is_read": True})
            n_data["is_read"] = True
            has_deletes = True

        class NotifObj:

            def __init__(self, data):
                self.__dict__.update(data)

        user_notifications.append(NotifObj(n_data))

    if has_deletes:
        batch.commit()

    user_notifications.sort(
        key=lambda x: x.created_at
        if isinstance(x.created_at, datetime)
        else datetime.min,
        reverse=True,
    )

    return render_template(
        "clients/client_notifications.html", notifications=user_notifications
    )


@client_views.route(
    "/notification/delete/<string:notif_id>", methods=["POST", "GET"]
)
@login_required
def delete_notification(notif_id: str):
    db = get_db()
    notif_ref = db.collection("notifications").document(notif_id)
    notif_doc = cast(Any, notif_ref.get())
    notif_data = notif_doc.to_dict() or {}

    if (
        notif_doc.exists
        and notif_data
        and notif_data.get("user_id") == current_user.id
    ):
        notif_ref.delete()
        flash("Đã xóa thông báo thành công!", "success")
    else:
        flash(
            "Không tìm thấy thông báo hoặc bạn không có quyền xóa.",
            "danger",
        )

    return redirect(url_for("client_views.notifications"))

@client_views.route("/profile", methods=["GET", "POST"])
@login_required
def update_profile():
    db = get_db()
    if request.method == "POST":
        new_full_name = request.form.get("full_name")
        if new_full_name:
            db.collection("users").document(current_user.id).update(
                {"full_name": new_full_name}
            )
            current_user.full_name = new_full_name
            flash("Cập nhật Họ và tên thành công!", "success")

        return redirect(url_for("client_views.update_profile"))

    return render_template("clients/client_profile.html", user=current_user)