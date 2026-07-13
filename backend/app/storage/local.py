"""Implementação local (sistema de ficheiros) do DocumentStorage.

Estrutura em disco, sempre debaixo do root configurado:

    {root}/tmp/{uuid}.part                          — uploads em curso
    {root}/{institution_id}/{document_id}/{version_id}/source.<ext>

Nenhum nome fornecido pelo utilizador entra na construção de caminhos;
o original_filename é apenas metadado guardado na base de dados.
"""

import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO

_TEMP_DIR = "tmp"


class StoragePathError(Exception):
    """Caminho relativo inválido: tentaria sair do root do armazenamento."""


class LocalDocumentStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def resolve_path(self, path: str) -> Path:
        # Resolve e valida que o resultado continua dentro do root: um
        # caminho com ".." (ou absoluto) é rejeitado antes de tocar no disco.
        candidate = (self._root / path).resolve()
        if not candidate.is_relative_to(self._root):
            msg = "storage path escapes the storage root"
            raise StoragePathError(msg)
        return candidate

    def save_temp(self, chunks: Iterable[bytes]) -> str:
        relative = f"{_TEMP_DIR}/{uuid.uuid4().hex}.part"
        target = self.resolve_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("wb") as handle:
                for chunk in chunks:
                    handle.write(chunk)
        except BaseException:
            # O produtor dos blocos pode falhar a meio (ex.: limite de
            # tamanho excedido); o ficheiro parcial nunca deve sobrar.
            target.unlink(missing_ok=True)
            raise
        return relative

    def move_to_final(self, temp_path: str, final_path: str) -> None:
        source = self.resolve_path(temp_path)
        target = self.resolve_path(final_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # os.replace por baixo: atómico dentro do mesmo sistema de ficheiros,
        # que é garantido porque ambos os caminhos vivem debaixo do root.
        source.replace(target)

    def open(self, path: str) -> BinaryIO:
        return self.resolve_path(path).open("rb")

    def delete(self, path: str) -> None:
        self.resolve_path(path).unlink(missing_ok=True)

    def exists(self, path: str) -> bool:
        return self.resolve_path(path).is_file()
