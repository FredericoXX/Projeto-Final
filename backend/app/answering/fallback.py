"""Mensagens determinísticas de fallback por falta de evidências.

Sem tradução por LLM: as mensagens são fixas por idioma. Um idioma
suportado pela instituição mas sem mensagem própria usa o fallback
documentado (inglês) — nunca um erro 500.
"""

_FALLBACK_MESSAGES: dict[str, str] = {
    "pt": (
        "Não encontrei informação institucional suficiente para responder "
        "com segurança."
    ),
    "en": "I could not find sufficient institutional information to answer safely.",
}

# Idioma sem mensagem própria cai aqui (decisão documentada).
_DEFAULT_FALLBACK_LANGUAGE = "en"


def get_fallback_message(language: str) -> str:
    """Mensagem de fallback para o idioma resolvido.

    Procura primeiro o código completo (ex.: "pt-pt"), depois o subtag
    primário ("pt"); sem correspondência, usa a mensagem em inglês.
    """
    normalized = language.strip().lower()
    if normalized in _FALLBACK_MESSAGES:
        return _FALLBACK_MESSAGES[normalized]
    primary = normalized.split("-")[0]
    if primary in _FALLBACK_MESSAGES:
        return _FALLBACK_MESSAGES[primary]
    return _FALLBACK_MESSAGES[_DEFAULT_FALLBACK_LANGUAGE]
