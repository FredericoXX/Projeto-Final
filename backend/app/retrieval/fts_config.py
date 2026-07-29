"""Seleção fechada (allowlist) da configuração PostgreSQL Full-Text Search.

O idioma resolvido do pedido nunca é usado diretamente como nome de
configuração SQL: é traduzido por esta função pura numa das três
configurações fixas e conhecidas. Isto garante que nenhum ``regconfig``
arbitrário — muito menos input do utilizador — chega ao PostgreSQL, e que
a configuração usada no ``search_vector`` (coluna gerada) e na
``websearch_to_tsquery`` da consulta é sempre a mesma para o mesmo idioma.

A correspondência é feita pela subtag primária do código de idioma
(``pt-pt``/``pt-br`` -> ``pt``; ``en-gb``/``en-us`` -> ``en``), coerente
com ``normalize_language_code`` e com a lista de termos funcionais do
planeador de consultas. Idiomas sem configuração linguística suportada
usam ``simple`` (sem stemming nem stopwords).
"""

from enum import StrEnum


class FtsConfiguration(StrEnum):
    """Configurações PostgreSQL FTS permitidas.

    O valor é literalmente o nome ``regconfig`` usado no SQL. Como o
    conjunto é fechado e definido só no código, o valor pode ser usado
    com segurança como parâmetro de ``websearch_to_tsquery`` sem risco de
    injeção.
    """

    PORTUGUESE = "portuguese"
    ENGLISH = "english"
    SIMPLE = "simple"


def _primary_subtag(language: str) -> str:
    """Subtag primária normalizada: ``"PT_pt"`` -> ``"pt"``.

    Reproduz o formato de ``normalize_language_code`` (trim, minúsculas,
    ``_`` -> ``-``) sem validar o comprimento: aqui só interessa escolher
    uma configuração, e um valor inesperado recai em ``simple``.
    """
    return language.strip().lower().replace("_", "-").split("-", 1)[0]


def resolve_fts_config(language: str) -> FtsConfiguration:
    """Configuração FTS para um código de idioma, por allowlist.

    - subtag primária ``pt`` (``pt``, ``pt-pt``, ``pt-br``...): ``portuguese``;
    - subtag primária ``en`` (``en``, ``en-gb``, ``en-us``...): ``english``;
    - qualquer outro idioma: ``simple``.
    """
    primary = _primary_subtag(language)
    if primary == "pt":
        return FtsConfiguration.PORTUGUESE
    if primary == "en":
        return FtsConfiguration.ENGLISH
    return FtsConfiguration.SIMPLE
