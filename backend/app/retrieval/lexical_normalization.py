"""Normalização lexical tipada para o reranking determinístico.

Esta camada é distinta de ``app.core.text_normalization``: a
``normalize_text`` continua a ser a normalização genérica (NFKD, remoção
de diacríticos, casefold, colapso de espaços) que produz o
``normalized_content`` persistido. Aqui recebe-se texto **já normalizado**
por essa função e produz-se uma representação lexical rica, usada apenas
pelo ranking — nunca altera texto persistido, a pergunta original nem o
conteúdo apresentado ao utilizador.

A representação reconhece, de forma conservadora e determinística:

- palavras e números (tokens de conteúdo);
- ordinais padrão com indicador (``1o``, ``1.o``, ``1a``, ``2.a``...) e
  ordinais escritos por idioma (``primeiro``..``decimo``, ``first``..
  ``tenth``), reduzidos a uma forma canónica ``ord:N`` interna;
- intervalos numéricos **explícitos** (``01 a 12``, ``01-12``, ``01–12``,
  ``01a12``), com um separador textual/hífen inequívoco.

Regras deliberadamente restritivas (ver Momento 4, secções 15–16):

- um cardinal isolado **nunca** é convertido em ordinal (``12`` não é
  ``ord:1``; ``22`` não é ``ord:2``);
- uma sequência apenas numérica sem separador **nunca** é dividida em
  intervalo (``0509``, ``2206``, ``20262027`` permanecem um único token);
- não há interpretação de datas, preenchimento de zeros nem validação de
  calendário; ``Ro`` e afins continuam palavras, sem virar número.

Sem SQL, sem rede, sem LLM, sem dependências pesadas. Determinística por
construção: a mesma entrada produz sempre a mesma representação.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

# Ordinais escritos, na forma normalizada (sem acentos, minúsculas). As
# listas são pequenas, explícitas e por idioma; cobrem primeiro..décimo e
# first..tenth, nas formas masculina/feminina do português.
_WRITTEN_ORDINALS_PT: dict[str, int] = {
    "primeiro": 1, "primeira": 1,
    "segundo": 2, "segunda": 2,
    "terceiro": 3, "terceira": 3,
    "quarto": 4, "quarta": 4,
    "quinto": 5, "quinta": 5,
    "sexto": 6, "sexta": 6,
    "setimo": 7, "setima": 7,
    "oitavo": 8, "oitava": 8,
    "nono": 9, "nona": 9,
    "decimo": 10, "decima": 10,
}
_WRITTEN_ORDINALS_EN: dict[str, int] = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}

# Separadores de intervalo inequívocos: a preposição "a", hífen, travessão
# e meia-risca. A barra "/" e a ausência de separador nunca formam
# intervalo.
_RANGE_RE = re.compile(r"(\d+)\s*(?:a|-|–|—)\s*(\d+)")

# Ordinal numérico português: dígitos, ponto opcional e o indicador o/a
# (que a normalização já produziu a partir de º/ª), sem mais letras ou
# dígitos a seguir. Cobre 1o, 1.o, 1a, 1.a, 2.o, 2a...
_ORDINAL_NUM_PT_RE = re.compile(r"(\d+)\.?([oa])(?![a-z0-9])")

# Ordinal numérico inglês: 1st, 2nd, 3rd, 4th...
_ORDINAL_NUM_EN_RE = re.compile(r"(\d+)(?:st|nd|rd|th)(?![a-z0-9])")

# Token de palavra/número: sequência sem pontuação nem underscore.
_WORD_RE = re.compile(r"[^\W_]+")
_DIGITS_RE = re.compile(r"\d+")


class TokenKind(StrEnum):
    WORD = "word"
    NUMBER = "number"
    ORDINAL = "ordinal"
    RANGE_ENDPOINT = "range_endpoint"


@dataclass(frozen=True)
class CanonicalOrdinal:
    """Ordinal reconhecido e a sua forma canónica interna ``ord:N``."""

    value: int
    position: int

    @property
    def canonical(self) -> str:
        return f"ord:{self.value}"


@dataclass(frozen=True)
class NumericRange:
    """Intervalo numérico explícito reconhecido (endpoints como inteiros)."""

    start: int
    end: int
    position: int

    @property
    def canonical(self) -> str:
        low, high = sorted((self.start, self.end))
        return f"rng:{low}-{high}"


@dataclass(frozen=True)
class LexicalToken:
    """Um token normalizado e a sua forma canónica para comparação.

    - ``surface``: o token tal como aparece no texto normalizado;
    - ``canonical``: a forma usada na comparação de cobertura (igual ao
      ``surface`` para palavras/números; ``ord:N`` para ordinais);
    - ``position``: índice do token na sequência (0-based), para
      proximidade e ordem;
    - ``ordinal``: valor do ordinal quando aplicável, senão ``None``.
    """

    surface: str
    canonical: str
    position: int
    kind: TokenKind
    ordinal: int | None = None


@dataclass(frozen=True)
class LexicalRepresentation:
    """Representação lexical completa de um texto normalizado."""

    tokens: tuple[LexicalToken, ...]
    ranges: tuple[NumericRange, ...]

    @property
    def canonical_tokens(self) -> tuple[str, ...]:
        """Formas canónicas por ordem de ocorrência."""
        return tuple(token.canonical for token in self.tokens)

    def canonical_set(self) -> frozenset[str]:
        """Conjunto de formas canónicas, incluindo marcadores de intervalo."""
        values = {token.canonical for token in self.tokens}
        values.update(numeric_range.canonical for numeric_range in self.ranges)
        return frozenset(values)

    def first_positions(self) -> dict[str, int]:
        """Primeira posição de cada forma canónica (para proximidade/ordem)."""
        positions: dict[str, int] = {}
        for token in self.tokens:
            positions.setdefault(token.canonical, token.position)
        return positions


def _ordinal_family(language: str) -> str | None:
    """Família de ordinais a aplicar: ``"pt"``, ``"en"`` ou ``None``.

    Idiomas sem regras próprias não recebem canonização de ordinais (mas
    continuam a reconhecer palavras, números e intervalos).
    """
    primary = language.strip().lower().replace("_", "-").split("-", 1)[0]
    if primary == "pt":
        return "pt"
    if primary == "en":
        return "en"
    return None


def _match_range(text: str, pos: int) -> re.Match[str] | None:
    match = _RANGE_RE.match(text, pos)
    return match if match is not None else None


def _match_numeric_ordinal(
    text: str, pos: int, family: str | None
) -> tuple[re.Match[str], int] | None:
    if family == "pt":
        match = _ORDINAL_NUM_PT_RE.match(text, pos)
        if match is not None:
            return match, int(match.group(1))
    elif family == "en":
        match = _ORDINAL_NUM_EN_RE.match(text, pos)
        if match is not None:
            return match, int(match.group(1))
    return None


def build_lexical_representation(
    normalized_text: str, language: str
) -> LexicalRepresentation:
    """Constrói a representação lexical de um texto **já normalizado**.

    A varredura é da esquerda para a direita e determinística. Em cada
    posição de token tenta, por prioridade: intervalo explícito, ordinal
    numérico, e por fim palavra/número (com possível ordinal escrito).
    """
    family = _ordinal_family(language)
    written = (
        _WRITTEN_ORDINALS_PT
        if family == "pt"
        else _WRITTEN_ORDINALS_EN
        if family == "en"
        else {}
    )
    tokens: list[LexicalToken] = []
    ranges: list[NumericRange] = []
    position = 0
    index = 0
    length = len(normalized_text)
    while index < length:
        char = normalized_text[index]
        # Salta separadores/pontuação até ao início do próximo token.
        if not (char.isalnum()):
            index += 1
            continue

        range_match = _match_range(normalized_text, index)
        if range_match is not None:
            start_value = int(range_match.group(1))
            end_value = int(range_match.group(2))
            ranges.append(NumericRange(start_value, end_value, position))
            for endpoint in (range_match.group(1), range_match.group(2)):
                tokens.append(
                    LexicalToken(
                        surface=endpoint,
                        canonical=endpoint,
                        position=position,
                        kind=TokenKind.RANGE_ENDPOINT,
                    )
                )
                position += 1
            index = range_match.end()
            continue

        numeric_ordinal = _match_numeric_ordinal(normalized_text, index, family)
        if numeric_ordinal is not None:
            match, value = numeric_ordinal
            tokens.append(
                LexicalToken(
                    surface=match.group(0),
                    canonical=f"ord:{value}",
                    position=position,
                    kind=TokenKind.ORDINAL,
                    ordinal=value,
                )
            )
            position += 1
            index = match.end()
            continue

        word_match = _WORD_RE.match(normalized_text, index)
        if word_match is None:  # pragma: no cover - defensivo; isalnum já garante match
            index += 1
            continue
        surface = word_match.group(0)
        index = word_match.end()
        if surface in written:
            value = written[surface]
            tokens.append(
                LexicalToken(
                    surface=surface,
                    canonical=f"ord:{value}",
                    position=position,
                    kind=TokenKind.ORDINAL,
                    ordinal=value,
                )
            )
        elif _DIGITS_RE.fullmatch(surface):
            tokens.append(
                LexicalToken(
                    surface=surface,
                    canonical=surface,
                    position=position,
                    kind=TokenKind.NUMBER,
                )
            )
        else:
            tokens.append(
                LexicalToken(
                    surface=surface,
                    canonical=surface,
                    position=position,
                    kind=TokenKind.WORD,
                )
            )
        position += 1

    return LexicalRepresentation(tokens=tuple(tokens), ranges=tuple(ranges))
