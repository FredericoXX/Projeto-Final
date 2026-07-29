"""Planeamento determinístico de consultas lexicais progressivas.

Problema: a baseline aplica websearch_to_tsquery('simple', pergunta) à
pergunta inteira, e com a configuração `simple` (sem stopwords nem
stemming) todos os termos são obrigatórios — "Quando começam as aulas?"
exige `quando & comecam & aulas` e falha num documento que só contém
"aulas".

Este módulo produz variantes ordenadas de uma consulta já normalizada
(ver app.core.text_normalization), sem executar SQL:

1. exact — a consulta normalizada original, comportamento atual;
2. reduced_and — apenas os termos informativos, todos obrigatórios;
3. reduced_or — os mesmos termos informativos, qualquer um suficiente.

A partir do Momento 4, o retriever executa **todas** as variantes
permitidas, agrega os candidatos num pool limitado (deduplicado por
chunk_id, preservando a melhor estratégia) e aplica um reranking lexical
determinístico. A estratégia que recuperou cada candidato passa a ser um
sinal explícito do ranking (exact > reduced_and > reduced_or), em vez de
"a primeira variante com resultados vence".

Regras deliberadas:
- determinístico, local, sem LLM, sem embeddings, sem stemming próprio
  e sem sinónimos;
- consultas com sintaxe websearch explícita (aspas, OR, termos
  negativos) usam apenas a variante exact — a relaxação nunca pode
  inverter uma intenção explícita (ex.: `matricula -propinas` nunca
  pode passar a procurar também "propinas");
- idioma suportado sem lista de termos funcionais própria usa apenas a
  variante exact — nunca se aplica a lista de outro idioma;
- num idioma com lista própria, uma consulta simples composta apenas
  por termos funcionais ("O que é?") produz um plano sem variantes:
  não se pesquisa de todo, porque qualquer correspondência seria uma
  coincidência de palavras funcionais sem valor informativo.

Sem SQL, sem SQLAlchemy e sem regras de autenticação neste módulo.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

# Uma pergunta pode ter até 1000 caracteres; a tsquery reduzida nunca
# precisa de mais do que isto para uma baseline lexical.
MAX_INFORMATIVE_TERMS = 12

# Tokens de palavra sem underscore; linear, sem backtracking aninhado.
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Listas pequenas e conservadoras de termos claramente funcionais
# (artigos, preposições/contrações, interrogativos e auxiliares comuns),
# na forma NORMALIZADA (sem acentos, minúsculas): "e" cobre "e" e "é",
# "sao" cobre "são", "ate" cobre "até". Termos potencialmente
# informativos (matrícula, aulas, exames, biblioteca, período,
# prestação, registration, students, office, deadline...) nunca entram.
_FUNCTIONAL_TERMS: dict[str, frozenset[str]] = {
    "pt": frozenset(
        {
            "a", "o", "as", "os", "um", "uma",
            "de", "do", "da", "dos", "das", "ao", "aos",
            "em", "no", "na", "nos", "nas", "pelo", "pela",
            "para", "por", "com", "ate", "se",
            "e", "ou", "que",
            "qual", "quais", "quando", "onde", "como", "quem",
            "sao", "ser",
            "posso", "pode", "devo", "deve",
        }
    ),
    "en": frozenset(
        {
            "a", "an", "the",
            "of", "to", "in", "on", "for", "with", "from", "at",
            "and", "or",
            "what", "which", "when", "where", "how", "who",
            "is", "are", "does", "do", "can", "should",
            "have", "has",
        }
    ),
}


class LexicalQueryStrategy(StrEnum):
    EXACT = "exact"
    REDUCED_AND = "reduced_and"
    REDUCED_OR = "reduced_or"


@dataclass(frozen=True)
class LexicalQueryVariant:
    """Uma tentativa de pesquisa: o texto é sempre passado como parâmetro
    a websearch_to_tsquery, nunca interpolado em SQL."""

    strategy: LexicalQueryStrategy
    websearch_input: str


@dataclass(frozen=True)
class LexicalQueryPlan:
    """Variantes por prioridade; pode estar vazio sem termos informativos."""

    variants: tuple[LexicalQueryVariant, ...]


def _functional_terms_for(language: str) -> frozenset[str] | None:
    """Lista do idioma resolvido: código exato, depois subtag primário
    (ex.: "pt-pt" -> "pt"); None quando não existe lista própria."""
    normalized = language.strip().lower()
    if normalized in _FUNCTIONAL_TERMS:
        return _FUNCTIONAL_TERMS[normalized]
    primary = normalized.split("-")[0]
    return _FUNCTIONAL_TERMS.get(primary)


def functional_terms_for(language: str) -> frozenset[str]:
    """Termos funcionais do idioma (vazio quando não há lista própria).

    Acessor público reutilizado pelo reranking lexical para distinguir os
    termos informativos da consulta e do conteúdo. Nunca é ``None``: um
    idioma sem lista devolve um conjunto vazio, o que significa "nenhum
    termo é considerado funcional".
    """
    return _functional_terms_for(language) or frozenset()


def _uses_advanced_syntax(normalized_query: str) -> bool:
    """Sintaxe websearch explícita: aspas, termos negativos ou o operador
    OR (a normalização já converteu tudo para minúsculas)."""
    if '"' in normalized_query:
        return True
    for token in normalized_query.split(" "):
        if token == "or":
            return True
        if token.startswith("-") and len(token) > 1:
            return True
    return False


def _raw_tokens(normalized_query: str) -> list[str]:
    return _TOKEN_RE.findall(normalized_query)


def extract_informative_terms(normalized_query: str, language: str) -> tuple[str, ...]:
    """Termos informativos da consulta normalizada, por ordem original.

    Regras: tokens de palavra sem pontuação; sem duplicados (preserva a
    primeira ocorrência); números e anos mantidos; tokens alfabéticos de
    um único carácter ignorados; termos funcionais do idioma removidos;
    máximo de MAX_INFORMATIVE_TERMS termos. Determinístico por construção.
    """
    functional = _functional_terms_for(language) or frozenset()
    terms: list[str] = []
    seen: set[str] = set()
    for token in _raw_tokens(normalized_query):
        if len(token) == 1 and token.isalpha():
            continue
        if token in functional or token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= MAX_INFORMATIVE_TERMS:
            break
    return tuple(terms)


def plan_lexical_query(normalized_query: str, language: str) -> LexicalQueryPlan:
    """Produz variantes ordenadas para uma consulta normalizada.

    Consultas simples sem termos informativos num idioma com lista própria
    produzem um plano vazio. Nos restantes casos, a variante exact preserva
    o comportamento atual; variantes reduzidas só são acrescentadas quando
    diferem da exata e quando a relaxação é segura.
    """
    exact = LexicalQueryVariant(LexicalQueryStrategy.EXACT, normalized_query)

    if _uses_advanced_syntax(normalized_query):
        return LexicalQueryPlan((exact,))
    if _functional_terms_for(language) is None:
        return LexicalQueryPlan((exact,))

    informative = extract_informative_terms(normalized_query, language)
    if not informative:
        # Só termos funcionais: qualquer correspondência seria uma
        # coincidência de palavras funcionais — "O que é?" encontraria um
        # documento que contenha literalmente "o que é" — sem qualquer
        # valor informativo. Num idioma com lista própria, uma consulta
        # simples sem termos informativos não pesquisa de todo (zero
        # evidências); consultas explicitamente citadas/avançadas mantêm
        # a variante exact (ramo acima).
        return LexicalQueryPlan(())

    variants = [exact]
    # A exact já é conjuntiva sobre todos os tokens; reduced_and só vale
    # a pena se algum token foi de facto removido.
    if list(informative) != _raw_tokens(normalized_query):
        variants.append(
            LexicalQueryVariant(
                LexicalQueryStrategy.REDUCED_AND, " ".join(informative)
            )
        )
    # Com um único termo, OR e AND são a mesma consulta.
    if len(informative) >= 2:
        variants.append(
            LexicalQueryVariant(
                LexicalQueryStrategy.REDUCED_OR, " OR ".join(informative)
            )
        )
    return LexicalQueryPlan(tuple(variants))
