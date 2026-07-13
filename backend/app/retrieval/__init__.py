"""Contratos e implementação da recuperação de evidências documentais."""

from app.retrieval.base import Evidence, RetrievalContext, Retriever
from app.retrieval.dependencies import get_retriever
from app.retrieval.lexical import PostgresLexicalRetriever

__all__ = [
    "Evidence",
    "PostgresLexicalRetriever",
    "RetrievalContext",
    "Retriever",
    "get_retriever",
]
