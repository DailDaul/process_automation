import os
import redis
from flask import Blueprint, render_template
from sqlalchemy import text
from app.database import get_db

bp = Blueprint('main', __name__)

# Laboratornaya 5x
# Инициализация клиента Redis.
# Хост и порт берутся из переменных окружения (они заданы в docker-compose.yaml).
# Если Redis недоступен, приложение продолжит работать, просто счётчик не будет увеличиваться.
try:
    redis_client = redis.Redis(
        host=os.environ.get('REDIS_HOST', 'localhost'),
        port=int(os.environ.get('REDIS_PORT', 6379)),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2
    )
    # Проверяем соединение при старте (необязательно, но полезно для логов)
    redis_client.ping()
except Exception as e:
    print(f"ВНИМАНИЕ: Redis недоступен ({e}). Счётчик посещений работать не будет.")
    redis_client = None


@bp.get('/')
def index():
    db = get_db()
    
    # --- Работа со сторонним сервисом (Redis) ---
    visits = 0
    if redis_client:
        try:
            visits = redis_client.incr('visits')
        except Exception as e:
            print(f"Ошибка при обращении к Redis: {e}")
            visits = 0

    # --- Основная логика приложения ---
    featured = db.execute(text(
        "SELECT p.*, m.name AS media_name, pr.retail_price, COALESCE(s.stock_quantity,0) stock "
        "FROM products p "
        "JOIN media_types m ON m.media_type_id=p.media_type_id "
        "LEFT JOIN product_prices pr ON pr.product_id=p.product_id AND pr.valid_to IS NULL "
        "LEFT JOIN v_product_stock s ON s.product_id=p.product_id "
        "WHERE p.is_active=1 ORDER BY p.product_id LIMIT 3"
    )).mappings().all()
    
    return render_template('index.html', featured=featured, visits=visits)


@bp.get('/health')
def health():
    get_db().execute(text('SELECT 1'))
    return {'status': 'ok', 'database': 'connected'}
