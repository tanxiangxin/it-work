"""Prepare curated HUT documents and import through the authenticated document API."""

import argparse
import hashlib
import http.cookiejar
import json
import os
import time
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf8"))
    seen = set()
    for item in manifest["documents"]:
        name = item["file"]
        if (
            Path(name).name != name
            or not name.startswith("hut-")
            or not name.endswith(".md")
            or name in seen
        ):
            raise ValueError("Invalid or duplicate document filename")
        seen.add(name)
        text = (
            f"# {item['title']}\n\n"
            f"学校：{manifest['school']}；领域：{item['category']}。\n"
            f"采集核验日期：{manifest['checked_on']}；原文发布日：{item['published_on'] or '页面未标注'}。\n"
            "来源类型：官方公开资料摘要。核验日期不代表政策生效日期，办理时以最新官方通知为准。\n"
            + "\n".join("原文来源：" + url for url in item["sources"])
            + "\n\n"
            + item["body"]
            + "\n"
        )
        # Every chunk must retain source/date context; keep each curated topic within one chunk.
        if len(text) > 950:
            raise ValueError(
                f"Document too long to preserve source context in one chunk: {name}"
            )
        (directory / name).write_text(text, encoding="utf8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "samples/hut")
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--email", default="admin@example.test")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--hide-demo",
        action="store_true",
        help="Make the three original demo guides admin-only",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs/evaluations/20261010-hut-import.json",
    )
    args = parser.parse_args()
    manifest = prepare(args.directory)
    if args.prepare_only:
        print("Prepared", len(manifest["documents"]), "documents")
        return
    password = os.environ.get("EVAL_ADMIN_PASSWORD") or os.environ.get(
        "DEMO_ADMIN_PASSWORD"
    )
    if not password:
        raise SystemExit(
            "Set EVAL_ADMIN_PASSWORD to the existing admin account password"
        )
    origin = args.base_url.rstrip("/")
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )

    def request(path, body=None, method=None, content_type="application/json"):
        data = (
            body
            if isinstance(body, bytes)
            else json.dumps(body).encode()
            if body is not None
            else None
        )
        with opener.open(
            urllib.request.Request(
                origin + "/api/v1" + path,
                data=data,
                method=method,
                headers={"Content-Type": content_type, "Origin": origin},
            ),
            timeout=45,
        ) as r:
            return json.load(r)

    report = {
        "school": manifest["school"],
        "checked_on": manifest["checked_on"],
        "started_at": datetime.now(UTC).isoformat(),
        "documents": [],
        "demo_visibility_changes": [],
    }

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
        )
        temporary.replace(args.output)

    user = request("/auth/login", {"email": args.email, "password": password})
    try:
        if user["role"] != "admin":
            raise ValueError("Administrator required")
        documents = []
        page = 1
        while True:
            batch = request(f"/documents?page={page}&page_size=100")
            documents.extend(batch["items"])
            if len(documents) >= batch["total"]:
                break
            page += 1
        for item in manifest["documents"]:
            name = item["file"]
            data = (args.directory / name).read_bytes()
            record = {
                "file": name,
                "sources": item["sources"],
                "sha256": hashlib.sha256(data).hexdigest(),
                "status": "pending",
            }
            report["documents"].append(record)
            save()
            matches = [doc for doc in documents if doc["name"] == name]
            if len(matches) > 1:
                raise ValueError("Multiple documents share the curated filename")
            existing = matches[0] if matches else None
            boundary = uuid.uuid4().hex
            multipart = (
                (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="visibility"\r\n\r\npublic\r\n'
                    f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                    "Content-Type: text/markdown; charset=utf-8\r\n\r\n"
                ).encode()
                + data
                + f"\r\n--{boundary}--\r\n".encode()
            )
            path = f"/documents/{existing['id']}/versions" if existing else "/documents"
            job = request(
                path,
                multipart,
                content_type="multipart/form-data; boundary=" + boundary,
            )
            record.update(job)
            until = time.monotonic() + 180
            while True:
                state = request("/jobs/" + job["job_id"])
                if state["status"] in {"ready", "failed"}:
                    break
                if time.monotonic() > until:
                    raise TimeoutError(
                        "Import job did not finish; inspect recorded job ID"
                    )
                time.sleep(1)
            record.update(status=state["status"], error=state.get("error"))
            if state["status"] != "ready":
                save()
                raise RuntimeError(
                    "Import failed; see report and retry through admin interface"
                )
            detail = request("/documents/" + job["document_id"])
            if detail["active_version_id"] != job["version_id"]:
                raise RuntimeError("Imported version was not published")
            if detail["visibility"] != "public":
                request(
                    f"/documents/{detail['id']}/visibility",
                    {"visibility": "public"},
                    method="PATCH",
                )
            record["chunks"] = len(detail["chunks"])
            save()
            print(name, "ready", record["chunks"], "chunks", flush=True)
        if args.hide_demo:
            for doc in documents:
                if (
                    doc["name"] in {"accounts.md", "campus-network.md", "vpn-809.md"}
                    and doc["visibility"] == "public"
                ):
                    request(
                        f"/documents/{doc['id']}/visibility",
                        {"visibility": "admin"},
                        method="PATCH",
                    )
                    report["demo_visibility_changes"].append(
                        {
                            "document_id": doc["id"],
                            "name": doc["name"],
                            "before": "public",
                            "after": "admin",
                        }
                    )
        report["completed_at"] = datetime.now(UTC).isoformat()
        save()
        print("Published", len(report["documents"]), "official-source documents")
    finally:
        request("/auth/logout", {}, method="POST")


if __name__ == "__main__":
    main()
