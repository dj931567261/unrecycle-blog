from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from jwt.exceptions import PyJWTError
import bcrypt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from app.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, ADMIN_USERNAME, ADMIN_PASSWORD

# Custom OAuth2 password bearer that doesn't crash if header is missing,
# since we will also check cookies.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

# Helper to check if credentials match config
# We hash the config password dynamically for security during verification
ADMIN_PASSWORD_HASH = get_password_hash(ADMIN_PASSWORD)

def verify_admin_credentials(username, password):
    return username == ADMIN_USERNAME and verify_password(password, ADMIN_PASSWORD_HASH)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user_optional(request: Request):
    """
    Tries to retrieve the admin user from the Cookie 'access_token' or authorization header.
    Returns the username if authenticated, else None.
    """
    token = request.cookies.get("access_token")
    if not token:
        # Check header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            
    if not token:
        return None
        
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None or username != ADMIN_USERNAME:
            return None
        return username
    except PyJWTError:
        return None

async def get_current_user(username: Optional[str] = Depends(get_current_user_optional)):
    """
    Enforces authentication. Raises 401 if not logged in.
    """
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username
