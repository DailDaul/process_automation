from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import text

from app.database import get_db, get_engine
from app.utils import current_user, login_required

bp = Blueprint('shop', __name__)
MAX_CART_QUANTITY = 99


def _clean_cart(raw_cart):
    """Возвращает корзину с корректными положительными ID и количествами."""
    cleaned = {}
    if not isinstance(raw_cart, dict):
        return cleaned
    for raw_id, raw_quantity in raw_cart.items():
        try:
            product_id = int(raw_id)
            quantity = int(raw_quantity)
        except (TypeError, ValueError):
            continue
        if product_id > 0 and 1 <= quantity <= MAX_CART_QUANTITY:
            cleaned[str(product_id)] = quantity
    return cleaned


def cart_data():
    cart = _clean_cart(session.get('cart', {}))
    if cart != session.get('cart', {}):
        session['cart'] = cart
    if not cart:
        return [], 0

    ids = [int(product_id) for product_id in cart]
    params = {f'id_{index}': product_id for index, product_id in enumerate(ids)}
    placeholders = ','.join(f':id_{index}' for index in range(len(ids)))
    rows = get_db().execute(text(
        f"SELECT p.product_id,p.title,p.catalog_number,pp.retail_price,"
        f"COALESCE(s.stock,0) AS stock, "
        f"COALESCE(s.stock,0)-COALESCE((SELECT SUM(oi.quantity) FROM order_items oi "
        f"JOIN orders o ON o.order_id=oi.order_id WHERE oi.product_id=p.product_id "
        f"AND o.status IN ('new','processing')),0) AS available_stock "
        f"FROM products p "
        f"JOIN product_prices pp ON pp.product_id=p.product_id AND pp.valid_to IS NULL "
        f"LEFT JOIN v_product_stock s ON s.product_id=p.product_id "
        f"WHERE p.is_active=1 AND p.product_id IN ({placeholders})"
    ), params).mappings().all()

    found_ids = {str(row['product_id']) for row in rows}
    removed_ids = set(cart) - found_ids
    for product_id in removed_ids:
        cart.pop(product_id, None)
    if removed_ids:
        session['cart'] = cart

    items = []
    total = 0
    for row in rows:
        item = dict(row)
        item['quantity'] = cart[str(row['product_id'])]
        item['line_total'] = item['quantity'] * item['retail_price']
        item['available'] = item['available_stock'] >= item['quantity']
        items.append(item)
        total += item['line_total']
    return items, total


@bp.get('/cart')
def cart():
    items, total = cart_data()
    return render_template('shop/cart.html', items=items, total=total)


@bp.post('/cart/add/<int:product_id>')
def cart_add(product_id):
    row = get_db().execute(text(
        "SELECT p.product_id,COALESCE(s.stock,0) AS stock, "
        "COALESCE(s.stock,0)-COALESCE((SELECT SUM(oi.quantity) FROM order_items oi "
        "JOIN orders o ON o.order_id=oi.order_id WHERE oi.product_id=p.product_id "
        "AND o.status IN ('new','processing')),0) AS available_stock "
        "FROM products p LEFT JOIN v_product_stock s ON s.product_id=p.product_id "
        "WHERE p.product_id=:id AND p.is_active=1"
    ), {'id': product_id}).mappings().first()
    if not row:
        abort(404)

    try:
        requested = int(request.form.get('quantity', '1'))
    except (TypeError, ValueError):
        flash('Количество должно быть целым числом.','error')
        return redirect(request.referrer or url_for('shop.cart'))
    if requested < 1:
        flash('Количество должно быть не меньше 1.','error')
        return redirect(request.referrer or url_for('shop.cart'))

    cart = _clean_cart(session.get('cart', {}))
    key = str(product_id)
    new_quantity = min(cart.get(key, 0) + requested, MAX_CART_QUANTITY)
    if new_quantity > row['available_stock']:
        flash(f"Сейчас доступно для заказа: {row['available_stock']} шт.", 'error')
        return redirect(request.referrer or url_for('shop.cart'))
    cart[key] = new_quantity
    session['cart'] = cart
    flash('Товар добавлен в корзину.','success')
    return redirect(request.referrer or url_for('shop.cart'))


@bp.post('/cart/update')
def cart_update():
    cart = _clean_cart(session.get('cart', {}))
    for key in list(cart):
        if key not in request.form:
            continue
        try:
            quantity = int(request.form.get(key, cart[key]))
        except (TypeError, ValueError):
            flash('Некорректное количество: используйте целое число.','error')
            continue
        if quantity <= 0:
            cart.pop(key, None)
        else:
            cart[key] = min(quantity, MAX_CART_QUANTITY)
    session['cart'] = cart
    flash('Корзина обновлена. Перед оформлением проверьте доступные остатки.','success')
    return redirect(url_for('shop.cart'))


@bp.post('/cart/remove/<int:product_id>')
def cart_remove(product_id):
    cart = _clean_cart(session.get('cart', {}))
    cart.pop(str(product_id), None)
    session['cart'] = cart
    return redirect(url_for('shop.cart'))


