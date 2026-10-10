from firebase_admin import firestore
from enum import Enum
from datetime import datetime, timezone
from algorithms.schedule_agent import ScheduleAgent
from .utils import get_year_week_num, get_next_year_week_num

db = firestore.client()

class DayOfWeek(Enum):
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7

DAY_MAPPING = {
    1: "monday",
    2: "tuesday",
    3: "wednesday",
    4: "thursday",
    5: "friday",
    6: "saturday",
    7: "sunday"
}

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
    
  def to_dict(self):
    """Converts instance back into a dictionary for API JSON responses or saving to Firestore."""
    return {
        "id": self.id,
        "email": self.email,
        "user_name": self.user_name,
        "full_name": self.full_name,
        "role_id": self.role_id,
        "allowed_off_days": self.allowed_off_days,
        "is_verified": self.is_verified,
    }

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
  
  @staticmethod
  def count():
      """Returns the total number of users in Firestore."""
      results = db.collection("users").count().get()
      return results[0][0].value

  @staticmethod
  def get_all():
      """Fetches all users from Firestore and returns a list of User objects."""
      docs = db.collection("users").stream()
      return [User(doc.id, doc.to_dict()) for doc in docs]

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
    self.selected_days = data.get("selected_days", [])
    self.session = data.get("session")
    self.week_number = data.get("week_number")
    self.status_id = data.get("status_id")
    self.user_id = data.get("user_id")
    self.created_at = data.get("created_at")

  def to_dict(self):
    """Helper method to convert instance back to dict for Firestore or JSON responses."""
    return {
        "id": self.id,
        "selected_days": self.selected_days,
        "session": self.session,
        "week_number": self.week_number,
        "status_id": self.status_id,
        "user_id": self.user_id,
        "created_at": self.created_at
    }

  @classmethod
  def get_all(cls):
    """Fetches all registrations and returns a list of Registration objects."""
    docs = db.collection("registrations").stream()
    return [cls(doc.id, doc.to_dict()) for doc in docs]
  
  @classmethod
  def get_latest(cls, user_id):
    """Fetches all registrations and returns a list of Registration objects."""
    docs = (
        db.collection("registrations")
        .where("user_id", "==", user_id)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(1)
        .stream()
    )
    for doc in docs:
      data = doc.to_dict() or {}
      return cls(doc.id, data)
        
    return None

  # @classmethod
  # def get_current_week(cls):
  #   """Fetches the most recent registration object for the current week."""
  #   current_week = get_year_week_num()
    
  #   docs = (
  #       db.collection("registrations")
  #       .where("week_number", "==", current_week)
  #       .order_by("created_at", direction=firestore.Query.DESCENDING)
  #       .limit(1)
  #       .stream()
  #   )
    
  #   for doc in docs:
  #     data = doc.to_dict() or {}
  #     return cls(doc.id, data)
        
  #   return None
  
  @classmethod
  def get_current_week(cls):
    """Lấy danh sách tất cả các bản ghi đăng ký trong tuần hiện tại."""
    year, week = get_year_week_num() # Hàm helper lấy số tuần hiện tại
    
    docs = (
        db.collection("registrations")
        .where("week", "==", week)
        .stream()
    )
    
    # Trả về list các Dictionary thay vì Custom Object
    return [cls(doc.id, doc.to_dict() or {}).to_dict() for doc in docs]
  
  @classmethod
  def get_year_week(cls, year, week):
    """Lấy danh sách tất cả các bản ghi đăng ký trong tuần hiện tại."""
    
    docs = (
        db.collection("registrations")
        .where("year", "==", year)
        .where("week", "==", week)
        .stream()
    )
    
    # Trả về list các Dictionary thay vì Custom Object
    return [cls(doc.id, doc.to_dict() or {}).to_dict() for doc in docs]

