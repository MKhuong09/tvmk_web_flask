import base64
import io
import os
import time
from datetime import datetime, timezone

import numpy as np
from dotenv import load_dotenv
from firebase_admin import firestore
from flask import request
from flask_login import current_user
from flask_socketio import emit, join_room
from threading import Lock
from google import genai
from google.genai import types
from PIL import Image

from . import socketio
from .AI.ai_extractor import extract_emails_from_text


# ---------------------------------------------------------
# Gemini dự phòng khi EasyOCR không trả ra văn bản
# ---------------------------------------------------------
_presence_lock = Lock()
_presence_by_user = {}
_sid_to_user = {}


def publish_presence():
    """Gửi danh sách online: admin thấy tất cả, client chỉ thấy cùng role."""
    with _presence_lock:
        users = [
            {
                "id": user_id,
                "name": info["name"],
                "role_id": info["role_id"],
            }
            for user_id, info in _presence_by_user.items()
        ]

    # Admin nhận danh sách tất cả tài khoản đang online.
    socketio.emit(
        "online_users_update",
        {"users": users},
        to="presence_admin",
    )

    # Mỗi nhóm client chỉ nhận danh sách cùng role_id.
    role_ids = {
        user["role_id"]
        for user in users
        if user["role_id"] != 1
    }

    for role_id in role_ids:
        same_role_users = [
            user for user in users
            if user["role_id"] == role_id
        ]

        socketio.emit(
            "online_users_update",
            {"users": same_role_users},
            to=f"presence_role_{role_id}",
        )
load_dotenv()

gemini_key = os.getenv("GEMINI_API_KEY")
ai_client = None

if gemini_key:
    try:
        ai_client = genai.Client(api_key=gemini_key)
        print("✅ [Gemini AI] Đã kết nối Gemini Client dự phòng!")
    except Exception as exc:
        print(f"⚠️ [Gemini AI] Không thể khởi tạo Client: {exc}")


# ---------------------------------------------------------
# EasyOCR: chỉ nạp mô hình khi cần đọc ảnh
# ---------------------------------------------------------
class OCRAgent:
    def __init__(self):
        self.reader = None

    def _get_reader(self):
        if self.reader is None:
            try:
                import easyocr

                print("[OCRAgent] Đang khởi tạo mô hình...")
                self.reader = easyocr.Reader(["en", "vi"], gpu=False)
                print("[OCRAgent] Mô hình Local OCR đã sẵn sàng!")
            except Exception as exc:
                print(f"⚠️ [OCRAgent] Không thể nạp EasyOCR: {exc}")
                self.reader = False

        return self.reader if self.reader is not False else None

    def extract_text_from_bytes(self, image_bytes: bytes) -> str:
        try:
            reader = self._get_reader()
            if reader is None:
                return ""

            with Image.open(io.BytesIO(image_bytes)) as image:
                image_np = np.array(image.convert("RGB"))

            readtext = getattr(reader, "readtext", None)

            if not callable(readtext):
                 print("[OCRAgent] Reader không có hàm readtext.")
                 return ""

            results = readtext(image_np, detail=0)
            return " ".join(results).strip()

        except Exception as exc:
            print(f"[OCRAgent] Lỗi phân tích hình ảnh: {exc}")
            return ""


ocr_agent = OCRAgent()

