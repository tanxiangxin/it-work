"""Notifications are committed atomically with the business event."""

from sqlalchemy import select, text

from app import models as m


def notify_ticket(db, ticket, actor, event_id, kind, title, content):
    recipients = set(db.scalars(select(m.User.id).where(m.User.role == "admin")))
    if kind != "ticket_created":
        recipients.add(ticket.user_id)
    recipients.discard(actor.id)
    emit(db, recipients, event_id, kind, title, content, ticket_id=ticket.id)


def emit(db, recipients, event_id, kind, title, content, **target):
    if not recipients:
        return
    # Serialize allocation through commit: polling cursors cannot skip a late-committing event.
    db.execute(text("SELECT pg_advisory_xact_lock(74201984)"))
    for recipient in sorted(recipients):
        db.add(
            m.Notification(
                user_id=recipient,
                **target,
                event_id=event_id,
                kind=kind,
                title=title,
                content=content[:500],
            )
        )
    db.flush()
