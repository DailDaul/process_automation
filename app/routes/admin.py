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
