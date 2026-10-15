"""Snapshot/verify database row counts and hashes of all stored files. Run with writers stopped."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, '/app')

from sqlalchemy import func, select

from app.db import session
from app.models import Base


def snapshot():
    with session() as db:
        tables = {table.name: db.scalar(select(func.count()).select_from(table))
                  for table in Base.metadata.sorted_tables}
    root = Path('/data/files')
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_file():
            with path.open('rb') as source:
                files[str(path.relative_to(root))] = hashlib.file_digest(source, 'sha256').hexdigest()
    return {'schema_version': 1, 'tables': tables, 'files': files}


if __name__ == '__main__':
    path = Path('/backup/manifest.json')
    current = snapshot()
    if sys.argv[1] == 'snapshot':
        path.write_text(json.dumps(current, indent=2), encoding='utf8')
        print(f"Snapshot: {len(current['tables'])} tables, {len(current['files'])} files")
    else:
        expected = json.loads(path.read_text(encoding='utf8'))
        if current != expected:
            raise SystemExit('Restore verification failed: database counts or file hashes differ')
        print(f"Restore verified: {len(current['tables'])} table counts and all {len(current['files'])} file hashes match")
