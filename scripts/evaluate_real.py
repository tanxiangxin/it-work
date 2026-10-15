"""Opt-in real-mode HTTP evaluation; no SDK or automatic accuracy claims."""

import argparse
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.evaluation import inspect_events, parse_sse, summarize  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("E2E_BASE_URL", "http://localhost:8080"))
    parser.add_argument("--cases", type=Path, default=ROOT / "samples/questions.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--email", default="student@example.test")
    parser.add_argument("--origin", default=os.environ.get("PUBLIC_ORIGIN"))
    args = parser.parse_args()
    base = args.base_url.rstrip("/") + "/api/v1"
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path, body=None):
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        return opener.open(
            urllib.request.Request(
                base + path,
                data=data,
                headers={"Content-Type": "application/json", "Origin": (args.origin or args.base_url).rstrip("/")},
            ),
            timeout=300,
        )

    with request("/system") as response:
        system = json.load(response)
    if system["model_mode"] != "real":
        raise SystemExit("MODEL_MODE=real required; Mock evaluation rejected before login")
    password = os.environ.get("EVAL_PASSWORD") or os.environ.get("DEMO_STUDENT_PASSWORD")
    if not password:
        raise SystemExit(
            "Set EVAL_PASSWORD to the student's actual password; existing DB credentials may differ from .env"
        )
    cases = json.loads(args.cases.read_text(encoding="utf8"))
    if not isinstance(cases, list) or not cases or len({case["id"] for case in cases}) != len(cases):
        raise SystemExit("Cases must be a nonempty list with unique IDs")
    if any(not isinstance(case.get("answerable"), bool) or not case.get("question") for case in cases):
        raise SystemExit("Each case requires a question and boolean answerable expectation")
    with request("/auth/login", {"email": args.email, "password": password}) as response:
        json.load(response)
    stamp = datetime.now(UTC)
    output = args.output or ROOT / "work/evaluations" / ("real-" + stamp.strftime("%Y%m%dT%H%M%SZ") + ".json")
    report = {
        "schema_version": 1,
        "started_at": stamp.isoformat(),
        "model_mode": "real",
        "system": system,
        "results": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        report["summary"] = summarize(report["results"])
        report["measured_accuracy"] = None
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
        temporary.replace(output)

    for case in cases:
        started = time.monotonic()
        result = {"case": case, "status": "http_failure", "events": []}
        try:
            with request("/conversations", {}) as response:
                conversation = json.load(response)
            result["conversation_id"] = conversation["id"]
            with request(
                "/conversations/" + conversation["id"] + "/messages", {"content": case["question"]}
            ) as response:
                if response.headers.get_content_type() != "text/event-stream":
                    raise ValueError("Unexpected response type")
                result["events"] = list(parse_sse(response))
            result.update(inspect_events(case, result["events"]))
            if result["status"] == "complete":
                checks = []
                for citation in result["answer"]["citations"]:
                    try:
                        with request("/sources/" + citation["chunk_id"]) as response:
                            source = json.load(response)
                        checks.append(
                            {
                                "chunk_id": citation["chunk_id"],
                                "accessible": True,
                                "version_matches": source["version_id"] == citation["version_id"],
                                "source": source,
                            }
                        )
                    except urllib.error.HTTPError as exc:
                        checks.append(
                            {"chunk_id": citation["chunk_id"], "accessible": False, "http_status": exc.code}
                        )
                result["citation_checks"] = checks
                result["citations_verified"] = all(
                    check.get("accessible") and check.get("version_matches") for check in checks
                )
        except urllib.error.HTTPError as exc:
            result.update(status="http_failure", http_status=exc.code)
        except (urllib.error.URLError, TimeoutError):
            result.update(status="network_failure")
        except (ValueError, KeyError, TypeError):
            result.update(status="protocol_failure", code="INVALID_RESPONSE")
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        report["results"].append(result)
        save()
        print(case["id"], result["status"])
    report["completed_at"] = datetime.now(UTC).isoformat()
    save()
    print(
        "Recorded:",
        output,
        "— expectation checks are not human answer accuracy; usage remains in request_traces.",
    )
    raise SystemExit(1 if report["summary"]["failures"] or report["summary"]["expectation_failures"] else 0)


if __name__ == "__main__":
    main()
