from pathlib import Path


class Config:
    SECRET_KEY = "development-key-change-before-release"
    BASE_DIR = Path(__file__).resolve().parent.parent
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{BASE_DIR / 'instance' / 'mashup.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
