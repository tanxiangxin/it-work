"""Metrics for document ranking; deliberately separate from answer quality."""

import math
import statistics


def validate_cases(cases):
    if not isinstance(cases, list) or not cases:
        raise ValueError("Cases must be a nonempty list")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"]:
            raise ValueError("Each case needs an ID")
        if case["id"] in ids:
            raise ValueError("Case IDs must be unique")
        ids.add(case["id"])
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            raise ValueError("Each case needs a nonempty question")
        relevant = case.get("relevant_documents", [])
        forbidden = case.get("forbidden_documents", [])
        if any(
            not isinstance(items, list) or any(not isinstance(x, str) or not x for x in items)
            for items in (relevant, forbidden)
        ):
            raise ValueError("Document labels must be lists of nonempty names")
        if set(relevant) & set(forbidden):
            raise ValueError("Relevant and forbidden labels overlap")
    return cases


def ranking_metrics(case, sources):
    relevant = set(case.get("relevant_documents", []))
    names = [source["document_name"] for source in sources]
    rank = next((i for i, name in enumerate(names[:5], 1) if name in relevant), None)
    return {
        "recall": {str(k): len(set(names[:k]) & relevant) / len(relevant) for k in (1, 3, 5)}
        if relevant
        else None,
        "reciprocal_rank": (1 / rank if rank else 0) if relevant else None,
        "forbidden_hits": sorted(set(names) & set(case.get("forbidden_documents", []))),
        "retrieved_documents": names,
    }


def distribution(values):
    ordered = sorted(values)
    return {
        "median": statistics.median(ordered) if ordered else None,
        "p95": ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)] if ordered else None,
    }


def summarize_comparison(results):
    complete = [item for item in results if item["status"] == "complete"]
    output = {
        "cases": len(results),
        "completed": len(complete),
        "failures": len(results) - len(complete),
        "answer_accuracy": None,
        "unstable_cases": sum(item.get("stable_rankings") is False for item in complete),
        "modes": {},
    }
    for mode in ("vector", "hybrid"):
        scored = [item["metrics"][mode] for item in complete if item["metrics"][mode]["recall"] is not None]
        output["modes"][mode] = {
            "positive_cases": len(scored),
            "recall_at": {
                str(k): statistics.mean(item["recall"][str(k)] for item in scored) if scored else None
                for k in (1, 3, 5)
            },
            "mrr_at_5": statistics.mean(item["reciprocal_rank"] for item in scored) if scored else None,
            "forbidden_hit_cases": sum(bool(item["metrics"][mode]["forbidden_hits"]) for item in complete),
            "retrieval_ms": distribution([item["retrieval_ms"][mode] for item in complete]),
        }
    output["embedding_ms"] = distribution([item["embedding_ms"] for item in complete])
    return output
