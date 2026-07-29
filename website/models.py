from . import db
from flask_login import UserMixin
from sqlalchemy.sql import func


class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    # Khai báo mối quan hệ ngược lại để dễ dàng truy vấn user.role.name
    users = db.relationship('User', backref='role', lazy=True)
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True)
    password = db.Column(db.String(150))
    user_name = db.Column(db.String(150), unique=True)
    notes = db.relationship('Note')
    registrations = db.relationship('Registration', backref='user_account', lazy=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), nullable=False,default=2)  # Mặc định role_id=2 cho Client

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.String(10000))
    date = db.Column(db.DateTime(timezone=True), default=func.now())
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
class Registration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    selected_days = db.Column(db.String(200), nullable=False) 
    session = db.Column(db.String(50), nullable=False)       
    week_number = db.Column(db.Integer)                      
    created_at = db.Column(db.DateTime(timezone=True), default=func.now()) 
    status = db.Column(db.String(20), default='Pending')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
