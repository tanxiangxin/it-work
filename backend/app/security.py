import hashlib
from datetime import timedelta

from argon2 import PasswordHasher
from fastapi import Depends, Request
from sqlalchemy import select

from app.db import get_db
from app.errors import AppError
from app.models import LoginSession, User, now

passwords = PasswordHasher()


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request, db=Depends(get_db)):
    token = request.cookies.get("campus_session", "")
    login = db.scalar(
        select(LoginSession).where(
            LoginSession.token_hash == token_hash(token), LoginSession.expires_at > now()
        )
    )
    if not login:
        raise AppError("UNAUTHENTICATED", "请先登录", 401)
    return db.get(User, login.user_id)


def admin(user=Depends(current_user)):
    if user.role != "admin":
        raise AppError("FORBIDDEN", "需要管理员权限", 403)
    return user


def make_session(db, user, token):
    db.add(LoginSession(user_id=user.id, token_hash=token_hash(token), expires_at=now() + timedelta(days=7)))
