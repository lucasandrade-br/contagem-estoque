import os
from datetime import timedelta


class Config:
    """Application configuration."""
    SECRET_KEY = os.getenv('SECRET_KEY', 'chave_secreta_padaria_segura')
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DATABASE = os.path.join(BASE_DIR, 'database', 'padaria.db')
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    DEBUG = os.getenv('FLASK_DEBUG', 'true').lower() == 'true'
    HOST = os.getenv('FLASK_RUN_HOST', '0.0.0.0')
    PORT = int(os.getenv('FLASK_RUN_PORT', 5000))
