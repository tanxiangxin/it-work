"""Compare vector and hybrid retrieval without chat calls or configuration changes."""

import argparse
import hashlib
import http.cookiejar
import json
import os
import statistics
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.retrieval_evaluation import ranking_metrics, summarize_comparison, validate_cases  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--email", default="student@example.test")
    parser.add_argument("--cases", type=Path, default=ROOT / "samples/retrieval-questions.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 10:
        parser.error("repetitions must be 1..10")
    raw_cases = args.cases.read_bytes()
    cases = validate_cases(json.loads(raw_cases.decode("utf-8")))
    password = os.environ.get("EVAL_PASSWORD") or os.environ.get("DEMO_STUDENT_PASSWORD")
    if not password:
        raise SystemExit("Set EVAL_PASSWORD to the student's actual password locally")
    base = args.base_url.rstrip("/") + "/api/v1"
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path, body=None):
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        with opener.open(
            urllib.request.Request(
                base + path,
                data=data,
                headers={"Content-Type": "application/json", "Origin": args.base_url.rstrip("/")},
            ),
            timeout=180,
        ) as response:
            return json.load(response)

    system = request("/system")
    if system["model_mode"] != "real":
        raise SystemExit("Real mode required; Mock results cannot be used as real retrieval quality")
    user = request("/auth/login", {"email": args.email, "password": password})
    if user["role"] != "student":
        request("/auth/logout", {})
        raise SystemExit("Use a student account to measure student retrieval permissions")
    stamp = datetime.now(UTC)
    output = args.output or ROOT / "work/evaluations" / (
        "retrieval-" + stamp.strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1,
        "status": "running",
        "started_at": stamp.isoformat(),
        "system": system,
        "dataset_sha256": hashlib.sha256(raw_cases).hexdigest(),
        "planned_cases": len(cases),
        "repetitions": args.repetitions,
        "warmup_requests": 1,
        "results": [],
    }

    def save():
        report["summary"] = summarize_comparison(report["results"])
        report["groups"] = {
            group: summarize_comparison(
                [item for item in report["results"] if item["case"].get("group", "other") == group]
            )
            for group in sorted({item["case"].get("group", "other") for item in report["results"]})
        }
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
        temporary.replace(output)

    try:
        warmup = request("/retrieval/compare", {"content": cases[0]["question"]})
        if warmup["model_mode"] != "real" or warmup["index_key"] != system["index_key"]:
            raise ValueError("MODEL_CHANGED")
        report["corpus"] = warmup["corpus"]
        report["generation"] = warmup["generation"]
        report["embedding_revision"] = warmup["embedding_revision"]
        report["parameters"] = warmup["parameters"]
        signature = (warmup["index_key"], warmup["generation"], warmup["corpus"])
        present = {doc["document_name"] for doc in warmup["corpus"]}
        required = {name for case in cases for name in case.get("relevant_documents", [])}
        if not required <= present:
            report["status"] = "missing_corpus"
            report["missing_documents"] = sorted(required - present)
            save()
            raise SystemExit("Relevant documents are missing from the published student corpus")
        for index, case in enumerate(cases):
            result = {"case": case, "status": "failed", "runs": []}
            try:
                for repetition in range(args.repetitions):
                    run = request(
                        "/retrieval/compare",
                        {
                            "content": case["question"],
                            "first_mode": "vector" if (index + repetition) % 2 == 0 else "hybrid",
                        },
                    )
                    if (
                        run["model_mode"] != "real"
                        or run["role"] != "student"
                        or (run["index_key"], run["generation"], run["corpus"]) != signature
                    ):
                        raise ValueError("CORPUS_CHANGED")
                    if any(len(sources) > 5 for sources in run["results"].values()):
                        raise ValueError("INVALID_RESULTS")
                    result["runs"].append(run)
                runs = result["runs"]
                # Keep every repetition; score the first ranking and flag any variation.
                result.update(
                    status="complete",
                    metrics={
                        mode: ranking_metrics(case, runs[0]["results"][mode]) for mode in ("vector", "hybrid")
                    },
                    embedding_ms=statistics.median(run["embedding_ms"] for run in runs),
                    retrieval_ms={
                        mode: statistics.median(run["retrieval_ms"][mode] for run in runs)
                        for mode in ("vector", "hybrid")
                    },
                    stable_rankings=all(run["results"] == runs[0]["results"] for run in runs),
                )
            except urllib.error.HTTPError as error:
                result["code"] = "HTTP_" + str(error.code)
            except (OSError, ValueError, KeyError, TypeError):
                result["code"] = "NETWORK_OR_PROTOCOL_ERROR"
            report["results"].append(result)
            save()
            print(case["id"], result["status"], flush=True)
            if result["status"] != "complete":
                # Do not mix observations from a changed knowledge base with earlier cases.
                report["status"] = "incomplete"
                break
        if report["status"] == "running":
            report["status"] = "complete"
        save()
    except (urllib.error.URLError, ValueError, KeyError, TypeError):
        report["status"] = "preflight_failed"
        save()
    finally:
        try:
            request("/auth/logout", {})
        except (OSError, ValueError):
            pass
    print("Recorded:", output)
    isolation_failures = any(mode["forbidden_hit_cases"] for mode in report["summary"]["modes"].values())
    raise SystemExit(0 if report["status"] == "complete" and not isolation_failures else 1)


if __name__ == "__main__":
    main()
