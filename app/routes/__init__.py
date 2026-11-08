from app.routes.main import bp as main_bp
from app.routes.auth import bp as auth_bp
from app.routes.catalog import bp as catalog_bp
from app.routes.shop import bp as shop_bp
from app.routes.admin import bp as admin_bp

def register_routes(app):
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(catalog_bp, url_prefix='/catalog')
    app.register_blueprint(shop_bp)
    app.register_blueprint(admin_bp, url_prefix='/employee')
    from app.utils import current_user, money
    @app.context_processor
    def inject_globals():
        return {'current_user': current_user(), 'money': money}
