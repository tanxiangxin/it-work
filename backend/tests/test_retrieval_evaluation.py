import asyncio

import pytest
from sqlalchemy import select

from app import models as m
from app.config import settings
from app.db import session
from app.jobs import process_import
from app.providers import MockProvider
from app.retrieval_evaluation import ranking_metrics, summarize_comparison, validate_cases


def test_document_metrics_deduplicate_chunks_and_ignore_unlabeled_cases():
    case = {"relevant_documents": ["a.md", "b.md"], "forbidden_documents": ["private.md"]}
    sources = [{"document_name": name} for name in ["x.md", "a.md", "a.md", "b.md", "private.md"]]
    metrics = ranking_metrics(case, sources)
    assert metrics["recall"] == {"1": 0, "3": 0.5, "5": 1}
    assert metrics["reciprocal_rank"] == 0.5 and metrics["forbidden_hits"] == ["private.md"]
    negative = ranking_metrics({"relevant_documents": []}, sources)
    assert negative["recall"] is None and negative["reciprocal_rank"] is None
    rows = [
        {
            "status": "complete",
            "metrics": {mode: metric for mode in ("vector", "hybrid")},
            "retrieval_ms": {"vector": 2, "hybrid": 3},
            "embedding_ms": 4,
        }
        for metric in (metrics, negative)
    ] + [{"status": "failed"}]
    summary = summarize_comparison(rows)
    assert summary["failures"] == 1 and summary["modes"]["hybrid"]["positive_cases"] == 1
    assert summary["modes"]["vector"]["mrr_at_5"] == 0.5
    assert summary["answer_accuracy"] is None


@pytest.mark.parametrize(
    "cases",
    [
        [],
        [{"id": "a", "question": " "}],
        [{"id": "a", "question": "x"}, {"id": "a", "question": "y"}],
        [{"id": "a", "question": "x", "relevant_documents": ["x"], "forbidden_documents": ["x"]}],
    ],
)
def test_invalid_retrieval_labels(cases):
    with pytest.raises(ValueError):
        validate_cases(cases)


def test_compare_uses_one_embedding_and_preserves_permissions_and_live_mode(clients, monkeypatch):
    student, admin, other = clients
    for name, visibility in [("public.md", "public"), ("private.md", "admin")]:
        response = admin.post(
            "/api/v1/documents",
            files={"file": (name, b"# VPN\n\nVPN error 809")},
            data={"visibility": visibility},
        )
        assert response.status_code == 201
        asyncio.run(process_import(response.json()["job_id"]))
    models = []

    def factory():
        model = MockProvider()
        models.append(model)
        return model

    monkeypatch.setattr("app.main.provider", factory)
    current_mode = settings().retrieval_mode
    response = student.post("/api/v1/retrieval/compare", json={"content": "VPN 809", "first_mode": "hybrid"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert models[0].calls == 1 and settings().retrieval_mode == current_mode
    assert result["order"] == ["hybrid", "vector"]
    assert {doc["document_name"] for doc in result["corpus"]} == {"public.md"}
    for mode in ("vector", "hybrid"):
        assert {s["document_name"] for s in result["results"][mode]} == {"public.md"}
    result = admin.post("/api/v1/retrieval/compare", json={"content": "VPN"}).json()
    assert {doc["document_name"] for doc in result["corpus"]} == {"public.md", "private.md"}
    public = next(doc for doc in result["corpus"] if doc["document_name"] == "public.md")
    updated = admin.post(
        "/api/v1/documents/" + public["document_id"] + "/versions",
        files={"file": ("public.md", b"# VPN\n\nVPN updated error 809")},
    ).json()
    asyncio.run(process_import(updated["job_id"]))
    current = student.post("/api/v1/retrieval/compare", json={"content": "VPN"}).json()
    for mode in ("vector", "hybrid"):
        assert {source["version_id"] for source in current["results"][mode]} == {updated["version_id"]}
    assert admin.delete("/api/v1/documents/" + public["document_id"]).status_code == 200
    withdrawn = student.post("/api/v1/retrieval/compare", json={"content": "VPN"}).json()
    assert withdrawn["corpus"] == [] and withdrawn["results"] == {"vector": [], "hybrid": []}
    other.post("/api/v1/auth/logout")
    assert other.post("/api/v1/retrieval/compare", json={"content": "VPN"}).status_code == 401
    assert (
        student.post(
            "/api/v1/retrieval/compare", json={"content": "VPN", "first_mode": "invalid"}
        ).status_code
        == 422
    )


def test_compare_rejects_concurrent_knowledge_change(clients, monkeypatch):
    student, _, _ = clients
    from app.main import retrieve_with_vector as original

    def change(db, *args, **kwargs):
        sources = original(db, *args, **kwargs)
        with session() as other_db:
            state = other_db.scalar(
                select(m.KnowledgeState).where(m.KnowledgeState.id == 1).with_for_update()
            )
            state.generation += 1
            other_db.commit()
        return sources

    monkeypatch.setattr("app.main.retrieve_with_vector", change)
    response = student.post("/api/v1/retrieval/compare", json={"content": "VPN"})
    assert response.status_code == 409 and response.json()["code"] == "KNOWLEDGE_CHANGED"
