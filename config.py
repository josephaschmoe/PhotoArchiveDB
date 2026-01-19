import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-please-change'
    # Use SQLite
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(os.getcwd(), 'instance', 'archivedb.sqlite')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Default to a 'library' folder in the project root for dev
    LIBRARY_PATH = os.environ.get('LIBRARY_PATH') or os.path.join(os.getcwd(), 'test_assets')
    
    # Increase timeout to fix "database is locked" errors
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"timeout": 30}
    }
