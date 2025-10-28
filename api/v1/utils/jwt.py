from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt
from api.v1.config import auth_config

ALGORITHM = "HS256"

def create_jwt_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, auth_config.JWT_SECRET_KEY, algorithm=ALGORITHM)