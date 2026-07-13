"""Factory FastAPI da estratégia de retrieval ativa."""

from app.retrieval.base import Retriever
from app.retrieval.lexical import PostgresLexicalRetriever


def get_retriever() -> Retriever:
    """Retorna a baseline ativa sem acoplar rota/service à sua classe."""
    return PostgresLexicalRetriever()