class Schedule:
  DAYS_OF_WEEK = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

  def __init__(self, doc_id, data):
      self.id = doc_id
      self.week = data.get("week")
      self.year = data.get("year")
      self.status = data.get("status", "draft")
      self.created_at = data.get("created_at")
      raw_daily_schedule = data.get("daily_schedule", {})
      self.daily_schedule = {}

      for day in self.DAYS_OF_WEEK:
          raw_users = raw_daily_schedule.get(day, [])
          self.daily_schedule[day] = [
              User(u.get("id"), u) if isinstance(u, dict) else u 
              for u in raw_users
          ]

  def to_dict(self):
      """Converts instance to a dictionary for API response or writing back to Firestore."""
      # Serialize User instances back to dictionaries per day
      serialized_daily_schedule = {}
      for day in self.DAYS_OF_WEEK:
          serialized_daily_schedule[day] = [
              user.to_dict() if isinstance(user, User) else user 
              for user in self.daily_schedule.get(day, [])
          ]

      return {
          "id": self.id,
          "week": self.week,
          "year": self.year,
          "status": self.status,
          "created_at": self.created_at,
          "daily_schedule": serialized_daily_schedule
      }

  @staticmethod
  def create(is_next_week):
    """
    Creates a new schedule document in Firestore. 
    If daily_schedule is None, it triggers ScheduleAgent to compute it automatically.
    """
    # 1. Check if a schedule already exists for this week before running solver or saving
    year, week = get_next_year_week_num() if is_next_week else get_year_week_num()

    if Schedule.is_existed(year, week):
      print(f"Schedule for week {week} and year {year} already exists. Skipping creation.")
      return None

    # 2. If daily_schedule was not passed, generate it using ScheduleAgent
    all_users = User.get_all()  # Fetch users automatically if not provided
    registrations = Registration.get_current_week()
    
    agent = ScheduleAgent(all_users, registrations, NumOfSchedDays=7, NumOfUsersPerDay=3)
    daily_schedule = agent.generate_schedule()  # Calls solver method below

    if not daily_schedule:
      print("Solver could not find a feasible schedule.")
      return None

    # 3. Serialize User objects to dicts for each day
    serialized_daily_schedule = {}
    for day in Schedule.DAYS_OF_WEEK:
        day_users = daily_schedule.get(day, [])
        serialized_daily_schedule[day] = [
            user.id if isinstance(user, User) else user
            for user in day_users
        ]

    # 4. Save to Firestore
    doc_ref = db.collection("schedules").document()
    schedule_data = {
      "year": year,
      "week": week,
      "status": "Published",
      "created_at": datetime.now(timezone.utc),
      "daily_schedule": serialized_daily_schedule
    }

    doc_ref.set(schedule_data)
    return Schedule(doc_ref.id, schedule_data)
  
  @staticmethod
  def is_existed(year, week):
    """Checks if a schedule already exists for the given week."""
    docs = (
      db.collection("schedules")
      .where("week", "==", week)
      .where("year", "==", year)
      .limit(1)
      .stream()
    )
    return any(docs)

  @staticmethod
  def get_latest():
    """Fetches the most recently created schedule."""
    docs = (
      db.collection("schedules")
      .order_by("created_at", direction=firestore.Query.DESCENDING)
      .limit(1)
      .stream()
    )
    for doc in docs:
      return Schedule(doc.id, doc.to_dict())
    return None

  @staticmethod
  def get_schedule(year, week):
    """Fetches the most recently created schedule."""
    docs = (
      db.collection("schedules")
      .where("year", "==", year)
      .where("week", "==", week)
      .limit(1)
      .stream()
    )
    for doc in docs:
      return Schedule(doc.id, doc.to_dict())
    return None

  @staticmethod
  def get_by_id(schedule_id):
      """Fetches a specific schedule by document ID."""
      doc = db.collection("schedules").document(schedule_id).get()
      if doc.exists:
        return Schedule(doc.id, doc.to_dict())
      return None
  
  @staticmethod
  def parse_day(day_val):
    """Helper to standardize day input into mapped string keys (e.g., 1 -> 'monday')."""
    if isinstance(day_val, int) or (isinstance(day_val, str) and day_val.isdigit()):
      return DAY_MAPPING.get(int(day_val))
    return str(day_val).lower() if day_val else None

  @staticmethod
  def remove_user(user_id, day_of_week, week):
    """Removes a user_id from the specified day in the schedule for a given week."""
    schedule_doc = Schedule.get_week(week)
    if not schedule_doc:
      return False

    data = schedule_doc.to_dict() if hasattr(schedule_doc, 'to_dict') else (schedule_doc or {})
    schedule_daily = data.get('daily_schedule', {})
    day_key = Schedule.parse_day(day_of_week)

    # Filter out user_id from the targeted day array
    if day_key and day_key in schedule_daily and isinstance(schedule_daily[day_key], list):
      schedule_daily[day_key] = [
        uid for uid in schedule_daily[day_key] if str(uid) != str(user_id)
      ]

      doc_id = getattr(schedule_doc, 'id', None) or data.get('id')

      if doc_id:
        db.collection("schedules").document(doc_id).update({
            f"daily_schedule.{day_key}": schedule_daily[day_key]
        })
        return True

    return False

  @staticmethod
  def add_users(user_ids, day_of_week, week):
    """Adds a user_id to the specified day in the schedule for a given week."""
    schedule_doc = Schedule.get_week(week)
    if not schedule_doc:
      return False

    data = schedule_doc.to_dict() if hasattr(schedule_doc, 'to_dict') else (schedule_doc or {})
    schedule_daily = data.get('daily_schedule', {})
    day_key = Schedule.parse_day(day_of_week)

    if day_key and day_key in schedule_daily:
      if not isinstance(schedule_daily[day_key], list):
        schedule_daily[day_key] = []
        
      if not isinstance(user_ids, list):
        user_ids = [user_ids]

      # 1. Filter out duplicates and append all new user_ids

      newly_added = False

      for user_id in user_ids:
          if not any(str(uid) == str(user_id) for uid in schedule_daily[day_key]):
              schedule_daily[day_key].append(user_id)
              newly_added = True

      # 2. Update Firestore ONCE with the final array if any user was added
      if newly_added:
        doc_id = getattr(schedule_doc, 'id', None) or data.get('id')
        if doc_id:
          db.collection("schedules").document(doc_id).update({
              f"daily_schedule.{day_key}": schedule_daily[day_key]
          })
          return True
      return False
    return False
  
  @staticmethod
  def move_user(user_id, current_day_of_week, selected_day_of_week, week):
    # 1. Remove user from current day
    removed = Schedule.remove_user(user_id, current_day_of_week, week)
    
    # 2. Add user to new selected day
    added = Schedule.add_users(user_id, selected_day_of_week, week)
    
    return removed and added
    
  # @staticmethod
  # def move_user(user_id, current_day_of_week, selected_day_of_week, week_num):
  #   # 1. Fetch current schedule document for the week
  #   schedule_doc = Schedule.get_week(week_num)
  #   if not schedule_doc:
  #     return False

  #   schedule_data = schedule_doc.to_dict() if hasattr(schedule_doc, 'to_dict') else schedule_doc

  #   current_key = parse_day(current_day_of_week)
  #   selected_key = parse_day(selected_day_of_week)

  #   # 2. Remove user_id specifically from the current_day_of_week array
  #   if current_key and current_key in schedule_data and isinstance(schedule_data[current_key], list):
  #     schedule_data[current_key] = [
  #       uid for uid in schedule_data[current_key] if str(uid) != str(user_id)
  #     ]

  #   # 3. Add user_id to the selected_day_of_week array
  #   if selected_key and selected_key in schedule_data:
  #     if not isinstance(schedule_data[selected_key], list):
  #       schedule_data[selected_key] = []
      
  #     # Avoid duplicate if user_id is already in target array
  #     if not any(str(uid) == str(user_id) for uid in schedule_data[selected_key]):
  #       schedule_data[selected_key].append(user_id)

  #   # 4. Save updated data back to Firestore
  #   doc_id = getattr(schedule_doc, 'id', None) or schedule_data.get('id')
  #   if doc_id:
  #     db.collection("schedules").document(doc_id).update(schedule_data)
  #     return True

  #   return False

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