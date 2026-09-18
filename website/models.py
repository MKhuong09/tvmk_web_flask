from datetime import datetime
from flask_login import UserMixin
from sqlalchemy.sql import func
from enum import Enum
from . import db  # Hoặc cách import db tương ứng của dự án

class DayOfWeek(Enum):
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7
    
class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    users = db.relationship('User', backref='role', lazy=True)
    
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True)
    password = db.Column(db.String(150))
    user_name = db.Column(db.String(150), unique=True)
    fullname = db.Column(db.String(150))
    notes = db.relationship('Note')
    registrations = db.relationship('Registration', backref='user_account', lazy=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), nullable=False, default=2)
    allowed_off_days = db.Column(db.Integer, default=2)
    unavailable_days = db.Column(db.JSON, default=[])
    max_days_per_week = db.Column(db.Integer, default=3)

    # def to_dict(self):
    #     return {
    #         "id": self.id,
    #         "user_name": self.user_name,
    #         "fullname": self.fullname,
    #         "email": self.email,
    #         "role_id": self.role_id,
    #         "allowed_off_days": self.allowed_off_days,
    #         "unavailable_days": self.unavailable_days or [],
    #         "max_days_per_week": self.max_days_per_week
    #     }

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.String(10000))
    date = db.Column(db.DateTime(timezone=True), default=func.now())
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class Registration(db.Model):
    __tablename__ = 'registration'
    id = db.Column(db.Integer, primary_key=True)
    selected_days = db.Column(db.String(200), nullable=False)
    session = db.Column(db.String(50), nullable=False)
    week_number = db.Column(db.Integer)   
    status_id = db.Column(db.Integer, db.ForeignKey('status.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=func.now())
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Status(db.Model):
    __tablename__ = 'status'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False) 
    registrations = db.relationship('Registration', backref='status_obj', lazy=True)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    
class ScheduleOutput(db.Model):
    date = db.Column(db.String(20), primary_key=True)
    userlist = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=func.now())
