import uuid

from sqlalchemy import select

from app import models as m
from app.db import session

API = "/api/v1"


def make_ticket(student):
    owner = student.get(API + "/auth/me").json()["id"]
    with session() as db:
        conv = m.Conversation(user_id=uuid.UUID(owner))
        db.add(conv)
        db.flush()
        draft = m.TicketDraft(
            user_id=uuid.UUID(owner),
            conversation_id=conv.id,
            title="网络故障",
            category="校园网络",
            description="无法连接校园网",
        )
        db.add(draft)
        db.commit()
        payload = {
            "draft_id": str(draft.id),
            "title": draft.title,
            "category": draft.category,
            "description": draft.description,
        }
    response = student.post(API + "/tickets", json=payload, headers={"Idempotency-Key": "notify-test"})
    assert response.status_code == 201
    return response.json()["id"], payload


def test_recipients_idempotency_and_read_permissions(clients):
    student, admin, other = clients
    ticket, payload = make_ticket(student)
    assert student.get(API + "/notifications").json()["total"] == 0
    assert other.get(API + "/notifications").json()["total"] == 0
    notices = admin.get(API + "/notifications").json()
    assert notices["total"] == 1
    notice = notices["items"][0]
    assert notice["kind"] == "ticket_created" and notice["ticket_id"] == ticket
    student.post(API + "/tickets", json=payload, headers={"Idempotency-Key": "notify-test"})
    student.post(API + "/tickets", json=payload, headers={"Idempotency-Key": "second-key"})
    assert admin.get(API + "/notifications").json()["total"] == 1
    assert student.post(API + "/notifications/" + notice["id"] + "/read").status_code == 404
    assert admin.post(API + "/notifications/" + notice["id"] + "/read").status_code == 200
    first = admin.post(API + "/notifications/" + notice["id"] + "/read").json()["read_at"]
    assert admin.post(API + "/notifications/" + notice["id"] + "/read").json()["read_at"] == first
    assert admin.get(API + "/notifications/updates").json()["unread_count"] == 0

    baseline = student.get(API + "/notifications/updates").json()
    assert baseline["items"] == []
    admin.post(API + f"/tickets/{ticket}/replies", json={"content": "请补充错误截图"})
    updates = student.get(API + f"/notifications/updates?after={baseline['cursor']}").json()
    assert updates["unread_count"] == 1
    assert updates["items"][0]["kind"] == "ticket_reply"
    assert "错误截图" in updates["items"][0]["content"]
    assert admin.get(API + "/notifications").json()["total"] == 1
    assert other.get(API + "/notifications/updates?after=0").json()["items"] == []
    admin.patch(API + f"/tickets/{ticket}/status", json={"status": "resolved"})
    student.patch(API + f"/tickets/{ticket}/status", json={"status": "closed"})
    assert admin.get(API + "/notifications/updates").json()["unread_count"] == 1
    before = student.get(API + "/notifications").json()["total"]
    assert admin.post(API + f"/tickets/{ticket}/replies", json={"content": "late"}).status_code == 409
    assert student.get(API + "/notifications").json()["total"] == before
    assert student.post(API + "/notifications/read-all").status_code == 200
    assert student.get(API + "/notifications/updates").json()["unread_count"] == 0
    student.post(API + "/auth/logout")
    assert student.get(API + "/notifications").status_code == 401


def test_offline_history_and_paginated_catchup(clients):
    student, admin, _ = clients
    ticket, _ = make_ticket(student)
    with session() as db:
        owner = db.scalar(select(m.User).where(m.User.email == "student@example.test"))
        db.add_all(
            [
                m.Notification(
                    user_id=owner.id,
                    ticket_id=uuid.UUID(ticket),
                    event_id=uuid.uuid4(),
                    kind="ticket_reply",
                    title="回复",
                    content=str(i),
                )
                for i in range(105)
            ]
        )
        db.commit()
    initial = student.get(API + "/notifications/updates").json()
    assert initial["items"] == [] and initial["unread_count"] == 105
    assert student.get(API + "/notifications?page=2").json()["total"] == 105
    first = student.get(API + "/notifications/updates?after=0").json()
    second = student.get(API + f"/notifications/updates?after={first['cursor']}").json()
    assert len(first["items"]) == 100 and len(second["items"]) == 5
    assert not set(x["id"] for x in first["items"]) & set(x["id"] for x in second["items"])
    admin.post(API + "/notifications/read-all")
    assert student.get(API + "/notifications/updates").json()["unread_count"] == 105
