import asyncio
import hashlib
import os
import shutil
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db import session
from app.jobs import process_import
from app.models import Document, DocumentVersion, ImportJob, User
from app.security import passwords
from app.storage import storage


def seed():
    cfg = settings()
    if not cfg.demo_student_password or not cfg.demo_admin_password:
        raise SystemExit("Set DEMO_STUDENT_PASSWORD and DEMO_ADMIN_PASSWORD before seeding")
    with session() as db:
        for email, name, role, password in [
            ("student@example.test", "演示学生", "student", cfg.demo_student_password),
            ("admin@example.test", "服务管理员", "admin", cfg.demo_admin_password),
        ]:
            if not db.scalar(select(User).where(User.email == email)):
                db.add(User(email=email, name=name, role=role, password_hash=passwords.hash(password)))
        db.commit()
    print("Demo users initialized. Existing passwords are not overwritten.")


async def seed_documents():
    root = Path(__file__).absolute().parents[2] / "samples"
    if not root.exists():
        root = Path(os.environ.get("SAMPLES_DIR", "../samples"))
    for path in root.glob("*.md"):
        with session() as db:
            doc = db.scalar(select(Document).where(Document.name == path.name, Document.deleted.is_(False)))
            if doc:
                continue
            doc = Document(name=path.name, visibility="admin" if path.name.startswith("admin-") else "public")
            db.add(doc)
            db.flush()
            key = str(uuid.uuid4()) + ".md"
            target = storage.path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            version = DocumentVersion(
                document_id=doc.id,
                filename=path.name,
                storage_key=key,
                file_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
                index_key=settings().index_key,
            )
            db.add(version)
            db.flush()
            job = ImportJob(version_id=version.id)
            db.add(job)
            db.commit()
            job_id = job.id
        await process_import(job_id)
        print(f"Imported {path.name}")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m app.cli seed | seed-documents | run-job UUID | recover")
    if sys.argv[1] == "seed":
        seed()
    elif sys.argv[1] == "seed-documents":
        asyncio.run(seed_documents())
    elif sys.argv[1] == "run-job":
        asyncio.run(process_import(sys.argv[2]))
    elif sys.argv[1] == "recover":
        from app.jobs import recover

        recover()
    else:
        raise SystemExit("Unknown command")


if __name__ == "__main__":
    main()
