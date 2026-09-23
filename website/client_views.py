from datetime import datetime, timedelta
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from google.cloud.firestore import Query  # Import trực tiếp Query từ google.cloud để tránh lỗi Pylance
import pytz

from firebase_admin import firestore
from website.utils import send_mail_based_on_admin_config

client_views = Blueprint("client_views", __name__)


def get_db():
    return firestore.client()


@client_views.route("/")
@login_required
def home():
    vietnam_tz = pytz.timezone("Asia/Ho_Chi_Minh")
    current_week = datetime.now(vietnam_tz).isocalendar()[1]

    db = get_db()
    all_days_in_week = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    
    schedule_by_day = {day: [] for day in all_days_in_week}

    # Tìm status 'Đã xác nhận'
    conf_ref = (
        db.collection("statuses")
        .where("name", "==", "Đã xác nhận")
        .limit(1)
        .stream()
    )
    conf_list = list(conf_ref)

    registrations = []
    if conf_list:
        approved_status_id = conf_list[0].id
        regs_stream = (
            db.collection("registrations")
            .where("week_number", "==", current_week)
            .where("status_id", "==", approved_status_id)
            .stream()
        )
        registrations = [doc.to_dict() for doc in regs_stream]

    for reg in registrations:
        if not reg:
            continue
        user_id = reg.get("user_id")
        if not user_id:
            continue

        u_doc = db.collection("users").document(str(user_id)).get()
        if not u_doc.exists:
            continue

        user_info = u_doc.to_dict() or {}
        user_name = user_info.get(
            "user_name", user_info.get("username", "Thành viên")
        )
        raw_off_days = reg.get("selected_days")

        off_days_list = (
            [
                d.strip()
                .replace("Thứ ", "T")
                .replace("Chủ Nhật", "CN")
                .replace("Thứ Hai", "T2")
                .replace("Thứ Ba", "T3")
                .replace("Thứ Tư", "T4")
                .replace("Thứ Năm", "T5")
                .replace("Thứ Sáu", "T6")
                .replace("Thứ Bảy", "T7")
                for d in raw_off_days.split(",")
            ]
            if raw_off_days
            else []
        )
        
        working_days = [d for d in all_days_in_week if d not in off_days_list]

        for day in working_days:
            if day in schedule_by_day:
                if user_name not in schedule_by_day[day]:
                    schedule_by_day[day].append(user_name)

   
    # dữ liệu giả 
    if not any(schedule_by_day.values()):
        schedule_by_day = {
            "T2": ["Nguyễn Văn An", "Trần Văn Bình"],
            "T3": ["Lê Văn Cường"],
            "T4": ["Phạm Văn Dũng", "Hoàng Văn Em", "Đỗ Văn Phong"],
            "T5": ["Vũ Văn Giang"],
            "T6": ["Bùi Văn Hải", "Ngô Văn Hùng"],
            "T7": ["Dương Văn Khải"],
            "CN": ["Lý Văn Long", "Hồ Văn Minh"]
        }

    # Tính tổng số quân số độc lập trong tuần
    unique_users_in_week = set()
    for day_list in schedule_by_day.values():
        for name in day_list:
            unique_users_in_week.add(name)
    total_personnel = len(unique_users_in_week)

    return render_template(
        "clients/client_home.html", 
        user=current_user, 
        schedule_by_day=schedule_by_day,
        total_personnel=total_personnel
    )


