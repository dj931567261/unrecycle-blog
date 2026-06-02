import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./blog.db")

# Security configuration
SECRET_KEY = os.getenv("SECRET_KEY", "devhub_super_secret_key_change_me_in_production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 1 week

# Admin credentials
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
# Default password is 'admin123' (will be hashed if needed)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

# Upload directory
UPLOAD_DIR = BASE_DIR / "app" / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
