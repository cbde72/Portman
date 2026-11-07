"""Sichere, inhaltsadressierte Originalablage für eingehende PDF-Bytes."""
from datetime import datetime
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from portman_v10.application.contracts import ApplicationError, Document, DocumentContent, DocumentUpload, ErrorCode
from portman_v10.infrastructure.sqlite_store import SQLiteStore


class DocumentStorage:
    def __init__(self, data_dir: str | Path, store: SQLiteStore):
        self.root = Path(data_dir).resolve()
        if store.path.resolve().parent != self.root:
            raise ValueError("SQLite-Datei und Dokumentablage müssen im selben verschiebbaren V10-Datenverzeichnis liegen")
        self.documents_dir = self.root / "documents"
        self.temporary_dir = self.documents_dir / ".incoming"
        self.store = store
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.temporary_dir.mkdir(parents=True, exist_ok=True)
        if self.documents_dir.is_symlink() or self.temporary_dir.is_symlink():
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "V10-Dokumentordner dürfen keine symbolischen Links sein")
        try:
            self.documents_dir.resolve().relative_to(self.root)
            self.temporary_dir.resolve().relative_to(self.documents_dir.resolve())
        except ValueError as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Dokumentablage verweist aus dem konfigurierten Datenverzeichnis heraus") from error

    def add(self, upload: DocumentUpload) -> tuple[Document, bool]:
        if len(upload.content) > 50 * 1024 * 1024:
            raise ApplicationError(ErrorCode.VALIDATION_ERROR, "PDF überschreitet die Uploadgrenze von 50 MiB")
        digest = sha256(upload.content).hexdigest()
        try:
            known = self.store.find_document_by_hash(digest)
        except (OSError, sqlite3.Error, ValueError) as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Dokumentmetadaten konnten nicht gelesen werden") from error
        if known is not None:
            return known, True
        shard = self.documents_dir / digest[:2]
        try:
            shard.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Interner Dokumentordner kann nicht angelegt werden") from error
        if shard.is_symlink():
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Interner Dokumentordner darf kein symbolischer Link sein")
        try:
            shard.resolve().relative_to(self.documents_dir.resolve())
        except ValueError as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Interner Dokumentordner liegt außerhalb der Ablage") from error
        final = shard / f"{digest}.pdf"
        if final.is_symlink():
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Interner Dokumentpfad darf kein symbolischer Link sein")
        temporary = self.temporary_dir / f"{uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(upload.content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, final)
            except FileExistsError:
                if sha256(final.read_bytes()).hexdigest() != digest:
                    raise ApplicationError(ErrorCode.STORAGE_ERROR, "Interner Dokumentpfad ist bereits mit anderem Inhalt belegt")
            relative = final.relative_to(self.root).as_posix()
            document, was_duplicate = self.store.register_document(
                document_id=uuid4().hex, digest=digest, name=_safe_display_name(upload.original_name),
                relative_path=relative, media_type="application/pdf", imported_at=datetime.now().astimezone().isoformat(),
            )
            # Bei gleichzeitigem Upload derselben Bytes bleibt die gemeinsame Zieldatei erhalten.
            return document, was_duplicate
        except ApplicationError:
            raise
        except (OSError, sqlite3.Error, ValueError) as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "PDF konnte nicht sicher abgelegt werden") from error
        finally:
            temporary.unlink(missing_ok=True)
            # Absichtlich keine Bereinigung von final: nach einem DB-Fehler kann
            # ein anderer gleichzeitiger Upload die Datei bereits registriert haben.

    def open(self, document_id: str) -> DocumentContent:
        metadata, candidate = self.internal_path(document_id)
        try:
            content = candidate.read_bytes()
        except OSError as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Dokumentdatei kann nicht geöffnet werden") from error
        if sha256(content).hexdigest() != metadata.sha256:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Dokumentinhalt stimmt nicht mit den gespeicherten Metadaten überein")
        return DocumentContent(metadata, content)

    def internal_path(self, document_id: str) -> tuple[Document, Path]:
        try:
            record = self.store.document_record(document_id)
        except (OSError, sqlite3.Error, ValueError) as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Dokumentmetadaten oder Ablagepfad sind ungültig") from error
        if record is None:
            raise ApplicationError(ErrorCode.NOT_FOUND, "Dokument nicht gefunden")
        metadata, relative = record
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.documents_dir.resolve())
        except ValueError as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Dokumentpfad liegt außerhalb der V10-Ablage") from error
        try:
            digest = sha256()
            with candidate.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as error:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Dokumentdatei kann nicht geöffnet werden") from error
        if digest.hexdigest() != metadata.sha256:
            raise ApplicationError(ErrorCode.STORAGE_ERROR, "Dokumentinhalt stimmt nicht mit den gespeicherten Metadaten überein")
        return metadata, candidate

    def cleanup_temporary(self) -> int:
        """Löscht ausschließlich eigene, unvollständige *.tmp-Dateien."""
        removed = 0
        for path in self.temporary_dir.glob("[0-9a-f]*.tmp"):
            if path.is_file() and path.parent.resolve() == self.temporary_dir.resolve():
                path.unlink()
                removed += 1
        return removed


def _safe_display_name(name: str) -> str:
    leaf = name.replace("\\", "/").rsplit("/", 1)[-1]
    leaf = "".join(char for char in leaf if char >= " " and char != "\x7f").strip()
    if not leaf or leaf in {".", ".."}:
        return "dokument.pdf"
    return leaf[:240]
