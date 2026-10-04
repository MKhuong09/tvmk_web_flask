import re
import cv2
import numpy as np

def extract_emails_from_text(text: str) -> list:
    if not text:
        return []

    # Xóa khoảng trắng quanh dấu chấm và @
    text = re.sub(r"\s*([.@])\s*", r"\1", text)

    # bỏ dấu chấm trong các tên miền phổ biến
    text = re.sub(
    r"@(gmail|yahoo|outlook|hotmail)\s*\.?\s*com\b",
    r"@\1.com",
    text,
    flags=re.IGNORECASE,
)

    email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    emails = re.findall(email_pattern, text)

    print(f"[EMAIL DEBUG] Kết quả regex: {emails!r}")
    return list(set(email.lower() for email in emails))

def process_image_to_text(image_bytes: bytes) -> str:
    """
    Chuyển đổi dữ liệu ảnh (bytes) thành Văn bản thực tế
    """
    if not image_bytes:
        return ""
        
    try:
        # Import nội bộ ngay trong hàm để gọi từ events.py
        from ..events import process_ocr_from_bytes
        extracted_text = process_ocr_from_bytes(image_bytes)
        return extracted_text
    except Exception as e:
        print(f"❌ Lỗi xử lý ảnh: {e}")
        return ""