from pathlib import Path
from flask import Flask
from dotenv import load_dotenv
import os
from app.database import init_database

def create_app(test_config=None):
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config.from_mapping(
        SECRET_KEY=os.getenv('SECRET_KEY', 'dev-only-change-me'),
        DATABASE_URL=f"sqlite:///{Path(app.instance_path) / 'mashup.db'}",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
    )
    if test_config:
        app.config.update(test_config)
    init_database(app)
    from app.routes import register_routes
    register_routes(app)
    return app
