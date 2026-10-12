import pytest
from sqlalchemy import func, select

from app import models as m
from app.db import session


@pytest.mark.parametrize(
    "email,role,wrong_entry",
    [
        ("student@example.test", "student", "admin"),
        ("admin@example.test", "admin", "student"),
    ],
)
def test_login_entry_checks_role_before_creating_session(clients, email, role, wrong_entry):
    client = clients[0] if role == "student" else clients[1]
    client.post("/api/v1/auth/logout")
    with session() as db:
        before = db.scalar(select(func.count()).select_from(m.LoginSession))
    payload = {"email": email, "password": "test-password", "entry_role": wrong_entry}
    rejected = client.post("/api/v1/auth/login", json=payload)
    assert rejected.status_code == 403
    assert rejected.json()["code"] == "LOGIN_ENTRY_MISMATCH"
    assert "set-cookie" not in rejected.headers
    assert client.get("/api/v1/auth/me").status_code == 401
    with session() as db:
        assert db.scalar(select(func.count()).select_from(m.LoginSession)) == before
    payload["entry_role"] = role
    accepted = client.post("/api/v1/auth/login", json=payload)
    assert accepted.status_code == 200 and accepted.json()["role"] == role
    assert client.get("/api/v1/documents").status_code == (200 if role == "admin" else 403)
