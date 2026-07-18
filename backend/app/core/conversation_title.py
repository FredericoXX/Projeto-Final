"""Título automático de conversas derivado da primeira pergunta.

Função pura, determinística e local: sem LLM, sem pedidos externos, sem
custo e sem latência de fornecedor. O título é a própria pergunta
original — preservando idioma, acentos e maiúsculas/minúsculas — apenas
com o whitespace normalizado, a pontuação final removida e um limite de
comprimento estável. Não é um resumo semântico.
"""

import re

MAX_TITLE_LENGTH = 80

_WHITESPACE_RE = re.compile(r"\s+")

# Pontuação final descartada (repetida ou combinada): "Quando começam as
# aulas?!?" -> "Quando começam as aulas". A pontuação interna mantém-se.
_TRAILING_PUNCTUATION = ".?!…"

_ELLIPSIS = "…"


def derive_conversation_title(question: str) -> str:
    """Deriva o título a partir da pergunta original.

    Regras: colapsa espaços/tabs/quebras num único espaço; remove espaços
    exteriores; remove pontuação final ("."/"?"/"!"/"…", mesmo repetida);
    limita a MAX_TITLE_LENGTH caracteres preferindo cortar no último
    espaço e terminando com "…" quando trunca. Nunca devolve título vazio
    para uma pergunta válida (uma pergunta composta só por pontuação
    mantém a própria pontuação como título).
    """
    collapsed = _WHITESPACE_RE.sub(" ", question).strip()
    stripped = collapsed.rstrip(_TRAILING_PUNCTUATION + " ")
    title = stripped or collapsed

    if len(title) <= MAX_TITLE_LENGTH:
        return title

    cut = title[: MAX_TITLE_LENGTH - len(_ELLIPSIS)]
    last_space = cut.rfind(" ")
    if last_space > 0:
        # Corte por palavra; uma palavra única maior do que o limite cai
        # no corte duro acima.
        cut = cut[:last_space]
    return cut.rstrip() + _ELLIPSIS
