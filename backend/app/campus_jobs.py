from sqlalchemy import or_, select

from app import models as m
from app.db import session
from app.notifications import emit


def deliver_reminders():
    """Row locks plus notification/event uniqueness make scheduler retries safe."""
    with session() as db:
        todos = db.scalars(
            select(m.Todo)
            .where(
                m.Todo.completed.is_(False),
                m.Todo.reminded_at.is_(None),
                m.Todo.remind_at <= m.now(),
                or_(
                    m.Todo.announcement_id.is_(None),
                    m.Todo.announcement_id.in_(
                        select(m.Announcement.id).where(m.Announcement.status == "published")
                    ),
                ),
            )
            .with_for_update(skip_locked=True)
            .limit(100)
        ).all()
        for todo in todos:
            notice = db.get(m.Announcement, todo.announcement_id) if todo.announcement_id else None
            if notice and notice.status != "published":
                continue
            emit(db, {todo.user_id}, todo.id, "todo_reminder", "待办提醒", todo.title, todo_id=todo.id)
            todo.reminded_at = m.now()
        db.commit()
        return len(todos)
