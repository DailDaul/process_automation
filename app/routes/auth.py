import re

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

from app.database import get_db

bp = Blueprint('auth', __name__)


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('username', '').strip()
        login = request.form.get('login', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip().lower() or None
        password = request.form.get('password', '')

        errors = []
        if not name or len(name) > 100:
            errors.append('Имя должно содержать от 1 до 100 символов.')
        if len(login) < 3 or len(login) > 50:
            errors.append('Логин должен содержать от 3 до 50 символов.')
        if len(phone) < 5 or len(phone) > 30:
            errors.append('Телефон должен содержать от 5 до 30 символов.')
        if email and (len(email) > 254 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)):
            errors.append('Укажите корректный адрес электронной почты.')
        if len(password) < 8:
            errors.append('Пароль должен содержать не менее 8 символов.')

        if errors:
            for error in errors:
                flash(error, 'error')
        else:
            try:
                with get_db() as db:
                    with db.begin():
                        db.execute(text(
                            "INSERT INTO users(role_id, username, login, phone, email, password_hash) "
                            "VALUES(1, :n, :l, :p, :e, :h)"
                        ), {
                            'n': name,
                            'l': login,
                            'p': phone,
                            'e': email,
                            'h': generate_password_hash(password)
                        })

                        uid = db.execute(
                            text('SELECT last_insert_rowid()')
                        ).scalar_one()

                        db.execute(
                            text('INSERT INTO wishlists(user_id) VALUES(:u)'),
                            {'u': uid}
                        )
                session.clear()
                session['user_id'] = uid
                flash('Аккаунт создан. Добро пожаловать в MashUp!', 'success')
                return redirect(url_for('main.index'))
            except Exception as exc:
                import traceback
                traceback.print_exc()

                # Не раскрываем пользователю SQL-текст, но разделяем типичную
                # ситуацию конфликта уникальности и прочие ошибки БД.
                message = str(exc).lower()
                if 'unique constraint' in message:
                    flash('Такой логин, телефон или адрес электронной почты уже зарегистрирован.', 'error')
                else:
                    flash('Не удалось создать аккаунт. Проверьте данные и повторите попытку.', 'error')

    return render_template('auth/register.html')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identity = request.form.get('identity', '').strip()
        password = request.form.get('password', '')
        row = get_db().execute(text(
            "SELECT * FROM users WHERE (login=:v COLLATE NOCASE OR phone=:v OR email=:v COLLATE NOCASE) "
            "AND is_active=1"
        ), {'v': identity}).mappings().first()
        if row and check_password_hash(row['password_hash'], password):
            session.clear()
            session['user_id'] = row['user_id']
            flash('Вы вошли в аккаунт.', 'success')
            return redirect(url_for('main.index'))
        flash('Не удалось войти: проверьте логин и пароль.', 'error')
    return render_template('auth/login.html')


@bp.post('/logout')
def logout():
    session.clear()
    flash('Вы вышли из аккаунта.', 'info')
    return redirect(url_for('main.index'))
