"""Generate a local mock configuration once, without printing passwords."""
from pathlib import Path
import secrets

root=Path(__file__).resolve().parents[1]
target=root/'.env'
if target.exists():
    raise SystemExit('.env already exists; it was not overwritten')
content=(root/'.env.example').read_text(encoding='utf8')
content=content.replace('replace-with-a-random-db-password',secrets.token_urlsafe(24))
content=content.replace('replace-with-a-student-password',secrets.token_urlsafe(18))
content=content.replace('replace-with-an-admin-password',secrets.token_urlsafe(18))
with target.open('x',encoding='utf8') as output: output.write(content)
print('Created .env with random local demo passwords. Read the file locally; do not commit it.')
