import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'rentsafe-super-secret-key-2026-prod-jwt-9842')
    DATABASE_PATH = os.path.join(BASE_DIR, 'rentsafe.db')
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    DEEDS_FOLDER = os.path.join(UPLOAD_FOLDER, 'deeds')
    PROPERTIES_FOLDER = os.path.join(UPLOAD_FOLDER, 'properties')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'webp'}
    
    # SMTP Email Configuration
    SMTP_CONFIG_FILE = os.path.join(BASE_DIR, 'smtp_config.json')
    DEFAULT_SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    DEFAULT_SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    DEFAULT_SMTP_USER = os.environ.get('SMTP_USER', '')
    DEFAULT_SMTP_PASS = os.environ.get('SMTP_PASS', '')
    DEFAULT_FROM_EMAIL = os.environ.get('FROM_EMAIL', 'noreply@rentsafe.com')
    DEFAULT_USE_TLS = True
