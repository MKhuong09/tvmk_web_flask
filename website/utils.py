import time
from functools import wraps
from typing import Any, Callable, TypeVar, cast

from firebase_admin import firestore
from flask import current_app
from flask_mail import Mail, Message


# Cache dùng chung trong tiến trình Flask hiện tại
_universal_cache: dict = {}

F = TypeVar("F", bound=Callable[..., Any])


def clear_universal_cache() -> None:
    """Xóa toàn bộ cache dùng chung."""
    _universal_cache.clear()


def send_mail_based_on_admin_config(subject, recipients, body) -> bool:
    """Gửi email bằng cấu hình SMTP trong system_configs/mail_settings."""
    try:
        db = firestore.client()

        # Firestore client ở đây là client đồng bộ.
        config_ref = cast(
            Any,
            db.collection("system_configs").document("mail_settings"),
        )
        config_doc = cast(Any, config_ref.get())

        if not config_doc.exists:
            print("Không tìm thấy system_configs/mail_settings.")
            return False

        config_data = config_doc.to_dict() or {}
        print("Các field cấu hình mail:", list(config_data.keys()))
        smtp_user = (config_data.get("smtp_email") or "").strip()
        smtp_pass = "".join(
            (config_data.get("smtp_password") or "").split()
        )

        if not smtp_user or not smtp_pass:
            print("Thiếu smtp_email hoặc smtp_password trong cấu hình.")
            return False

        current_app.config.update({
            "MAIL_SERVER": "smtp.gmail.com",
            "MAIL_PORT": 465,
            "MAIL_USE_SSL": True,
            "MAIL_USE_TLS": False,
            "MAIL_USERNAME": smtp_user,
            "MAIL_PASSWORD": smtp_pass,
            "MAIL_DEFAULT_SENDER": smtp_user,
            "MAIL_DEBUG": False,
        })

        mail = Mail(current_app)
        message = Message(
            subject=subject,
            recipients=recipients,
            body=body,
        )
        mail.send(message)

        print("Đã gửi email thông báo thành công!")
        return True

    except Exception as exc:
        print(f"Lỗi gửi email: {exc}")
        return False


def cache_result(ttl: int = 30):
    """
    Cache kết quả của function trong ttl giây.
    Mặc định dữ liệu cache tồn tại 30 giây.
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = (
                func.__module__,
                func.__qualname__,
                repr(args),
                repr(sorted(kwargs.items())),
            )
            current_time = time.time()

            cached_item = _universal_cache.get(cache_key)
            if cached_item is not None:
                data, cached_time = cached_item
                if current_time - cached_time < ttl:
                    print(
                        f"[CACHE HIT] Đang dùng cache cho hàm: "
                        f"{func.__name__}"
                    )
                    return data

            print(
                f"[CACHE MISS] Đang tải dữ liệu mới cho hàm: "
                f"{func.__name__}"
            )
            result = func(*args, **kwargs)
            _universal_cache[cache_key] = (result, current_time)
            return result

        return cast(F, wrapper)

    return decorator
