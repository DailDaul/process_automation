from flask import Blueprint, render_template
from sqlalchemy import text
from app.database import get_db
bp = Blueprint('main', __name__)
@bp.get('/')
def index():
    db=get_db()
    featured=db.execute(text("SELECT p.*, m.name AS media_name, pr.retail_price, COALESCE(s.stock_quantity,0) stock FROM products p JOIN media_types m ON m.media_type_id=p.media_type_id LEFT JOIN product_prices pr ON pr.product_id=p.product_id AND pr.valid_to IS NULL LEFT JOIN v_product_stock s ON s.product_id=p.product_id WHERE p.is_active=1 ORDER BY p.product_id LIMIT 3")).mappings().all()
    return render_template('index.html', featured=featured)
@bp.get('/health')
def health():
    get_db().execute(text('SELECT 1'))
    return {'status':'ok','database':'connected'}
