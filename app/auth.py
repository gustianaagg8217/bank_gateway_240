import os
import hashlib
from fastapi import HTTPException, Header

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "admin-secret")


def verify_admin_token(x_admin_token: str = Header(default="")) -> None:
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin token required")


def hash_password(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
