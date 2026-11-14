from firebase_admin import firestore


db = firestore.client()


class User:

  def __init__(self, user_id, data):
    self.id = user_id  
    self.email = data.get("email")
    self.password = data.get("password")
    self.user_name = data.get("user_name")
    self.full_name = data.get("full_name")
    self.role_id = data.get("role_id", 2)  
    self.allowed_off_days = data.get("allowed_off_days", 2)
    self.is_verified = data.get("is_verified", False)

  #  hỗ trợ Flask-Login tìm user theo ID
  @staticmethod
  def get(user_id):
    doc_ref = db.collection("users").document(user_id).get()
    if doc_ref.exists:
      return User(doc_ref.id, doc_ref.to_dict())
    return None

  # Htìm user theo email (dùng khi đăng nhập)
  @staticmethod
  def get_by_email(email):
    users_ref = (
        db.collection("users").where("email", "==", email).limit(1).stream()
    )
    for doc in users_ref:
      return User(doc.id, doc.to_dict())
    return None

  # Flask-Login để quản lý session (chưa làm)
  @property
  def is_authenticated(self):
    return True

  @property
  def is_active(self):
    return self.is_verified

  @property
  def is_anonymous(self):
    return False

  def get_id(self):
    return str(self.id)


class Status:

  def __init__(self, status_id, data):
    self.id = status_id
    self.name = data.get("name")

  @staticmethod
  def get_all():
    statuses = []
    docs = db.collection("statuses").stream()
    for doc in docs:
      statuses.append(Status(doc.id, doc.to_dict()))
    return statuses


class Registration:

  def __init__(self, reg_id, data):
    self.id = reg_id
    self.selected_days = data.get("selected_days")
    self.session = data.get("session")
    self.week_number = data.get("week_number")
    self.status_id = data.get("status_id")
    self.user_id = data.get("user_id")
    self.created_at = data.get("created_at")


class SystemConfig:

  def __init__(self, config_id, data):
    self.id = config_id
    self.smtp_email = data.get("smtp_email")
    self.smtp_password = data.get("smtp_password")


class Notification:

  def __init__(self, notif_id, data):
    self.id = notif_id
    self.user_id = data.get('user_id')
    self.message = data.get('message')
    self.is_read = data.get('is_read', False)
    self.created_at = data.get('created_at')