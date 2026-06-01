from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta, timezone

SECRET_KEY = "6ddc5f078a0ff68ffe6b0e287b035cc5" #generated from https://randomkeygen.com/
ALGORITHM= "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60*24 #60 minutes x 24 hours = 1 day in minute

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def hash_password(password: str):
    # Passlib handles the 'salting' automatically
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    # This compares the attempt vs the stored hash
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)