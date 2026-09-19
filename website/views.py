from flask import Blueprint, redirect, url_for
views = Blueprint('views', __name__)

@views.route('/')
def home_redirect():

    return redirect(url_for('auth.login'))