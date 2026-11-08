from functools import wraps
from flask import session, flash, redirect, url_for
from sqlalchemy import text
from app.database import get_db

def current_user():
    uid = session.get('user_id')
    if not uid: return None
    row = get_db().execute(text("SELECT u.*, r.role_name FROM users u JOIN roles r ON r.role_id=u.role_id WHERE u.user_id=:id AND u.is_active=1"), {'id': uid}).mappings().first()
    return dict(row) if row else None

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash('Войдите в аккаунт, чтобы продолжить.', 'info')
            return redirect(url_for('auth.login', next=request_path()))
        return fn(*args, **kwargs)
    return wrapper

def employee_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            flash('Сначала войдите в аккаунт.', 'info'); return redirect(url_for('auth.login'))
        if user['role_name'] != 'employee':
            flash('Раздел доступен только сотрудникам магазина.', 'error'); return redirect(url_for('main.index'))
        return fn(*args, **kwargs)
    return wrapper

def request_path():
    from flask import request
    return request.full_path

def money(cents):
    return f"{(cents or 0)/100:,.2f} ₽".replace(',', ' ').replace('.', ',')
