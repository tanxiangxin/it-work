import threading

from rank_bm25 import BM25Okapi
from sqlalchemy import select

from app.config import settings
from app.models import Chunk, Document, DocumentVersion, KnowledgeState
from app.providers import tokenize

_cache = {}
_lock = threading.Lock()


def trim_context_overlap(content, previous):
    for text in previous:
        if content in text:
            return ""
        for length in range(min(settings().chunk_overlap, len(content), len(text)), 19, -1):
            if content[:length] == text[-length:]:
                content = content[length:]
                break
            if content[-length:] == text[:length]:
                content = content[:-length]
                break
    return content


def allowed_query(user, course_id=None):
    query = (
        select(Chunk, Document)
        .join(DocumentVersion, Chunk.version_id == DocumentVersion.id)
        .join(Document, Document.active_version_id == DocumentVersion.id)
        .where(
            Document.deleted.is_(False),
            Document.archived.is_(False),
            ~Chunk.heading.endswith("网页来源"),
            DocumentVersion.status == "ready",
            DocumentVersion.index_key == settings().index_key,
        )
    )
    if course_id is not None:
        return query.where(Document.owner_id == user.id, Document.course_id == course_id)
    query = query.where(Document.owner_id.is_(None))
    if user.role != "admin":
        query = query.where(Document.visibility == "public")
    return query


def retrieve_with_vector(db, user, question, vector, mode=None, course_id=None):
    mode = mode or settings().retrieval_mode
    if mode not in {"vector", "hybrid"}:
        raise ValueError("Unsupported retrieval mode")
    query = allowed_query(user, course_id)
    vector_rows = db.execute(
        query.order_by(Chunk.embedding.cosine_distance(vector), Chunk.id).limit(20)
    ).all()
    vector_ids = [str(c.id) for c, _ in vector_rows]
    scores = {key: 1 / (60 + rank) for rank, key in enumerate(vector_ids, 1)}
    rows_by_id = {str(c.id): (c, d) for c, d in vector_rows}
    if mode == "hybrid":
        generation = db.get(KnowledgeState, 1).generation
        cache_key = (
            str(user.id) if course_id else user.role,
            str(course_id),
            generation,
            settings().index_key,
        )
        with _lock:
            cached = _cache.get(cache_key)
        if not cached:
            all_rows = db.execute(query.order_by(Chunk.id)).all()
            tokens = [tokenize(c.content + " " + c.heading) or ["_"] for c, _ in all_rows]
            cached = (all_rows, BM25Okapi(tokens) if tokens else None)
            with _lock:
                _cache.clear()
                _cache[cache_key] = cached
        all_rows, bm25 = cached
        if bm25:
            terms = tokenize(question)
            bm_scores = bm25.get_scores(terms)
            indexes = sorted(range(len(bm_scores)), key=lambda i: (-bm_scores[i], i))[:20]
            rank = 0
            for index in indexes:
                c, d = all_rows[index]
                if not (set(terms) & set(tokenize(c.content + " " + c.heading))):
                    continue
                rank += 1
                key = str(c.id)
                scores[key] = scores.get(key, 0) + 1 / (60 + rank)
                rows_by_id[key] = c, d
    sources = []
    remaining = settings().max_context_chars
    seen = set()
    for key in sorted(scores, key=lambda k: (-scores[k], k)):
        if len(sources) >= settings().retrieval_top_k:
            break
        c, d = rows_by_id[key]
        normalized = "".join(c.content.split())
        if normalized in seen:
            continue
        seen.add(normalized)
        text = trim_context_overlap(
            c.content, [s["content"] for s in sources if s["version_id"] == str(c.version_id)]
        )
        if not text.strip():
            continue
        # Preserve full headings in stored chunks/source API; bound model context.
        heading = c.heading[:512]
        allowance = min(settings().chunk_size, remaining - len(heading) - len(d.name))
        if allowance <= 0:
            break
        content = text[:allowance]
        remaining -= len(content) + len(heading) + len(d.name)
        sources.append(
            {
                "number": len(sources) + 1,
                "chunk_id": str(c.id),
                "version_id": str(c.version_id),
                "document_id": str(d.id),
                "document_name": d.name,
                "content": content,
                "heading": heading,
                "page": c.page,
                "paragraph": c.paragraph,
                "source_spans": c.source_spans,
            }
        )
    return sources
