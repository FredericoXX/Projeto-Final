"""Normalização determinística de texto para pesquisa lexical.

Produz o normalized_content guardado em document_chunks: uma forma
canónica, previsível e independente de fornecedor, pensada para
comparações e pesquisa lexical. O content original nunca é
alterado — a normalização é sempre uma cópia derivada.

Regras aplicadas, por ordem:

1. normalização Unicode NFKD (formas compostas e de compatibilidade
   passam a uma representação única);
2. remoção dos diacríticos (marcas combinantes), para que "Matrícula" e
   "matricula" normalizem para o mesmo valor nas pesquisas;
3. casefold (minúsculas, mais agressivo do que lower() para Unicode);
4. colapso de qualquer sequência de espaços, tabs e quebras de linha num
   único espaço;
5. remoção de espaços no início e no fim.
"""

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Devolve a forma normalizada e determinística de ``text``.

    Exemplo: ``"  Matrícula   e\\nInscrição  "`` -> ``"matricula e inscricao"``.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    lowered = without_marks.casefold()
    return _WHITESPACE_RE.sub(" ", lowered).strip()
