import uuid

from sqlalchemy import select
from test_integration import API, ask
from test_notifications import make_ticket

from app import models as m
from app.db import session


def test_clear_recent_preserves_history_and_other_accounts(clients):
    student, _, other = clients
    first, _ = ask(student, "你好")
    second, _ = ask(student, "谢谢")
    other_id, _ = ask(other, "你好")
    response = student.delete(API + "/conversations")
    assert response.status_code == 200 and response.json()["cleared"] == 2
    assert student.get(API + "/conversations").json()["total"] == 0
    history = student.get(API + "/conversations?history=true").json()
    assert {c["id"] for c in history["items"]} == {first, second}
    assert student.get(API + f"/conversations/{first}").json()["messages"][-1]["content"]
    assert other.get(API + "/conversations").json()["items"][0]["id"] == other_id
    new_id = student.post(API + "/conversations").json()["id"]
    assert student.get(API + "/conversations").json()["items"][0]["id"] == new_id
    assert student.get(API + "/conversations?history=true&page_size=1").json()["total"] == 3


def test_clear_history_removes_access_and_keeps_tickets(clients):
    student, _, other = clients
    old_id, _ = ask(student, "你好")
    student.delete(API + "/conversations")
    recent_id = student.post(API + "/conversations").json()["id"]
    ticket_id, _ = make_ticket(student)
    other_id = other.post(API + "/conversations").json()["id"]
    response = student.delete(API + "/conversations?history=true")
    assert response.status_code == 200 and response.json()["cleared"] == 3
    for suffix in ["", "?history=true"]:
        assert student.get(API + "/conversations" + suffix).json()["total"] == 0
    for id in [old_id, recent_id]:
        assert student.get(API + f"/conversations/{id}").status_code == 404
        assert (
            student.post(API + f"/conversations/{id}/messages", json={"content": "你好"}).status_code == 404
        )
    assert student.get(API + f"/tickets/{ticket_id}").status_code == 200
    assert other.get(API + f"/conversations/{other_id}").status_code == 200
    assert student.delete(API + "/conversations?history=true").json()["cleared"] == 0


def test_clear_history_rejects_pending_answer_atomically(clients):
    student, _, _ = clients
    id = student.post(API + "/conversations").json()["id"]
    with session() as db:
        db.add(m.Message(conversation_id=uuid.UUID(id), role="assistant", content="", status="pending"))
        db.commit()
    assert student.delete(API + "/conversations?history=true").status_code == 409
    assert student.get(API + "/conversations").json()["total"] == 1
    with session() as db:
        message = db.scalar(select(m.Message).where(m.Message.conversation_id == uuid.UUID(id)))
        message.status = "complete"
        db.commit()
    assert student.delete(API + "/conversations?history=true").status_code == 200


def test_clear_requires_login(clients):
    student, _, _ = clients
    student.post(API + "/auth/logout")
    assert student.delete(API + "/conversations").status_code == 401
