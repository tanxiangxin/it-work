import asyncio
import uuid

from sqlalchemy import func, select

from app import models as m
from app.cli import reindex
from app.config import settings
from app.db import session
from app.storage import storage
from tests.test_integration import upload


def test_reindex_preserves_files_and_can_restore_prior_index(clients, monkeypatch):
    _, admin, _ = clients
    created = upload(admin)
    id = uuid.UUID(created["document_id"])
    original_size = settings().chunk_size
    with session() as db:
        original = db.get(m.DocumentVersion, uuid.UUID(created["version_id"]))
        original_key = original.storage_key
        original_content = storage.path(original_key).read_bytes()
    monkeypatch.setattr(settings(), "chunk_size", original_size + 1)
    asyncio.run(reindex())
    with session() as db:
        assert str(db.get(m.Document, id).active_version_id) != created["version_id"]
        assert db.scalar(select(func.count()).select_from(m.DocumentVersion)) == 2
    monkeypatch.setattr(settings(), "chunk_size", original_size)
    asyncio.run(reindex())
    asyncio.run(reindex())  # Existing ready versions are republished, without duplication.
    with session() as db:
        assert str(db.get(m.Document, id).active_version_id) == created["version_id"]
        assert db.scalar(select(func.count()).select_from(m.DocumentVersion)) == 2
    assert storage.path(original_key).read_bytes() == original_content
