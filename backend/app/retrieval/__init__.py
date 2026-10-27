"""Contratos e implementação da recuperação de evidências documentais.

Os contratos (:mod:`app.retrieval.base`) não dependem da configuração da
aplicação nem da base de dados. A implementação lexical e a sua factory são
carregadas só quando pedidas: importar os contratos — por exemplo, na reanálise
offline de uma avaliação arquivada — não carrega ``app.core.config``. Os nomes
públicos do pacote e o comportamento da recuperação não mudam.
"""

from typing import TYPE_CHECKING, Any

from app.retrieval.base import Evidence, RetrievalContext, Retriever

if TYPE_CHECKING:
    from app.retrieval.dependencies import get_retriever
    from app.retrieval.lexical import PostgresLexicalRetriever

__all__ = [
    "Evidence",
    "PostgresLexicalRetriever",
    "RetrievalContext",
    "Retriever",
    "get_retriever",
]


def __getattr__(name: str) -> Any:
    if name == "get_retriever":
        from app.retrieval.dependencies import get_retriever

        return get_retriever
    if name == "PostgresLexicalRetriever":
        from app.retrieval.lexical import PostgresLexicalRetriever

        return PostgresLexicalRetriever
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