# Đọc ảnh bằng EasyOCR, nếu không có kết quả thì thử Gemini
def process_ocr_from_bytes(image_bytes: bytes) -> str:
    raw_text = ocr_agent.extract_text_from_bytes(image_bytes)
    print(f"[OCR DEBUG] Nội dung OCR EasyOCR: {raw_text!r}")

    if raw_text or ai_client is None:
        return raw_text

    print("[OCRAgent] EasyOCR không có kết quả, đang thử Gemini...")

    config = types.GenerateContentConfig(
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            disable=True
        )
    )

    max_retries = 3

    for attempt in range(1, max_retries + 1):
        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                image_for_gemini = image.copy()

            response = ai_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[
                    "Hãy trích xuất toàn bộ văn bản, đặc biệt là địa chỉ email, "
                    "có trong hình ảnh này.",
                    image_for_gemini,
                ],
                config=config,
            )

            return (response.text or "").strip() if response else ""

        except Exception as exc:
            error_text = str(exc)
            retryable = "503" in error_text or "429" in error_text

            if retryable and attempt < max_retries:
                print(
                    f"⚠️ [Gemini] Lỗi tạm thời, thử lại "
                    f"({attempt}/{max_retries}) sau 2 giây..."
                )
                time.sleep(2)
            else:
                print(f"❌ [Gemini Fallback] Lỗi: {exc}")
                break

    return ""

# Lưu email theo document ID chuẩn, đồng thời gom dữ liệu cũ
def save_authorized_email(db, email: str, current_time: datetime) -> bool:
    """
    Lưu email tại authorized_emails/{email}.

    Trả về True nếu tạo giấy phép mới.
    Trả về False nếu email đã có hoặc đã được gom từ dữ liệu cũ.
    """
    collection = db.collection("authorized_emails")
    canonical_ref = collection.document(email)
    canonical_snap = canonical_ref.get()

    # Tìm cả những document cũ được tạo bằng ID tự sinh.
    matching_docs = list(
        collection.where("email", "==", email).stream()
    )

    legacy_docs = [
        doc for doc in matching_docs
        if doc.id != email
    ]

    if canonical_snap.exists:
        canonical_data = canonical_snap.to_dict() or {}
        is_used = bool(canonical_data.get("is_used", False))
        created_at = canonical_data.get("created_at", current_time)
        was_already_authorized = True
    elif legacy_docs:
        # Giữ lại thông tin  cũ thay vì cấp phép lại từ đầu.
        legacy_data = legacy_docs[0].to_dict() or {}
        is_used = any(
            bool((doc.to_dict() or {}).get("is_used", False))
            for doc in legacy_docs
        )
        created_at = legacy_data.get("created_at", current_time)
        was_already_authorized = True
    else:
        is_used = False
        created_at = current_time
        was_already_authorized = False

    # sign_up() có thể tra theo ID email.
    canonical_ref.set({
        "email": email,
        "is_used": is_used,
        "created_at": created_at,
        "used_at": (
            canonical_snap.to_dict() or {}
        ).get("used_at") if canonical_snap.exists else None,
        "registered_by_user_id": (
            (canonical_snap.to_dict() or {}).get("registered_by_user_id")
            if canonical_snap.exists
            else None
        ),
    })

    # Xóa các document cũ trùng email 
    if legacy_docs:
        batch = db.batch()
        for legacy_doc in legacy_docs:
            batch.delete(legacy_doc.reference)
        batch.commit()

    return not was_already_authorized

# SocketIO
@socketio.on("connect")
def handle_connect():
    # Chỉ ghi nhận người dùng đã đăng nhập.
    if not current_user.is_authenticated:
        return False

    user_id = str(current_user.get_id())
    role_id = getattr(current_user, "role_id", None)

    if not user_id or role_id is None:
        return False

    role_id = int(role_id)
    sid = getattr(request, "sid", None)
    if not sid:
     return False

    # Admin vào phòng nhận tất cả; client vào phòng theo role.
    room = (
        "presence_admin"
        if role_id == 1
        else f"presence_role_{role_id}"
    )
    join_room(room)

    with _presence_lock:
        user_info = _presence_by_user.setdefault(
            user_id,
            {
                "name": getattr(current_user, "user_name", None)
                or "Người dùng",
                "role_id": role_id,
                "sids": set(),
            },
        )

        # Một tài khoản có thể mở nhiều tab.
        user_info["sids"].add(sid)
        _sid_to_user[sid] = user_id

    publish_presence()
    print(f"[Presence] {user_id} đã online.")