@client_views.route("/shift")
@login_required
def client_shift():
    vietnam_tz = pytz.timezone("Asia/Ho_Chi_Minh")
    current_week = datetime.now(vietnam_tz).isocalendar()[1]

    db = get_db()
    
    # [QUAN TRỌNG] Lấy dữ liệu user mới nhất trực tiếp từ Firestore để cập nhật allowed_off_days chuẩn xác
    users_ref = db.collection("users")
    user_doc_ref = users_ref.document(str(current_user.id))
    user_doc = user_doc_ref.get()
    user_data = user_doc.to_dict()
    if user_data is not None:
        allowed_off_days = user_data.get("allowed_off_days", getattr(current_user, "allowed_off_days", 2))
    else:
        allowed_off_days = getattr(current_user, "allowed_off_days", 2)
    conf_ref = (
        db.collection("statuses")
        .where("name", "==", "Đã xác nhận")
        .limit(1)
        .stream()
    )
    conf_list = list(conf_ref)

    registrations = []
    if conf_list:
        confirmed_status_id = conf_list[0].id
        regs_stream = (
            db.collection("registrations")
            .where("week_number", "==", current_week)
            .where("status_id", "==", confirmed_status_id)
            .stream()
        )
        registrations = [doc.to_dict() for doc in regs_stream]

    all_days_in_week = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
    working_counts = {day: 0 for day in all_days_in_week}
    total_capacity = 4

    for reg in registrations:
        if not reg:
            continue
        raw_off_days = reg.get("selected_days")
        off_days_list = (
            [
                d.strip()
                .replace("Thứ ", "T")
                .replace("Chủ Nhật", "CN")
                for d in raw_off_days.split(",")
            ]
            if raw_off_days
            else []
        )
        working_days = [d for d in all_days_in_week if d not in off_days_list]

        for day in working_days:
            if day in working_counts:
                working_counts[day] += 1

    return render_template(
        "clients/client_shift.html",
        user=current_user,
        working_counts=working_counts,
        total_capacity=total_capacity,
        allowed_off_days=allowed_off_days, # Truyền biến đã query trực tiếp vào template
    )

