"""Camada de armazenamento de ficheiros de documentos."""

from app.core.config import settings
from app.storage.base import DocumentStorage
from app.storage.local import LocalDocumentStorage, StoragePathError

__all__ = ["DocumentStorage", "LocalDocumentStorage", "StoragePathError", "get_document_storage"]


def get_document_storage() -> DocumentStorage:
    """Dependency do FastAPI (e factory para services/testes): lê o root nas
    settings a cada chamada, para que os testes possam redirecionar o
    armazenamento para um diretório temporário via monkeypatch."""
    return LocalDocumentStorage(settings.resolved_document_storage_path)
