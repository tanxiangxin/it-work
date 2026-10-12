import asyncio
import uuid

from test_integration import API, ask, upload

from app import models as m
from app.db import session
from app.jobs import process_import
from app.providers import MockProvider
from app.schemas import Answer


def test_withdrawn_history_never_reaches_model(clients, monkeypatch):
    student, admin, _ = clients
    withdrawn = upload(admin, name="withdraw.md", content="# VPN\n\nVPN 809 SECRET-HISTORY-MARKER 关闭代理。")
    conv, _ = ask(student)
    admin.patch(API + "/documents/" + withdrawn["document_id"] + "/visibility", json={"visibility": "admin"})
    upload(admin, name="new.md", content="# 网络\n\n网络错误 809 先检查连接。")
    captured = []

    async def spy(self, question, sources, history):
        captured.extend(history)
        return Answer(answer="检查网络", answerable=True, sources=[sources[0]["number"]])

    monkeypatch.setattr(MockProvider, "answer", spy)
    assert ask(student, "网络 809", conv)[1]["answer"]["answerable"]
    assert all("SECRET-HISTORY-MARKER" not in item["content"] for item in captured)


def test_queued_index_cannot_be_written_by_a_different_model(clients):
    _, admin, _ = clients
    data = admin.post(API + "/documents", files={"file": ("x.txt", b"VPN809")}).json()
    with session() as db:
        db.get(m.DocumentVersion, uuid.UUID(data["version_id"])).index_key = "another-model:1024"
        db.commit()
    asyncio.run(process_import(data["job_id"]))
    job = admin.get(API + "/jobs/" + data["job_id"]).json()
    assert job["status"] == "failed" and job["error"].startswith("INDEX_MISMATCH")


def test_hybrid_candidates_deduplicate_and_vector_switch(clients, monkeypatch):
    student, admin, _ = clients
    upload(admin)
    _, events = ask(student)
    citations = events["answer"]["citations"]
    assert len({c["chunk_id"] for c in citations}) == len(citations)
    from app.config import settings

    monkeypatch.setattr(settings(), "retrieval_mode", "vector")
    assert ask(student)[1]["answer"]["answerable"]
