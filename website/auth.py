from flask import Blueprint, render_template, request, flash, redirect, url_for
#from .models import User
from werkzeug.security import generate_password_hash, check_password_hash
from . import db
from flask_login import login_user, login_required, logout_user, current_user

auth = Blueprint('auth', __name__)

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        from .models import User
        from website import db
        username = request.form.get('username')
        password = request.form.get('password')
    
        user = User.query.filter_by(user_name=username).first()
        if user:
            if check_password_hash(user.password, password):
                login_user(user, remember=True)
                flash('Logged in successfully!', category='success')
                # Go to Home page after login
                if user.role_id == 1 or user.role_id == 3:
                    return redirect(url_for('admin_views.admin_scheduleList'))
                elif user.role_id == 2:
                    return redirect(url_for('client_views.home'))
            else:
                flash('Incorrect password, try again.', category='error')
        else:
            flash('User not found.', category='error')
    # Render the login page template and pass the current user to it
    return render_template('login.html',user=current_user)

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
    # return render_template('logout.html',boolean = True)

@auth.route('/sign-up',methods=['GET', 'POST'])
def sign_up():
    if request.method == 'POST':
        from .models import User
        from website import db
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        user = User.query.filter_by(user_name=username).first()
        if user:
            flash('Username already exists.', category='error')
        elif len(email) < 4:
            flash('Email must be greater than 3 characters.', category='error')
        elif len(username) < 2:
            flash('Username must be greater than 1 character.', category='error')
        elif password != confirm_password:
            flash('Passwords don\'t match.', category='error')
        elif len(password) < 7:
            flash('Password must be at least 7 characters.', category='error')
        else:
            hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
            new_user = User(email=email, user_name=username, password=hashed_password,role_id=2)  # Mặc định role_id=2 cho Client   
            db.session.add(new_user)
            db.session.commit()
            flash('Account created!', category='success')
            login_user(new_user, remember=True)
            # Go to Home page after sign up
            return redirect(url_for('client_views.home'))
    
    return render_template('sign_up.html', user=current_user)