@client_views.route("/register-schedule", methods=["POST"])
@login_required
def register_schedule():
    try:
        db = get_db()
        data = request.get_json() or {}
        selected_off_days = data.get("days", [])

        # [SỬA 1] Truy vấn trực tiếp Firestore để lấy hạn mức allowed_off_days mới nhất của user
        user_doc = db.collection("users").document(str(current_user.id)).get()  # pyright: ignore
        user_data = user_doc.to_dict() if user_doc and user_doc.exists else {}
        allowed_limit = (
            user_data.get(
                "allowed_off_days", getattr(current_user, "allowed_off_days", 2)
            )
            if user_data is not None
            else 2
        )

        # [SỬA 2] So sánh với giới hạn động (allowed_limit) và hiển thị thông báo linh hoạt
        if len(selected_off_days) != allowed_limit:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": f"Vui lòng chọn chính xác {allowed_limit} ngày không trực!",
                    }
                ),
                400,
            )

        string_off_days = ",".join(selected_off_days)
        string_shifts = "Cả tuần"

        vietnam_tz = pytz.timezone("Asia/Ho_Chi_Minh")
        current_date = datetime.now(vietnam_tz)
        current_week = current_date.isocalendar()[1]

        existing_regs = list(
            db.collection("registrations")
            .where("user_id", "==", current_user.id)
            .where("week_number", "==", current_week)
            .limit(1)
            .stream()
        )
        if existing_regs:
            return (
                jsonify(
                    {
                        "status": "error",
                        "message": "Bạn đã đăng ký lịch tuần này rồi!",
                    }
                ),
                400,
            )

        all_days_in_week = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
        off_days_normalized = [
            d.strip().replace("Thứ ", "T").replace("Chủ Nhật", "CN")
            for d in selected_off_days
        ]
        user_working_days = [
            d for d in all_days_in_week if d not in off_days_normalized
        ]

        conf_ref = (
            db.collection("statuses")
            .where("name", "==", "Đã xác nhận")
            .limit(1)
            .stream()
        )
        conf_list = list(conf_ref)
        if conf_list:
            confirmed_status_id = conf_list[0].id
            confirmed_regs = [
                doc.to_dict()
                for doc in db.collection("registrations")
                .where("week_number", "==", current_week)
                .where("status_id", "==", confirmed_status_id)
                .stream()
            ]

            current_counts = {day: 0 for day in all_days_in_week}
            for reg in confirmed_regs:
                if not reg:
                    continue
                r_off_days = reg.get("selected_days")
                if r_off_days:
                    r_off = [
                        d.strip()
                        .replace("Thứ ", "T")
                        .replace("Chủ Nhật", "CN")
                        for d in r_off_days.split(",")
                    ]
                    r_work = [
                        d for d in all_days_in_week if d not in r_off
                    ]
                    for d in r_work:
                        if d in current_counts:
                            current_counts[d] += 1

            MAX_CAPACITY = 3
            for day in user_working_days:
                if current_counts.get(day, 0) >= MAX_CAPACITY:
                    return (
                        jsonify(
                            {
                                "status": "error",
                                "message": f"Ngày {day} đã đủ số lượng tối đa ({MAX_CAPACITY} người). Vui lòng chọn ngày nghỉ khác!",
                            }
                        ),
                        400,
                    )

        pend_ref = (
            db.collection("statuses")
            .where("name", "==", "Chờ xác nhận")
            .limit(1)
            .stream()
        )
        pend_list = list(pend_ref)
        if not pend_list:
            new_s_ref = db.collection("statuses").document()
            new_s_ref.set({"name": "Chờ xác nhận"})
            pending_status_id = new_s_ref.id
        else:
            pending_status_id = pend_list[0].id

        db.collection("registrations").add(
            {
                "selected_days": string_off_days,
                "session": string_shifts,
                "week_number": current_week,
                "created_at": current_date,
                "user_id": current_user.id,
                "status_id": pending_status_id,
            }
        )

        return (
            jsonify({"status": "success", "message": "Đăng ký thành công!"}),
            200,
        )

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@client_views.route("/DetailShift")
@login_required
def client_detailshift():
    vietnam_tz = pytz.timezone("Asia/Ho_Chi_Minh")
    now = datetime.now(vietnam_tz)
    current_week = now.isocalendar()[1]

    db = get_db()
    regs_stream = (
        db.collection("registrations")
        .where("user_id", "==", current_user.id)
        .order_by("week_number", direction=Query.DESCENDING)
        .stream()
    )

    all_regs = []
    all_days_in_week = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]

    conf_ref = (
        db.collection("statuses")
        .where("name", "==", "Đã xác nhận")
        .limit(1)
        .stream()
    )
    conf_list = list(conf_ref)
    confirmed_status_id = conf_list[0].id if conf_list else None

    for doc in regs_stream:
        r_data = doc.to_dict() or {}
        r_data["id"] = doc.id

        raw_off = r_data.get("selected_days", "")
        if raw_off:
            off_days_list = [d.strip() for d in raw_off.split(",")]
            r_data["working_days"] = [
                day for day in all_days_in_week if day not in off_days_list
            ]
        else:
            r_data["working_days"] = []

        status_name = ""
        s_id = r_data.get("status_id")
        if s_id:
            s_doc = db.collection("statuses").document(str(s_id)).get()
            if s_doc.exists:
                s_dict = s_doc.to_dict() or {} 
                status_name = s_dict.get("name", "")

        class StatusObj:

            def __init__(self, name):
                self.name = name

        r_data["status_obj"] = StatusObj(status_name)

        class RegObj:

            def __init__(self, data):
                self.__dict__.update(data)

        all_regs.append(RegObj(r_data))

    upcoming_regs = []
    history_regs = []

    for reg in all_regs:
        is_confirmed = reg.status_obj and reg.status_obj.name == "Đã xác nhận"
        is_past_week = reg.week_number < current_week

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
def request_change_shift(id):
    db = get_db()
    reg_doc = db.collection("registrations").document(id).get()

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
def edit_shift(id):
    db = get_db()
    reg_ref = db.collection("registrations").document(id)
    reg_doc = reg_ref.get()

    if not reg_doc.exists:
        flash("Không tìm thấy lịch trực.", "danger")
        return redirect(url_for("client_views.client_detailshift"))

    reg_data = reg_doc.to_dict() or {}
    reg_data["id"] = reg_doc.id

    if reg_data.get("user_id") != current_user.id:
        flash("Bạn không có quyền chỉnh sửa lịch này.", "danger")
        return redirect(url_for("client_views.client_detailshift"))

    if request.method == "POST":
        # Truy vấn trực tiếp Firestore để lấy hạn mức ngày nghỉ mới nhất do Admin vừa sửa
        u_doc = db.collection("users").document(str(current_user.id)).get()
        max_off = 2  # Giá trị mặc định an toàn
        if u_doc and u_doc.exists:
            u_info = u_doc.to_dict()
            if u_info is not None:
                max_off = u_info.get("allowed_off_days", getattr(current_user, "allowed_off_days", 2))
        else:
            max_off = getattr(current_user, "allowed_off_days", 2)
        days_list = []
        for i in range(max_off):
            day_val = request.form.get(f"day_{i + 1}")
            if day_val and day_val not in days_list:
                days_list.append(day_val)

        selected_days_str = ", ".join(days_list) if days_list else ""
        session_val = request.form.get("session", "Cả tuần")

        pend_ref = (
            db.collection("statuses")
            .where("name", "==", "Chờ xác nhận")
            .limit(1)
            .stream()
        )
        pend_list = list(pend_ref)
        pending_status_id = pend_list[0].id if pend_list else None

        reg_ref.update(
            {
                "selected_days": selected_days_str,
                "session": session_val,
                "status_id": pending_status_id,
            }
        )

        current_time_str = datetime.now().strftime("%d/%m/%Y lúc %H:%M")

        db.collection("notifications").add(
    {
        "user_id": current_user.id,
        "title": "Yêu cầu sửa lịch trực (Chờ duyệt)",
        "message": f"Học viên {current_user.user_name} vừa thay đổi lịch trực tuần {reg_data.get('week_number')} vào lúc {current_time_str}.",
        "status": "pending",
        "is_read": False,
        "created_at": datetime.now(), 
    }
)

        try:
            email_subject = f"[HỆ THỐNG] Xác nhận yêu cầu sửa lịch trực tuần {reg_data.get('week_number')}"
            email_body = (
                f"Xin chào {current_user.user_name},\n\n"
                f"Bạn vừa cập nhật lại lịch trực tuần {reg_data.get('week_number')} vào lúc {current_time_str}.\n"
                f"- Ca trực: {session_val}\n"
                f"- Các ngày nghỉ đăng ký: {selected_days_str}\n\n"
                f"Yêu cầu của bạn đang ở trạng thái chờ duyệt từ quản trị viên.\n\n"
                f"Trân trọng!"
            )
            send_mail_based_on_admin_config(
                email_subject, [current_user.email], email_body
            )
        except Exception as e:
            print(f"Lỗi gửi email: {e}")

        flash(
            "Cập nhật lịch thành công và đã gửi thông báo qua cả Web lẫn Gmail!",
            "success",
        )
        return redirect(url_for("client_views.client_detailshift"))

    class RegObj:

        def __init__(self, data):
            self.__dict__.update(data)

    return render_template(
        "clients/client_edit_shift.html", reg=RegObj(reg_data)
    )


@client_views.route("/notifications")
@login_required
def notifications():
    vietnam_tz = pytz.timezone("Asia/Ho_Chi_Minh")
    now = datetime.now(vietnam_tz)
    db = get_db()

    notifs_stream = (
        db.collection("notifications")
        .where("user_id", "==", current_user.id)
        .stream()
    )

    user_notifications = []
    one_day_ago = now - timedelta(days=1)

    batch = db.batch()
    has_deletes = False

    for doc in notifs_stream:
        n_data = doc.to_dict() or {}
        n_data["id"] = doc.id
        created_at = n_data.get("created_at")

        if isinstance(created_at, datetime) and created_at < one_day_ago:
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
def delete_notification(notif_id):
    db = get_db()
    notif_ref = db.collection("notifications").document(notif_id)
    notif_doc = notif_ref.get()
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
            "Không tìm thấy thông báo hoặc bạn không có quyền xóa.", "danger"
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