import hashlib
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.errors import AppError


class LocalStorage:
    def path(self, key):
        root = settings().storage_dir.resolve()
        path = (root / key).resolve()
        if path.parent != root:
            raise AppError("INVALID_STORAGE_KEY", "无效文件路径")
        return path

    async def save(self, upload):
        filename = Path((upload.filename or "file").replace("\\", "/")).name[:255]
        if Path(filename).suffix.lower() not in {".md", ".txt", ".pdf", ".docx"}:
            raise AppError("UNSUPPORTED_FILE", "只支持 MD、TXT、DOCX、PDF")
        key = str(uuid4()) + Path(filename).suffix.lower()
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha256(), 0
        try:
            with path.open("wb") as f:
                while data := await upload.read(65536):
                    size += len(data)
                    if size > settings().max_upload_bytes:
                        raise AppError("FILE_TOO_LARGE", "文件超过 20 MB", 413)
                    digest.update(data)
                    f.write(data)
            if not size:
                raise AppError("EMPTY_DOCUMENT", "文件为空")
            return filename, key, digest.hexdigest()
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def remove(self, key):
        self.path(key).unlink(missing_ok=True)


storage = LocalStorage()
