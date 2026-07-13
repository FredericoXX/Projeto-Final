"""Interface do armazenamento de documentos.

Os services dependem deste Protocol, não de uma implementação concreta,
para que o armazenamento local possa ser substituído no futuro (ex.: S3)
sem alterar a lógica de negócio. Todos os caminhos aceites e devolvidos
são relativos ao root do armazenamento — caminhos absolutos nunca saem
desta camada nem entram na base de dados.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO, Protocol


class DocumentStorage(Protocol):
    def save_temp(self, chunks: Iterable[bytes]) -> str:
        """Escreve os blocos num ficheiro temporário dentro do root e
        devolve o seu caminho relativo. Se o iterável levantar uma
        exceção a meio, o ficheiro parcial é removido antes de propagar."""
        ...

    def move_to_final(self, temp_path: str, final_path: str) -> None:
        """Move atomicamente o temporário para o caminho final relativo,
        criando os diretórios intermédios necessários."""
        ...

    def open(self, path: str) -> BinaryIO:
        """Abre o ficheiro relativo para leitura binária."""
        ...

    def delete(self, path: str) -> None:
        """Remove o ficheiro relativo, ignorando-o se já não existir."""
        ...

    def exists(self, path: str) -> bool:
        """Indica se o ficheiro relativo existe no armazenamento."""
        ...

    def resolve_path(self, path: str) -> Path:
        """Converte um caminho relativo no caminho absoluto correspondente,
        garantindo que nunca sai do root (proteção contra path traversal)."""
        ...
