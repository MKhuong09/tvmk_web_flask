from flask import Blueprint, render_template
from flask_login import login_required, current_user

views = Blueprint('views', __name__)

@views.route('/')
#@login_required
def home():
    return render_template('home.html', user=current_user)


from flask import Blueprint, render_template
from .models import User, Registration  # Import các Model cần dùng
from . import db

# Giả sử blueprint của em tên là views
