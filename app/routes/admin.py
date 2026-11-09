from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy import text
from app.database import get_db, get_engine
from app.utils import employee_required
bp=Blueprint('admin',__name__)
@bp.get('/')
@employee_required
def dashboard():
    db=get_db()
    stats={'products':db.execute(text('SELECT COUNT(*) FROM products WHERE is_active=1')).scalar_one(),'orders':db.execute(text("SELECT COUNT(*) FROM orders WHERE status IN ('new','processing')")).scalar_one(),'stock':db.execute(text('SELECT COALESCE(SUM(stock),0) FROM v_product_stock')).scalar_one()}
    orders=db.execute(text("SELECT o.*,u.username,(SELECT COALESCE(SUM(quantity*unit_price),0) FROM order_items WHERE order_id=o.order_id) total FROM orders o LEFT JOIN users u ON u.user_id=o.user_id ORDER BY o.created_at DESC LIMIT 30")).mappings().all()
    return render_template('employee/dashboard.html',stats=stats,orders=orders)
@bp.route('/products/new', methods=['GET', 'POST'])
@employee_required
def product_new():
    db = get_db()
    if request.method == 'POST':
        db.rollback()  # освобождаем read-транзакцию SQLite перед отдельной write-транзакцией
        title = request.form.get('title', '').strip()
        catalog = request.form.get('catalog_number', '').strip()
        description = request.form.get('description', '').strip()
        release_date = request.form.get('release_date') or None
        try:
            media_id = int(request.form.get('media_type_id', ''))
            manufacturer_id = int(request.form.get('manufacturer_company_id', ''))
            price_text = request.form.get('price', '0').strip().replace(',', '.')
            price_decimal = Decimal(price_text)
            stock = int(request.form.get('stock', '0'))
            if not price_decimal.is_finite() or price_decimal < 0 or stock < 0:
                raise ValueError
            price = int((price_decimal * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            if not title or len(title) > 250 or not catalog or len(catalog) > 100:
                raise ValueError
            if release_date:
                date.fromisoformat(release_date)
        except (ValueError, InvalidOperation, ArithmeticError, TypeError):
            flash('Проверьте название, каталожный номер, формат, производителя, дату, цену и остаток.', 'error')
        else:
            try:
                with get_engine().begin() as conn:
                    valid_media = conn.execute(text('SELECT 1 FROM media_types WHERE media_type_id=:id'), {'id': media_id}).first()
                    valid_manufacturer = conn.execute(text('SELECT 1 FROM manufacturers WHERE company_id=:id'), {'id': manufacturer_id}).first()
                    if not valid_media or not valid_manufacturer:
                        raise ValueError('Выбранный формат или производитель не существует.')
                    conn.execute(text(
                        "INSERT INTO products(catalog_number,title,media_type_id,manufacturer_company_id,release_date,description) "
                        "VALUES(:c,:t,:m,:man,:d,:desc)"
                    ), {'c': catalog, 't': title, 'm': media_id, 'man': manufacturer_id,
                        'd': release_date, 'desc': description})
                    product_id = conn.execute(text('SELECT last_insert_rowid()')).scalar_one()
                    conn.execute(text(
                        "INSERT INTO product_prices(product_id,retail_price,valid_from) VALUES(:p,:price,date('now'))"
                    ), {'p': product_id, 'price': price})
                    if stock:
                        conn.execute(text(
                            "INSERT INTO inventory_movements(product_id,movement_type,quantity,comment) "
                            "VALUES(:p,'receipt',:q,'Первоначальное поступление')"
                        ), {'p': product_id, 'q': stock})
                flash('Товар добавлен в каталог.', 'success')
                return redirect(url_for('admin.products'))
            except ValueError as exc:
                flash(str(exc), 'error')
            except Exception:
                flash('Не удалось сохранить товар. Проверьте каталожный номер и введённые данные.', 'error')

    media = db.execute(text('SELECT * FROM media_types ORDER BY name')).mappings().all()
    companies = db.execute(text(
        'SELECT c.company_id,c.name FROM companies c JOIN manufacturers m ON m.company_id=c.company_id ORDER BY c.name'
    )).mappings().all()
    return render_template('employee/product_form.html', media_types=media, companies=companies)

@bp.get('/products')
@employee_required
def products():
    rows=get_db().execute(text("SELECT p.*,mt.name media_name,pp.retail_price,COALESCE(s.stock,0) stock FROM products p JOIN media_types mt ON mt.media_type_id=p.media_type_id LEFT JOIN product_prices pp ON pp.product_id=p.product_id AND pp.valid_to IS NULL LEFT JOIN v_product_stock s ON s.product_id=p.product_id ORDER BY p.title")).mappings().all()
    return render_template('employee/products.html',products=rows)

@bp.route('/products/<int:product_id>/edit',methods=['GET','POST'])
@employee_required
def product_edit(product_id):
    db=get_db()
    product=db.execute(text("SELECT p.*,pp.retail_price FROM products p LEFT JOIN product_prices pp ON pp.product_id=p.product_id AND pp.valid_to IS NULL WHERE p.product_id=:id"),{'id':product_id}).mappings().first()
    if not product:
        flash('Товар не найден.','error'); return redirect(url_for('admin.products'))
    if request.method == 'POST':
        db.rollback()  # закрываем read-транзакцию, в которой получили карточку товара
        title = request.form.get('title', '').strip()
        catalog = request.form.get('catalog_number', '').strip()
        description = request.form.get('description', '').strip()
        release = request.form.get('release_date') or None
        try:
            price_decimal = Decimal(request.form.get('price', '0').strip().replace(',', '.'))
            if (not title or len(title) > 250 or not catalog or len(catalog) > 100
                    or not price_decimal.is_finite() or price_decimal < 0):
                raise ValueError
            price = int((price_decimal * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            if release:
                date.fromisoformat(release)
            with get_engine().begin() as conn:
                conn.execute(text(
                    "UPDATE products SET title=:t,catalog_number=:c,description=:d,release_date=:r WHERE product_id=:id"
                ), {'t': title, 'c': catalog, 'd': description, 'r': release, 'id': product_id})
                old = conn.execute(text(
                    "SELECT price_id,valid_from FROM product_prices WHERE product_id=:id AND valid_to IS NULL"
                ), {'id': product_id}).mappings().first()
                current = conn.execute(text(
                    "SELECT retail_price FROM product_prices WHERE product_id=:id AND valid_to IS NULL"
                ), {'id': product_id}).scalar_one_or_none()
                if current is None or current != price:
                    today = conn.execute(text("SELECT date('now')")).scalar_one()
                    if old and old['valid_from'] < today:
                        conn.execute(text(
                            "UPDATE product_prices SET valid_to=date('now','-1 day') WHERE price_id=:pid"
                        ), {'pid': old['price_id']})
                        conn.execute(text(
                            "INSERT INTO product_prices(product_id,retail_price,valid_from) VALUES(:id,:price,date('now'))"
                        ), {'id': product_id, 'price': price})
                    elif old:
                        conn.execute(text(
                            "UPDATE product_prices SET retail_price=:price WHERE price_id=:pid"
                        ), {'price': price, 'pid': old['price_id']})
                    else:
                        conn.execute(text(
                            "INSERT INTO product_prices(product_id,retail_price,valid_from) VALUES(:id,:price,date('now'))"
                        ), {'id': product_id, 'price': price})
            flash('Изменения сохранены.', 'success')
            return redirect(url_for('admin.products'))
        except (ValueError, InvalidOperation, ArithmeticError):
            flash('Проверьте название, каталожный номер, дату и цену.', 'error')
        except Exception:
            flash('Не удалось сохранить изменения. Проверьте уникальность каталожного номера и период цены.', 'error')
    media=db.execute(text('SELECT * FROM media_types')).mappings().all()
    return render_template('employee/product_edit.html',product=product,media_types=media)

@bp.post('/orders/<int:order_id>/status')
@employee_required
def order_status(order_id):
    get_db().rollback()  # освобождаем read-транзакцию проверки роли перед записью
    new_status = request.form.get('status')
    if new_status not in ('processing', 'completed', 'cancelled'):
        flash('Недопустимый статус заказа.', 'error')
        return redirect(url_for('admin.dashboard'))

    try:
        with get_engine().begin() as conn:
            order = conn.execute(text('SELECT * FROM orders WHERE order_id=:id'), {'id': order_id}).mappings().first()
            if not order:
                raise ValueError('Заказ не найден.')
            old_status = order['status']
            if old_status == 'completed' and new_status != 'completed':
                raise ValueError('Завершённый заказ нельзя отменить сменой статуса. Для возврата нужна отдельная операция.')
            if old_status == 'cancelled' and new_status != 'cancelled':
                raise ValueError('Отменённый заказ нельзя повторно открыть. Создайте новый заказ.')
            if old_status == new_status:
                flash('Заказ уже имеет выбранный статус.', 'info')
                return redirect(url_for('admin.dashboard'))

            if new_status == 'completed':
                lines = conn.execute(text('SELECT * FROM order_items WHERE order_id=:id'), {'id': order_id}).mappings().all()
                if not lines:
                    raise ValueError('Нельзя завершить заказ без товарных позиций.')
                # Проверяем остатки с учётом резервов других активных заказов.
                for line in lines:
                    stock = conn.execute(text(
                        'SELECT COALESCE(stock,0) FROM v_product_stock WHERE product_id=:p'
                    ), {'p': line['product_id']}).scalar_one()
                    other_reserved = conn.execute(text(
                        "SELECT COALESCE(SUM(oi.quantity),0) FROM order_items oi "
                        "JOIN orders o ON o.order_id=oi.order_id "
                        "WHERE oi.product_id=:p AND o.status IN ('new','processing') AND o.order_id<>:o"
                    ), {'p': line['product_id'], 'o': order_id}).scalar_one()
                    if stock - other_reserved < line['quantity']:
                        raise ValueError(f"Недостаточно свободного остатка для завершения заказа №{order_id}.")

                conn.execute(text(
                    "UPDATE orders SET status='completed',completed_at=CURRENT_TIMESTAMP WHERE order_id=:id"
                ), {'id': order_id})
                for line in lines:
                    conn.execute(text(
                        "INSERT INTO inventory_movements(product_id,movement_type,quantity,order_item_id,comment) "
                        "VALUES(:p,'sale',:q,:oi,'Продажа по заказу')"
                    ), {'p': line['product_id'], 'q': line['quantity'], 'oi': line['order_item_id']})
            else:
                conn.execute(text('UPDATE orders SET status=:s WHERE order_id=:id'),
                             {'s': new_status, 'id': order_id})
        flash('Статус заказа обновлён.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    except Exception:
        flash('Не удалось изменить статус заказа. Проверьте остатки и данные заказа.', 'error')
    return redirect(url_for('admin.dashboard'))

@bp.get('/statistics')
@employee_required
def statistics():
    rows=get_db().execute(text('SELECT * FROM v_product_sales_by_year ORDER BY sales_year DESC, quantity_sold DESC LIMIT 50')).mappings().all()
    leaders=get_db().execute(text("SELECT product_title,quantity_sold FROM v_product_sales_by_year WHERE sales_year=CAST(strftime('%Y','now') AS INTEGER) ORDER BY quantity_sold DESC LIMIT 10")).mappings().all()
    stock=get_db().execute(text('SELECT p.title,p.catalog_number,stock FROM v_product_stock s JOIN products p ON p.product_id=s.product_id ORDER BY stock,p.title')).mappings().all()
    return render_template('employee/statistics.html',sales=rows,stock=stock,leaders=leaders)


# Управление музыкальными ансамблями. Эти маршруты используют существующие
# таблицы ensembles, performances и compositions; миграция БД не требуется.
@bp.get('/ensembles')
@employee_required
def ensembles():
    rows = get_db().execute(text(
        "SELECT e.ensemble_id, e.name, e.ensemble_type, e.founded_year, "
        "e.disbanded_year, COUNT(DISTINCT p.composition_id) AS works_count, "
        "COUNT(DISTINCT p.performance_id) AS performances_count "
        "FROM ensembles e "
        "LEFT JOIN performances p ON p.ensemble_id=e.ensemble_id "
        "GROUP BY e.ensemble_id "
        "ORDER BY e.name"
    )).mappings().all()
    return render_template('employee/ensembles.html', ensembles=rows)


@bp.route('/ensembles/new', methods=['GET', 'POST'])
@employee_required
def ensemble_new():
    if request.method == 'POST':
        get_db().rollback()
        name = request.form.get('name', '').strip()
        ensemble_type = request.form.get('ensemble_type', '').strip()
        description = request.form.get('description', '').strip()
        founded_text = request.form.get('founded_year', '').strip()
        disbanded_text = request.form.get('disbanded_year', '').strip()
        try:
            founded = int(founded_text) if founded_text else None
            disbanded = int(disbanded_text) if disbanded_text else None
            if not name or len(name) > 200 or not ensemble_type or len(ensemble_type) > 100:
                raise ValueError
            if founded is not None and not 1000 <= founded <= 2100:
                raise ValueError
            if disbanded is not None and not 1000 <= disbanded <= 2100:
                raise ValueError
            if founded is not None and disbanded is not None and disbanded < founded:
                raise ValueError
            with get_engine().begin() as conn:
                conn.execute(text(
                    "INSERT INTO ensembles(name, ensemble_type, founded_year, disbanded_year, description) "
                    "VALUES(:name, :kind, :founded, :disbanded, :description)"
                ), {'name': name, 'kind': ensemble_type, 'founded': founded,
                    'disbanded': disbanded, 'description': description})
            flash('Ансамбль добавлен.', 'success')
            return redirect(url_for('admin.ensembles'))
        except (ValueError, TypeError):
            flash('Проверьте название, тип ансамбля и годы его существования.', 'error')
        except Exception:
            flash('Не удалось добавить ансамбль. Проверьте введённые данные.', 'error')
    return render_template('employee/ensemble_form.html', ensemble=None)


@bp.route('/ensembles/<int:ensemble_id>/edit', methods=['GET', 'POST'])
@employee_required
def ensemble_edit(ensemble_id):
    db = get_db()
    ensemble = db.execute(text(
        'SELECT * FROM ensembles WHERE ensemble_id=:id'
    ), {'id': ensemble_id}).mappings().first()
    if not ensemble:
        flash('Ансамбль не найден.', 'error')
        return redirect(url_for('admin.ensembles'))

    if request.method == 'POST':
        db.rollback()
        name = request.form.get('name', '').strip()
        ensemble_type = request.form.get('ensemble_type', '').strip()
        description = request.form.get('description', '').strip()
        founded_text = request.form.get('founded_year', '').strip()
        disbanded_text = request.form.get('disbanded_year', '').strip()
        try:
            founded = int(founded_text) if founded_text else None
            disbanded = int(disbanded_text) if disbanded_text else None
            if not name or len(name) > 200 or not ensemble_type or len(ensemble_type) > 100:
                raise ValueError
            if founded is not None and not 1000 <= founded <= 2100:
                raise ValueError
            if disbanded is not None and not 1000 <= disbanded <= 2100:
                raise ValueError
            if founded is not None and disbanded is not None and disbanded < founded:
                raise ValueError
            with get_engine().begin() as conn:
                conn.execute(text(
                    "UPDATE ensembles SET name=:name, ensemble_type=:kind, founded_year=:founded, "
                    "disbanded_year=:disbanded, description=:description WHERE ensemble_id=:id"
                ), {'name': name, 'kind': ensemble_type, 'founded': founded,
                    'disbanded': disbanded, 'description': description, 'id': ensemble_id})
            flash('Данные ансамбля обновлены.', 'success')
            return redirect(url_for('admin.ensemble_detail', ensemble_id=ensemble_id))
        except (ValueError, TypeError):
            flash('Проверьте название, тип ансамбля и годы его существования.', 'error')
        except Exception:
            flash('Не удалось сохранить изменения ансамбля.', 'error')

    return render_template('employee/ensemble_form.html', ensemble=ensemble)


@bp.post('/ensembles/<int:ensemble_id>/delete')
@employee_required
def ensemble_delete(ensemble_id):
    # Не удаляем ансамбль, если на него ссылаются исполнения или составы.
    get_db().rollback()
    try:
        with get_engine().begin() as conn:
            ensemble = conn.execute(text(
                'SELECT name FROM ensembles WHERE ensemble_id=:id'
            ), {'id': ensemble_id}).mappings().first()
            if not ensemble:
                flash('Ансамбль уже отсутствует в базе данных.', 'info')
                return redirect(url_for('admin.ensembles'))
            performance_count = conn.execute(text(
                'SELECT COUNT(*) FROM performances WHERE ensemble_id=:id'
            ), {'id': ensemble_id}).scalar_one()
            member_count = conn.execute(text(
                'SELECT COUNT(*) FROM ensemble_members WHERE ensemble_id=:id'
            ), {'id': ensemble_id}).scalar_one()
            if performance_count or member_count:
                raise ValueError(
                    f"Нельзя удалить ансамбль «{ensemble['name']}»: с ним связано "
                    f"исполнений — {performance_count}, записей об участниках — {member_count}. "
                    'Сначала необходимо корректно переназначить или удалить связанные записи.'
                )
            conn.execute(text(
                'DELETE FROM ensembles WHERE ensemble_id=:id'
            ), {'id': ensemble_id})
        flash('Ансамбль удалён.', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    except Exception:
        flash('Не удалось удалить ансамбль. Возможно, с ним связаны другие записи.', 'error')
    return redirect(url_for('admin.ensembles'))


@bp.get('/ensembles/<int:ensemble_id>')
@employee_required
def ensemble_detail(ensemble_id):
    db = get_db()
    ensemble = db.execute(text(
        'SELECT * FROM ensembles WHERE ensemble_id=:id'
    ), {'id': ensemble_id}).mappings().first()
    if not ensemble:
        flash('Ансамбль не найден.', 'error')
        return redirect(url_for('admin.ensembles'))
    works = db.execute(text(
        "SELECT c.composition_id, c.title, c.creation_year, COUNT(DISTINCT p.performance_id) AS performances_count "
        "FROM compositions c JOIN performances p ON p.composition_id=c.composition_id "
        "WHERE p.ensemble_id=:id GROUP BY c.composition_id ORDER BY c.title"
    ), {'id': ensemble_id}).mappings().all()
    performances = db.execute(text(
        "SELECT p.performance_id, c.title AS composition_title, p.recorded_at, "
        "p.recording_location, m.full_name AS conductor_name "
        "FROM performances p JOIN compositions c ON c.composition_id=p.composition_id "
        "LEFT JOIN musicians m ON m.musician_id=p.conductor_id "
        "WHERE p.ensemble_id=:id ORDER BY p.recorded_at DESC, p.performance_id DESC"
    ), {'id': ensemble_id}).mappings().all()
    return render_template('employee/ensemble_detail.html', ensemble=ensemble, works=works,
                           performances=performances)


# Управление музыкальными произведениями.
@bp.get('/compositions')
@employee_required
def compositions():
    rows = get_db().execute(text(
        "SELECT c.composition_id, c.title, c.creation_year, "
        "COUNT(DISTINCT p.performance_id) AS performances_count "
        "FROM compositions c LEFT JOIN performances p ON p.composition_id=c.composition_id "
        "GROUP BY c.composition_id ORDER BY c.title"
    )).mappings().all()
    return render_template('employee/compositions.html', compositions=rows)


@bp.route('/compositions/new', methods=['GET', 'POST'])
@employee_required
def composition_new():
    if request.method == 'POST':
        get_db().rollback()
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        year_text = request.form.get('creation_year', '').strip()
        try:
            year = int(year_text) if year_text else None
            if not title or len(title) > 250 or (year is not None and not 1000 <= year <= 2100):
                raise ValueError
            with get_engine().begin() as conn:
                conn.execute(text(
                    'INSERT INTO compositions(title, creation_year, description) '
                    'VALUES(:title, :year, :description)'
                ), {'title': title, 'year': year, 'description': description})
            flash('Музыкальное произведение добавлено.', 'success')
            return redirect(url_for('admin.compositions'))
        except (ValueError, TypeError):
            flash('Проверьте название и год создания произведения.', 'error')
        except Exception:
            flash('Не удалось добавить произведение.', 'error')
    return render_template('employee/composition_form.html', composition=None)


@bp.route('/compositions/<int:composition_id>/edit', methods=['GET', 'POST'])
@employee_required
def composition_edit(composition_id):
    db = get_db()
    composition = db.execute(text(
        'SELECT * FROM compositions WHERE composition_id=:id'
    ), {'id': composition_id}).mappings().first()
    if not composition:
        flash('Произведение не найдено.', 'error')
        return redirect(url_for('admin.compositions'))
    if request.method == 'POST':
        db.rollback()
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        year_text = request.form.get('creation_year', '').strip()
        try:
            year = int(year_text) if year_text else None
            if not title or len(title) > 250 or (year is not None and not 1000 <= year <= 2100):
                raise ValueError
            with get_engine().begin() as conn:
                conn.execute(text(
                    'UPDATE compositions SET title=:title, creation_year=:year, description=:description '
                    'WHERE composition_id=:id'
                ), {'title': title, 'year': year, 'description': description, 'id': composition_id})
            flash('Данные произведения обновлены.', 'success')
            return redirect(url_for('admin.compositions'))
        except (ValueError, TypeError):
            flash('Проверьте название и год создания произведения.', 'error')
        except Exception:
            flash('Не удалось сохранить произведение.', 'error')
    return render_template('employee/composition_form.html', composition=composition)


# Управление конкретными исполнениями произведений.
@bp.get('/performances')
@employee_required
def performances():
    rows = get_db().execute(text(
        "SELECT p.performance_id, c.title AS composition_title, e.name AS ensemble_name, "
        "p.recorded_at, p.recording_location, m.full_name AS conductor_name "
        "FROM performances p JOIN compositions c ON c.composition_id=p.composition_id "
        "LEFT JOIN ensembles e ON e.ensemble_id=p.ensemble_id "
        "LEFT JOIN musicians m ON m.musician_id=p.conductor_id "
        "ORDER BY p.recorded_at DESC, p.performance_id DESC"
    )).mappings().all()
    return render_template('employee/performances.html', performances=rows)


def _performance_form_data(db):
    compositions_rows = db.execute(text(
        'SELECT composition_id, title FROM compositions ORDER BY title'
    )).mappings().all()
    ensembles_rows = db.execute(text(
        'SELECT ensemble_id, name FROM ensembles ORDER BY name'
    )).mappings().all()
    musicians_rows = db.execute(text(
        'SELECT musician_id, full_name FROM musicians ORDER BY full_name'
    )).mappings().all()
    return compositions_rows, ensembles_rows, musicians_rows


def _save_performance(performance_id=None):
    composition_text = request.form.get('composition_id', '').strip()
    ensemble_text = request.form.get('ensemble_id', '').strip()
    conductor_text = request.form.get('conductor_id', '').strip()
    recorded_at = request.form.get('recorded_at', '').strip() or None
    location = request.form.get('recording_location', '').strip() or None
    notes = request.form.get('notes', '').strip() or None
    try:
        composition_id = int(composition_text)
        ensemble_id = int(ensemble_text) if ensemble_text else None
        conductor_id = int(conductor_text) if conductor_text else None
        if recorded_at:
            date.fromisoformat(recorded_at)
        if location and len(location) > 200:
            raise ValueError
        with get_engine().begin() as conn:
            if not conn.execute(text('SELECT 1 FROM compositions WHERE composition_id=:id'),
                                {'id': composition_id}).first():
                raise ValueError('Выбранное произведение не найдено.')
            if ensemble_id is not None and not conn.execute(
                    text('SELECT 1 FROM ensembles WHERE ensemble_id=:id'), {'id': ensemble_id}).first():
                raise ValueError('Выбранный ансамбль не найден.')
            if conductor_id is not None and not conn.execute(
                    text('SELECT 1 FROM musicians WHERE musician_id=:id'), {'id': conductor_id}).first():
                raise ValueError('Выбранный дирижёр не найден.')
            params = {'composition_id': composition_id, 'ensemble_id': ensemble_id,
                      'conductor_id': conductor_id, 'recorded_at': recorded_at,
                      'location': location, 'notes': notes}
            if performance_id is None:
                conn.execute(text(
                    'INSERT INTO performances(composition_id, ensemble_id, conductor_id, recorded_at, '
                    'recording_location, notes) VALUES(:composition_id, :ensemble_id, :conductor_id, '
                    ':recorded_at, :location, :notes)'
                ), params)
            else:
                params['id'] = performance_id
                conn.execute(text(
                    'UPDATE performances SET composition_id=:composition_id, ensemble_id=:ensemble_id, '
                    'conductor_id=:conductor_id, recorded_at=:recorded_at, '
                    'recording_location=:location, notes=:notes WHERE performance_id=:id'
                ), params)
        return None
    except (ValueError, TypeError) as exc:
        return str(exc) or 'Проверьте выбранные значения и дату исполнения.'
    except Exception:
        return 'Не удалось сохранить исполнение. Проверьте введённые данные.'


@bp.route('/performances/new', methods=['GET', 'POST'])
@employee_required
def performance_new():
    db = get_db()
    if request.method == 'POST':
        db.rollback()
        error = _save_performance()
        if error:
            flash(error, 'error')
        else:
            flash('Исполнение добавлено.', 'success')
            return redirect(url_for('admin.performances'))
    compositions_rows, ensembles_rows, musicians_rows = _performance_form_data(db)
    return render_template('employee/performance_form.html', performance=None,
                           compositions=compositions_rows, ensembles=ensembles_rows,
                           musicians=musicians_rows, selected_ensemble=request.args.get('ensemble_id', ''))


@bp.route('/performances/<int:performance_id>/edit', methods=['GET', 'POST'])
@employee_required
def performance_edit(performance_id):
    db = get_db()
    performance = db.execute(text(
        'SELECT * FROM performances WHERE performance_id=:id'
    ), {'id': performance_id}).mappings().first()
    if not performance:
        flash('Исполнение не найдено.', 'error')
        return redirect(url_for('admin.performances'))
    if request.method == 'POST':
        db.rollback()
        error = _save_performance(performance_id)
        if error:
            flash(error, 'error')
        else:
            flash('Данные исполнения обновлены.', 'success')
            return redirect(url_for('admin.performances'))
    compositions_rows, ensembles_rows, musicians_rows = _performance_form_data(db)
    return render_template('employee/performance_form.html', performance=performance,
                           compositions=compositions_rows, ensembles=ensembles_rows,
                           musicians=musicians_rows, selected_ensemble='')


# Управление составом музыкального издания (трек-листом).
@bp.route('/products/<int:product_id>/tracks', methods=['GET', 'POST'])
@employee_required
def product_tracks(product_id):
    db = get_db()
    product = db.execute(text(
        "SELECT p.product_id, p.title, p.catalog_number, mt.name AS media_name "
        "FROM products p JOIN media_types mt ON mt.media_type_id=p.media_type_id "
        "WHERE p.product_id=:id"
    ), {'id': product_id}).mappings().first()
    if not product:
        flash('Издание не найдено.', 'error')
        return redirect(url_for('admin.products'))

    if request.method == 'POST':
        db.rollback()
        try:
            performance_id = int(request.form.get('performance_id', ''))
            disc_number = int(request.form.get('disc_number', '1'))
            track_number = int(request.form.get('track_number', ''))
            duration_text = request.form.get('duration_seconds', '').strip()
            duration_seconds = int(duration_text) if duration_text else None
            track_title = request.form.get('track_title', '').strip() or None

            if disc_number < 1 or track_number < 1:
                raise ValueError('Номер диска и номер дорожки должны быть положительными числами.')
            if duration_seconds is not None and duration_seconds < 1:
                raise ValueError('Продолжительность должна быть положительной.')
            if track_title and len(track_title) > 250:
                raise ValueError('Название дорожки не должно превышать 250 символов.')

            with get_engine().begin() as conn:
                performance = conn.execute(text(
                    "SELECT performance_id FROM performances WHERE performance_id=:id"
                ), {'id': performance_id}).first()
                if not performance:
                    raise ValueError('Выбранное исполнение не найдено.')
                conn.execute(text(
                    "INSERT INTO product_performances "
                    "(product_id, performance_id, disc_number, track_number, track_title, duration_seconds) "
                    "VALUES (:product_id, :performance_id, :disc_number, :track_number, :track_title, :duration)"
                ), {
                    'product_id': product_id, 'performance_id': performance_id,
                    'disc_number': disc_number, 'track_number': track_number,
                    'track_title': track_title, 'duration': duration_seconds
                })
            flash('Дорожка добавлена в состав издания.', 'success')
            return redirect(url_for('admin.product_tracks', product_id=product_id))
        except ValueError as exc:
            flash(str(exc), 'error')
        except Exception as exc:
            # В частности, UNIQUE(product_id, disc_number, track_number)
            # не позволяет занять один номер дорожки дважды на одном диске.
            if 'UNIQUE constraint failed' in str(exc):
                flash('На этом диске уже есть дорожка с таким номером.', 'error')
            else:
                flash('Не удалось добавить дорожку. Проверьте данные и повторите попытку.', 'error')

    tracks = db.execute(text(
        "SELECT x.product_performance_id, x.disc_number, x.track_number, x.track_title, "
        "x.duration_seconds, c.title AS composition_title, e.name AS ensemble_name, "
        "f.recorded_at, f.recording_location "
        "FROM product_performances x "
        "JOIN performances f ON f.performance_id=x.performance_id "
        "JOIN compositions c ON c.composition_id=f.composition_id "
        "LEFT JOIN ensembles e ON e.ensemble_id=f.ensemble_id "
        "WHERE x.product_id=:id ORDER BY x.disc_number, x.track_number"
    ), {'id': product_id}).mappings().all()

    performances = db.execute(text(
        "SELECT f.performance_id, c.title AS composition_title, e.name AS ensemble_name, "
        "f.recorded_at, f.recording_location "
        "FROM performances f JOIN compositions c ON c.composition_id=f.composition_id "
        "LEFT JOIN ensembles e ON e.ensemble_id=f.ensemble_id "
        "ORDER BY c.title, e.name, f.recorded_at DESC, f.performance_id DESC"
    )).mappings().all()
    return render_template('employee/product_tracks.html', product=product,
                           tracks=tracks, performances=performances)


@bp.post('/products/<int:product_id>/tracks/<int:track_id>/delete')
@employee_required
def product_track_delete(product_id, track_id):
    get_db().rollback()
    try:
        with get_engine().begin() as conn:
            result = conn.execute(text(
                "DELETE FROM product_performances "
                "WHERE product_performance_id=:track_id AND product_id=:product_id"
            ), {'track_id': track_id, 'product_id': product_id})
            if result.rowcount == 0:
                flash('Дорожка не найдена.', 'info')
            else:
                flash('Дорожка удалена из состава издания.', 'success')
    except Exception:
        flash('Не удалось удалить дорожку.', 'error')
    return redirect(url_for('admin.product_tracks', product_id=product_id))

# Управление поставщиками и закупочными ценами.
@bp.get('/suppliers')
@employee_required
def suppliers():
    rows = get_db().execute(text(
        "SELECT c.company_id, c.name, c.country, c.address, c.phone, c.website, "
        "(SELECT COUNT(*) FROM product_suppliers ps WHERE ps.supplier_company_id=c.company_id) "
        "AS products_count "
        "FROM suppliers s JOIN companies c ON c.company_id=s.company_id "
        "ORDER BY c.name"
    )).mappings().all()
    return render_template('employee/suppliers.html', suppliers=rows)


@bp.route('/suppliers/new', methods=['GET', 'POST'])
@employee_required
def supplier_new():
    if request.method == 'POST':
        get_db().rollback()
        name = request.form.get('name', '').strip()
        country = request.form.get('country', '').strip() or None
        address = request.form.get('address', '').strip() or None
        phone = request.form.get('phone', '').strip() or None
        website = request.form.get('website', '').strip() or None
        if not name or len(name) > 200 or (country and len(country) > 100) or \
                (phone and len(phone) > 30) or (website and len(website) > 255):
            flash('Проверьте название и длину контактных данных.', 'error')
        else:
            try:
                with get_engine().begin() as conn:
                    conn.execute(text(
                        "INSERT INTO companies(name,country,address,phone,website) "
                        "VALUES(:name,:country,:address,:phone,:website)"
                    ), {'name': name, 'country': country, 'address': address,
                        'phone': phone, 'website': website})
                    company_id = conn.execute(text('SELECT last_insert_rowid()')).scalar_one()
                    conn.execute(text('INSERT INTO suppliers(company_id) VALUES(:id)'), {'id': company_id})
                flash('Поставщик добавлен.', 'success')
                return redirect(url_for('admin.suppliers'))
            except Exception:
                flash('Не удалось добавить поставщика. Проверьте введённые данные.', 'error')
    return render_template('employee/supplier_form.html', supplier=None)


@bp.route('/suppliers/<int:supplier_id>/edit', methods=['GET', 'POST'])
@employee_required
def supplier_edit(supplier_id):
    db = get_db()
    supplier = db.execute(text(
        "SELECT c.* FROM companies c JOIN suppliers s ON s.company_id=c.company_id "
        "WHERE c.company_id=:id"
    ), {'id': supplier_id}).mappings().first()
    if not supplier:
        flash('Поставщик не найден.', 'error')
        return redirect(url_for('admin.suppliers'))
    if request.method == 'POST':
        db.rollback()
        name = request.form.get('name', '').strip()
        country = request.form.get('country', '').strip() or None
        address = request.form.get('address', '').strip() or None
        phone = request.form.get('phone', '').strip() or None
        website = request.form.get('website', '').strip() or None
        if not name or len(name) > 200 or (country and len(country) > 100) or \
                (phone and len(phone) > 30) or (website and len(website) > 255):
            flash('Проверьте название и длину контактных данных.', 'error')
        else:
            try:
                with get_engine().begin() as conn:
                    conn.execute(text(
                        "UPDATE companies SET name=:name,country=:country,address=:address,"
                        "phone=:phone,website=:website WHERE company_id=:id"
                    ), {'name': name, 'country': country, 'address': address,
                        'phone': phone, 'website': website, 'id': supplier_id})
                flash('Данные поставщика обновлены.', 'success')
                return redirect(url_for('admin.suppliers'))
            except Exception:
                flash('Не удалось обновить данные поставщика.', 'error')
    return render_template('employee/supplier_form.html', supplier=supplier)


@bp.post('/suppliers/<int:supplier_id>/delete')
@employee_required
def supplier_delete(supplier_id):
    get_db().rollback()
    try:
        with get_engine().begin() as conn:
            linked = conn.execute(text(
                'SELECT 1 FROM product_suppliers WHERE supplier_company_id=:id LIMIT 1'
            ), {'id': supplier_id}).first()
            if linked:
                flash('Поставщика нельзя удалить: он связан с товарами. Сначала проверьте его связи с изданиями.', 'error')
                return redirect(url_for('admin.suppliers'))
            conn.execute(text('DELETE FROM suppliers WHERE company_id=:id'), {'id': supplier_id})
            # Компания может одновременно быть производителем — в таком случае её запись сохраняется.
            manufacturer = conn.execute(text(
                'SELECT 1 FROM manufacturers WHERE company_id=:id'
            ), {'id': supplier_id}).first()
            if not manufacturer:
                conn.execute(text('DELETE FROM companies WHERE company_id=:id'), {'id': supplier_id})
        flash('Поставщик удалён.', 'success')
    except Exception:
        flash('Не удалось удалить поставщика.', 'error')
    return redirect(url_for('admin.suppliers'))


@bp.route('/products/<int:product_id>/suppliers', methods=['GET', 'POST'])
@employee_required
def product_suppliers(product_id):
    db = get_db()
    product = db.execute(text(
        "SELECT p.product_id,p.title,p.catalog_number,mt.name AS media_name "
        "FROM products p JOIN media_types mt ON mt.media_type_id=p.media_type_id "
        "WHERE p.product_id=:id"
    ), {'id': product_id}).mappings().first()
    if not product:
        flash('Товар не найден.', 'error')
        return redirect(url_for('admin.products'))

    if request.method == 'POST':
        db.rollback()
        action = request.form.get('action', 'add')
        try:
            supplier_id = int(request.form.get('supplier_company_id', ''))
            if action == 'add':
                catalog_number = request.form.get('supplier_catalog_number', '').strip() or None
                preferred = 1 if request.form.get('is_preferred') == '1' else 0
                price_text = request.form.get('wholesale_price', '').strip().replace(',', '.')
                if catalog_number and len(catalog_number) > 100:
                    raise ValueError('Каталожный номер поставщика не должен превышать 100 символов.')
                price = None
                if price_text:
                    amount = Decimal(price_text)
                    if not amount.is_finite() or amount < 0:
                        raise ValueError('Закупочная цена должна быть неотрицательным числом.')
                    price = int((amount * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                with get_engine().begin() as conn:
                    if not conn.execute(text(
                        'SELECT 1 FROM suppliers WHERE company_id=:id'
                    ), {'id': supplier_id}).first():
                        raise ValueError('Выбранный поставщик не найден.')
                    exists = conn.execute(text(
                        'SELECT 1 FROM product_suppliers WHERE product_id=:p AND supplier_company_id=:s'
                    ), {'p': product_id, 's': supplier_id}).first()
                    if exists:
                        raise ValueError('Этот поставщик уже связан с данным изданием.')
                    if preferred:
                        conn.execute(text(
                            'UPDATE product_suppliers SET is_preferred=0 WHERE product_id=:p'
                        ), {'p': product_id})
                    conn.execute(text(
                        'INSERT INTO product_suppliers(product_id,supplier_company_id,'
                        'supplier_catalog_number,is_preferred) VALUES(:p,:s,:c,:preferred)'
                    ), {'p': product_id, 's': supplier_id, 'c': catalog_number, 'preferred': preferred})
                    if price is not None:
                        conn.execute(text(
                            "INSERT INTO supplier_product_prices(product_id,supplier_company_id,"
                            "wholesale_price,valid_from) VALUES(:p,:s,:price,date('now'))"
                        ), {'p': product_id, 's': supplier_id, 'price': price})
                flash('Поставщик привязан к изданию.', 'success')
            elif action == 'price':
                price_text = request.form.get('wholesale_price', '').strip().replace(',', '.')
                amount = Decimal(price_text)
                if not amount.is_finite() or amount < 0:
                    raise ValueError('Закупочная цена должна быть неотрицательным числом.')
                price = int((amount * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                with get_engine().begin() as conn:
                    linked = conn.execute(text(
                        'SELECT 1 FROM product_suppliers WHERE product_id=:p AND supplier_company_id=:s'
                    ), {'p': product_id, 's': supplier_id}).first()
                    if not linked:
                        raise ValueError('Сначала привяжите поставщика к изданию.')
                    current = conn.execute(text(
                        'SELECT supplier_price_id,wholesale_price,valid_from FROM supplier_product_prices '
                        'WHERE product_id=:p AND supplier_company_id=:s AND valid_to IS NULL'
                    ), {'p': product_id, 's': supplier_id}).mappings().first()
                    today = conn.execute(text("SELECT date('now')")).scalar_one()
                    if current and current['wholesale_price'] == price:
                        flash('Эта закупочная цена уже действует.', 'info')
                    elif current and current['valid_from'] == today:
                        conn.execute(text(
                            'UPDATE supplier_product_prices SET wholesale_price=:price '
                            'WHERE supplier_price_id=:id'
                        ), {'price': price, 'id': current['supplier_price_id']})
                        flash('Закупочная цена обновлена.', 'success')
                    else:
                        if current:
                            conn.execute(text(
                                "UPDATE supplier_product_prices SET valid_to=date('now','-1 day') "
                                "WHERE supplier_price_id=:id"
                            ), {'id': current['supplier_price_id']})
                        conn.execute(text(
                            "INSERT INTO supplier_product_prices(product_id,supplier_company_id,"
                            "wholesale_price,valid_from) VALUES(:p,:s,:price,date('now'))"
                        ), {'p': product_id, 's': supplier_id, 'price': price})
                        flash('Новая закупочная цена сохранена. Предыдущая цена осталась в истории.', 'success')
            elif action == 'preferred':
                with get_engine().begin() as conn:
                    linked = conn.execute(text(
                        'SELECT 1 FROM product_suppliers WHERE product_id=:p AND supplier_company_id=:s'
                    ), {'p': product_id, 's': supplier_id}).first()
                    if not linked:
                        raise ValueError('Связь с поставщиком не найдена.')
                    conn.execute(text('UPDATE product_suppliers SET is_preferred=0 WHERE product_id=:p'),
                                 {'p': product_id})
                    conn.execute(text(
                        'UPDATE product_suppliers SET is_preferred=1 WHERE product_id=:p AND supplier_company_id=:s'
                    ), {'p': product_id, 's': supplier_id})
                flash('Основной поставщик изменён.', 'success')
            else:
                raise ValueError('Неизвестное действие.')
        except (ValueError, InvalidOperation, ArithmeticError, TypeError) as exc:
            flash(str(exc) or 'Проверьте введённые данные.', 'error')
        except Exception:
            flash('Не удалось сохранить данные. Проверьте связь поставщика и периоды закупочных цен.', 'error')
        return redirect(url_for('admin.product_suppliers', product_id=product_id))

    rows = db.execute(text(
        "SELECT c.company_id,c.name,c.country,ps.supplier_catalog_number,ps.is_preferred,"
        "sp.wholesale_price,sp.valid_from "
        "FROM product_suppliers ps JOIN companies c ON c.company_id=ps.supplier_company_id "
        "LEFT JOIN supplier_product_prices sp ON sp.product_id=ps.product_id "
        "AND sp.supplier_company_id=ps.supplier_company_id AND sp.valid_to IS NULL "
        "WHERE ps.product_id=:id ORDER BY ps.is_preferred DESC,c.name"
    ), {'id': product_id}).mappings().all()
    history = db.execute(text(
        "SELECT c.name,sp.wholesale_price,sp.valid_from,sp.valid_to "
        "FROM supplier_product_prices sp JOIN companies c ON c.company_id=sp.supplier_company_id "
        "WHERE sp.product_id=:id ORDER BY sp.valid_from DESC,c.name"
    ), {'id': product_id}).mappings().all()
    available = db.execute(text(
        "SELECT c.company_id,c.name FROM suppliers s JOIN companies c ON c.company_id=s.company_id "
        "WHERE NOT EXISTS (SELECT 1 FROM product_suppliers ps WHERE ps.product_id=:id "
        "AND ps.supplier_company_id=c.company_id) ORDER BY c.name"
    ), {'id': product_id}).mappings().all()
    return render_template('employee/product_suppliers.html', product=product,
                           supplier_links=rows, price_history=history, available_suppliers=available)

