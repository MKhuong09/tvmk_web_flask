from flask import current_app
from flask_mail import Mail, Message
from firebase_admin import firestore

from .models import SystemConfig

def send_mail_based_on_admin_config(subject, recipients, body):
    db = firestore.client()
    
    configs_ref = db.collection('system_configs').limit(1).stream()
    config = None
    for doc in configs_ref:
        config_data = doc.to_dict()
        class ConfigObj:
            def __init__(self, data):
                self.smtp_email = data.get('smtp_email')
                self.smtp_password = data.get('smtp_password')
        config = ConfigObj(config_data)
        break

    if not config or not config.smtp_email or not config.smtp_password:       
        smtp_user = "danquanhocmon@gmail.com"
        smtp_pass = "jqhk xscf ovll fvin"  
    else:
        smtp_user = config.smtp_email
        smtp_pass = config.smtp_password
    current_app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    current_app.config['MAIL_PORT'] = 465
    current_app.config['MAIL_USE_SSL'] = True
    current_app.config['MAIL_USERNAME'] = smtp_user
    current_app.config['MAIL_PASSWORD'] = smtp_pass
    current_app.config['MAIL_DEFAULT_SENDER'] = smtp_user

    dynamic_mail = Mail(current_app)

    try:
        msg = Message(subject=subject, recipients=recipients, body=body)
        dynamic_mail.send(msg)
        print("Đã gửi email thông báo thành công!")
        return True
    except Exception as e:
        print(f"Lỗi gửi email: {e}")
        return False