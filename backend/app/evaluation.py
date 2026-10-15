"""Protocol and expectation checks, deliberately separate from human answer grading."""

import json
import math
import statistics


def parse_sse(lines):
    event, data = "message", []
    for raw in lines:
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        line = line.rstrip("\r\n")
        if not line:
            if data:
                yield {"event": event, "data": json.loads("\n".join(data))}
            event, data = "message", []
        elif not line.startswith(":"):
            field, separator, value = line.partition(":")
            if separator:
                value = value[1:] if value.startswith(" ") else value
                if field == "event":
                    event = value
                elif field == "data":
                    data.append(value)
    if data:
        yield {"event": event, "data": json.loads("\n".join(data))}


def inspect_events(case, events):
    errors = [event["data"] for event in events if event["event"] == "error"]
    if errors:
        return {"status": "model_failure", "errors": errors}
    answers = [event["data"] for event in events if event["event"] == "answer"]
    if not events or events[-1]["event"] != "done" or len(answers) != 1:
        return {"status": "protocol_failure", "code": "INCOMPLETE_SSE"}
    answer = answers[0]
    if not isinstance(answer, dict):
        return {"status": "protocol_failure", "code": "INVALID_ANSWER"}
    if answer.get("model_mode") != "real":
        return {"status": "protocol_failure", "code": "NON_REAL_ANSWER"}
    if not isinstance(answer.get("answerable"), bool) or not isinstance(answer.get("citations"), list):
        return {"status": "protocol_failure", "code": "INVALID_ANSWER"}
    if not answer.get("answer_id") or not isinstance(answer.get("content"), str):
        return {"status": "protocol_failure", "code": "INVALID_ANSWER"}
    citations = answer["citations"]
    if answer["answerable"] and not citations and answer.get("answer_kind", "knowledge") != "general":
        return {"status": "protocol_failure", "code": "MISSING_CITATIONS"}
    if answer.get("answer_kind") == "general" and citations:
        return {"status": "protocol_failure", "code": "GENERAL_WITH_CITATIONS"}
    if not answer["answerable"] and citations:
        return {"status": "protocol_failure", "code": "REFUSAL_WITH_CITATIONS"}
    if any(
        not isinstance(item, dict) or not item.get("chunk_id") or not item.get("version_id")
        for item in citations
    ):
        return {"status": "protocol_failure", "code": "INVALID_CITATIONS"}
    expected = case.get("expected_document")
    return {
        "status": "complete",
        "answer": answer,
        "answerability_match": answer["answerable"] == case["answerable"],
        "answer_kind_match": None
        if not case.get("answer_kind")
        else answer.get("answer_kind", "knowledge") == case["answer_kind"],
        "expected_document_cited": None
        if not expected
        else any(item.get("document_name") == expected for item in citations),
        "human_supported_answer": None,
    }


def summarize(results):
    completed = [result for result in results if result["status"] == "complete"]
    times = sorted(result["elapsed_ms"] for result in completed)
    return {
        "cases": len(results),
        "completed": len(completed),
        "failures": len(results) - len(completed),
        "expectation_failures": sum(
            any(
                result.get(key) is False
                for key in (
                    "answerability_match",
                    "answer_kind_match",
                    "expected_document_cited",
                    "citations_verified",
                )
            )
            for result in completed
        ),
        "answerability_matches": sum(result["answerability_match"] for result in completed),
        "answer_kind_checks": sum(result.get("answer_kind_match") is not None for result in completed),
        "answer_kind_matches": sum(result.get("answer_kind_match") is True for result in completed),
        "expected_document_checks": sum(
            result["expected_document_cited"] is not None for result in completed
        ),
        "expected_document_matches": sum(result["expected_document_cited"] is True for result in completed),
        "citation_verification_failures": sum(
            result.get("citations_verified") is False for result in completed
        ),
        "completed_latency_ms": {
            "median": statistics.median(times) if times else None,
            "p95": times[max(0, math.ceil(len(times) * 0.95) - 1)] if times else None,
        },
        "human_answer_accuracy": None,
        "cost": None,
    }