@bp.get('/wishlist')
@login_required
def wishlist():
    user = current_user()
    rows = get_db().execute(text(
        "SELECT p.*,pp.retail_price,COALESCE(s.stock,0) AS stock "
        "FROM wishlist_items wi "
        "JOIN wishlists w ON w.wishlist_id=wi.wishlist_id "
        "JOIN products p ON p.product_id=wi.product_id "
        "LEFT JOIN product_prices pp ON pp.product_id=p.product_id AND pp.valid_to IS NULL "
        "LEFT JOIN v_product_stock s ON s.product_id=p.product_id "
        "WHERE w.user_id=:u AND p.is_active=1 ORDER BY wi.added_at DESC"
    ), {'u': user['user_id']}).mappings().all()
    return render_template('shop/wishlist.html', products=rows)


@bp.post('/wishlist/toggle/<int:product_id>')
@login_required
def wishlist_toggle(product_id):
    user = current_user()
    get_db().rollback()  # освобождаем read-транзакцию проверки пользователя
    with get_engine().begin() as db:
        product_exists = db.execute(text(
            'SELECT 1 FROM products WHERE product_id=:p AND is_active=1'
        ), {'p': product_id}).first()
        if not product_exists:
            abort(404)

        db.execute(text(
            'INSERT OR IGNORE INTO wishlists(user_id) VALUES(:u)'
        ), {'u': user['user_id']})
        wishlist_id = db.execute(text(
            'SELECT wishlist_id FROM wishlists WHERE user_id=:u'
        ), {'u': user['user_id']}).scalar_one()
        exists = db.execute(text(
            'SELECT 1 FROM wishlist_items WHERE wishlist_id=:w AND product_id=:p'
        ), {'w': wishlist_id, 'p': product_id}).first()
        if exists:
            db.execute(text(
                'DELETE FROM wishlist_items WHERE wishlist_id=:w AND product_id=:p'
            ), {'w': wishlist_id, 'p': product_id})
        else:
            db.execute(text(
                'INSERT INTO wishlist_items(wishlist_id,product_id) VALUES(:w,:p)'
            ), {'w': wishlist_id, 'p': product_id})
    flash('Список желаемого обновлён.','success')
    return redirect(request.referrer or url_for('shop.wishlist'))


@bp.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    items, total = cart_data()
    if not items:
        flash('Корзина пуста или товары больше недоступны.','info')
        return redirect(url_for('catalog.index'))

    if request.method == 'POST':
        user = current_user()
        name = request.form.get('customer_name', user['username']).strip()
        phone = request.form.get('customer_phone', user['phone']).strip()
        email = request.form.get('customer_email', user['email'] or '').strip() or None
        if not name or len(name) > 200 or not phone or len(phone) > 30:
            flash('Проверьте имя получателя и телефон (не более 30 символов).','error')
            return render_template('shop/checkout.html', items=items, total=total)
        if email and (len(email) > 254 or '@' not in email):
            flash('Проверьте адрес электронной почты.','error')
            return render_template('shop/checkout.html', items=items, total=total)

        try:
            get_db().rollback()  # освобождаем read-транзакции корзины и пользователя
            with get_engine().begin() as db:
                # Сначала создаём заказ внутри транзакции записи. В SQLite это
                # сериализует конкурирующие оформления; ниже учитываем резервы
                # уже созданных заказов со статусами new/processing.
                db.execute(text(
                    "INSERT INTO orders(user_id,customer_name,customer_phone,customer_email,status) "
                    "VALUES(:u,:n,:p,:e,'new')"
                ), {'u': user['user_id'], 'n': name, 'p': phone, 'e': email})
                order_id = db.execute(text('SELECT last_insert_rowid()')).scalar_one()

                for item in items:
                    available = db.execute(text(
                        "SELECT COALESCE(s.stock,0) - COALESCE(("
                        "SELECT SUM(oi.quantity) FROM order_items oi "
                        "JOIN orders o ON o.order_id=oi.order_id "
                        "WHERE oi.product_id=:p AND o.status IN ('new','processing')"
                        "),0) AS available "
                        "FROM v_product_stock s WHERE s.product_id=:p"
                    ), {'p': item['product_id']}).scalar_one_or_none() or 0
                    if available < item['quantity']:
                        raise ValueError(
                            f"Недостаточно товара «{item['title']}». Доступно для заказа: {available} шт."
                        )
                    db.execute(text(
                        "INSERT INTO order_items(order_id,product_id,quantity,unit_price,product_title_snapshot,catalog_number_snapshot) "
                        "VALUES(:o,:p,:q,:price,:title,:cat)"
                    ), {
                        'o': order_id, 'p': item['product_id'], 'q': item['quantity'],
                        'price': item['retail_price'], 'title': item['title'],
                        'cat': item['catalog_number']
                    })

            session['cart'] = {}
            flash(f'Заказ №{order_id} создан! Товар зарезервирован до обработки заказа сотрудником.','success')
            return redirect(url_for('shop.orders'))
        except ValueError as exc:
            flash(str(exc), 'error')
        except Exception:
            flash('Не удалось оформить заказ. Проверьте корзину и попробуйте ещё раз.','error')

    return render_template('shop/checkout.html', items=items, total=total)


@bp.get('/orders')
@login_required
def orders():
    user = current_user()
    rows = get_db().execute(text(
        "SELECT o.*, (SELECT COALESCE(SUM(oi.quantity*oi.unit_price),0) "
        "FROM order_items oi WHERE oi.order_id=o.order_id) AS total "
        "FROM orders o WHERE o.user_id=:u ORDER BY o.created_at DESC"
    ), {'u': user['user_id']}).mappings().all()
    return render_template('shop/orders.html', orders=rows)