@socketio.on("disconnect")
def handle_disconnect():
    sid = getattr(request, "sid", None)
    if not sid:
     return

    with _presence_lock:
        user_id = _sid_to_user.pop(sid, None)

        if user_id:
            user_info = _presence_by_user.get(user_id)

            if user_info:
                user_info["sids"].discard(sid)

                # Chỉ offline khi tài khoản đóng hết các tab.
                if not user_info["sids"]:
                    _presence_by_user.pop(user_id, None)

    if user_id:
        publish_presence()
        print(f"[Presence] {user_id} đã offline.")


@socketio.on("admin_process_data")
def handle_process_data(data):
    # Chỉ tài khoản đã đăng nhập với role_id = 1 mới được cấp phép email
    if (
        not current_user.is_authenticated
        or str(getattr(current_user, "role_id", "")) != "1"
    ):
        emit("admin_process_result", {
            "status": "error",
            "message": "Bạn không có quyền thực hiện thao tác này.",
        })
        return

    if not isinstance(data, dict):
        emit("admin_process_result", {
            "status": "error",
            "message": "Dữ liệu gửi lên không hợp lệ.",
        })
        return

    input_type = (data.get("type") or "text").strip().lower()
    content = data.get("content") or ""

    print(f"[Socket] Nhận dữ liệu cấp phép từ Admin (Dạng: {input_type})...")

    if not content:
        emit("admin_process_result", {
            "status": "error",
            "message": "Dữ liệu gửi sang bị rỗng!",
        })
        return

    if input_type == "text":
        raw_text = str(content)

    elif input_type == "image":
        try:
            base64_str = str(content).split(",", 1)[-1]
            image_bytes = base64.b64decode(base64_str, validate=True)
            raw_text = process_ocr_from_bytes(image_bytes)
        except Exception as exc:
            print(f"[Socket] Lỗi giải mã hoặc đọc ảnh: {exc}")
            emit("admin_process_result", {
                "status": "error",
                "message": "Không thể đọc ảnh được gửi lên.",
            })
            return

    else:
        emit("admin_process_result", {
            "status": "error",
            "message": "Loại dữ liệu không được hỗ trợ.",
        })
        return

    try:
        extracted_emails = extract_emails_from_text(raw_text) or []
    except Exception as exc:
        print(f"[EMAIL] Lỗi trích xuất email: {exc}")
        emit("admin_process_result", {
            "status": "error",
            "message": "Có lỗi khi trích xuất email từ nội dung.",
        })
        return

    # Chuẩn hóa chữ hoa/thường, khoảng trắng và loại trùng OCR.
    unique_emails = sorted({
        str(email).strip().lower()
        for email in extracted_emails
        if email and str(email).strip()
    })

    if not unique_emails:
        emit("admin_process_result", {
            "status": "warning",
            "count": 0,
            "duplicates": 0,
            "emails": [],
            "message": "Không tìm thấy địa chỉ email hợp lệ nào trong dữ liệu!",
        })
        return

    added_count = 0
    duplicate_count = 0

    try:
        db = firestore.client()
        current_time = datetime.now(timezone.utc)

        for email in unique_emails:
            was_added = save_authorized_email(db, email, current_time)

            if was_added:
                added_count += 1
            else:
                duplicate_count += 1

        emit("admin_process_result", {
            "status": "success",
            "count": added_count,
            "duplicates": duplicate_count,
            "emails": unique_emails,
            "message": (
                f"Đã cấp phép mới {added_count} email "
                f"(bỏ qua hoặc gom {duplicate_count} email đã tồn tại)."
            ),
        })

    except Exception as exc:
        print(f"[Database] Lỗi lưu email được cấp phép: {exc}")
        emit("admin_process_result", {
            "status": "error",
            "message": f"Lỗi hệ thống khi lưu dữ liệu: {exc}",
        })