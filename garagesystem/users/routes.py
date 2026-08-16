from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from garagesystem import db, bcrypt
from garagesystem.models import User
from garagesystem.users.forms import LoginForm, RegisterForm, RequestResetForm, ResetPasswordForm
from garagesystem.users.utils import send_password_reset_email

users = Blueprint('users', __name__)


@users.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    # First-time setup: redirect to register if no users exist
    if User.query.count() == 0:
        flash('No account found. Please create one to get started.', 'info')
        return redirect(url_for('users.register'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and bcrypt.check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.home'))
        flash('Invalid username or password.', 'danger')

    return render_template('users/login.html', title='Login', form=form)


@users.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('users.login'))


@users.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    # Only allow registration when no users exist (first-time setup)
    if User.query.count() > 0:
        flash('Registration is not available.', 'danger')
        return redirect(url_for('users.login'))

    form = RegisterForm()
    if form.validate_on_submit():
        hashed_pw = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user = User(
            username=form.username.data,
            email=form.email.data,
            password=hashed_pw,
        )
        db.session.add(user)
        db.session.commit()
        flash('Account created. You can now log in.', 'success')
        return redirect(url_for('users.login'))

    return render_template('users/register.html', title='Create Account', form=form)


@users.route('/reset_password', methods=['GET', 'POST'])
def reset_request():
    form = RequestResetForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = user.get_reset_token()
            reset_url = url_for('users.reset_token', token=token, _external=True)
            send_password_reset_email(user, reset_url)
        # Same message whether or not the email exists, so we don't leak which emails are registered.
        flash('If an account exists for that email, a reset link has been sent.', 'info')
        return redirect(url_for('users.login'))

    return render_template('users/reset_request.html', title='Reset Password', form=form)


@users.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_token(token):
    user = User.verify_reset_token(token)
    if user is None:
        flash('That reset link is invalid or has expired.', 'warning')
        return redirect(url_for('users.reset_request'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        hashed_pw = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user.password = hashed_pw
        db.session.commit()
        # Drop the current session so the new password takes effect immediately
        # and any other active session (e.g. the one that made this reset feel necessary) is cleared.
        logout_user()
        flash('Your password has been updated. You can now log in.', 'success')
        return redirect(url_for('users.login'))

    return render_template('users/reset_password.html', title='Reset Password', form=form)
