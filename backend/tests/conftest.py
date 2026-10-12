import os
import uuid
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL/pgvector test database")
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    schema = "campus_test_" + uuid.uuid4().hex
    bootstrap = create_engine(url)
    with bootstrap.begin() as db:
        db.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
        db.execute(text(f"CREATE SCHEMA {schema}"))
    test_url = make_url(url).update_query_dict({"options": f"-csearch_path={schema},public"})
    os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)
    os.environ["MODEL_MODE"] = "mock"
    from app.config import settings
    from app.db import engine

    settings.cache_clear()
    engine.cache_clear()
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    command.upgrade(cfg, "head")
    # Alembic must create every test table here, never fall back to public.
    from sqlalchemy import inspect

    from app.models import Base

    assert set(Base.metadata.tables).issubset(inspect(engine()).get_table_names(schema=schema))
    yield engine()
    engine().dispose()
    with bootstrap.begin() as db:
        db.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    bootstrap.dispose()


@pytest.fixture
def clients(database, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app import models as m
    from app.config import settings
    from app.db import session
    from app.main import app
    from app.security import passwords

    monkeypatch.setattr(settings(), "storage_dir", tmp_path)
    # API/worker integration is deterministic; the separate broker test exercises Celery dispatch.
    monkeypatch.setattr("app.main.enqueue", lambda job_id: None)
    monkeypatch.setattr("app.jobs.enqueue", lambda job_id: None)
    monkeypatch.setattr("app.campus.enqueue", lambda job_id: None)
    monkeypatch.setattr("app.campus.enqueue_search", lambda job_id: None)
    monkeypatch.setattr("app.course_materials.enqueue_search", lambda job_id: None)
    monkeypatch.setattr("app.study_jobs.enqueue_study", lambda job_id: None)
    names = ",".join(t.name for t in m.Base.metadata.sorted_tables if t.name != "knowledge_state")
    with database.begin() as db:
        db.execute(text("TRUNCATE " + names + " CASCADE"))
    from app.retrieval import _cache

    _cache.clear()
    with session() as db:
        for email, role in [
            ("student@example.test", "student"),
            ("admin@example.test", "admin"),
            ("other@example.test", "student"),
        ]:
            db.add(m.User(email=email, role=role, name=role, password_hash=passwords.hash("test-password")))
        db.commit()
    with TestClient(app) as student, TestClient(app) as admin, TestClient(app) as other:
        for client, email in [
            (student, "student@example.test"),
            (admin, "admin@example.test"),
            (other, "other@example.test"),
        ]:
            assert (
                client.post(
                    "/api/v1/auth/login", json={"email": email, "password": "test-password"}
                ).status_code
                == 200
            )
        yield student, admin, other
