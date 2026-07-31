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
3. canonical_relaxed_and — os termos contextuais **não canónicos**, todos
   obrigatórios, com os ordinais/intervalos removidos apenas da consulta
   FTS (continuam obrigatórios na elegibilidade e no ranking canónico);
4. reduced_or — os termos informativos, qualquer um suficiente.

O retriever executa **todas** as variantes permitidas dentro de um
orçamento global de candidatos distribuído por quotas (ver
app.retrieval.lexical), agrega os candidatos, deduplica-os por chunk_id
(preservando a melhor estratégia) e aplica elegibilidade + reranking
determinístico. A estratégia que recuperou cada candidato é um sinal
explícito, em vez de "a primeira variante com resultados vence".

Regras deliberadas:
- determinístico, local, sem LLM, sem embeddings, sem stemming próprio
  e sem sinónimos;
- a relaxação canónica **nunca** expande um ordinal para o seu cardinal:
  "primeira" jamais se torna "primeira OR 1", e "01a12" jamais se torna
  uma pesquisa pelos endpoints "01"/"12" isolados — pesquisar por um
  dígito solto recuperaria "Sala 1" para a pergunta "primeira";
- uma consulta composta **apenas** por ordinais/intervalos não tem termo
  contextual que a ancore: usa apenas a variante exact;
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

from app.retrieval.lexical_normalization import (
    CANONICAL_KINDS,
    LexicalRepresentation,
    build_lexical_representation,
)

# Uma pergunta pode ter até 1000 caracteres; a tsquery reduzida nunca
# precisa de mais do que isto para uma baseline lexical.
MAX_INFORMATIVE_TERMS = 12

# Nº máximo de variantes de um plano (exact, reduced_and,
# canonical_relaxed_and, reduced_or): fixo, sem explosão combinatória.
MAX_QUERY_VARIANTS = 4

# Tokens de palavra sem underscore; linear, sem backtracking aninhado.
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Operadores de websearch_to_tsquery em forma de palavra. Não são conteúdo em
# nenhum idioma: `or` é sempre interpretado como operador pelo PostgreSQL, pelo
# que nunca pode contar como termo informativo da pergunta (contá-lo baixaria
# artificialmente a cobertura de "aulas OR exames" para 2/3).
WEBSEARCH_OPERATORS = frozenset({"or"})

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
    CANONICAL_RELAXED_AND = "canonical_relaxed_and"
    REDUCED_OR = "reduced_or"


# Prioridade única das estratégias (maior é melhor), partilhada por todo o
# retrieval: ordem das variantes no plano, distribuição do resto das
# quotas, escolha da melhor estratégia na deduplicação e o sinal
# ``strategy_quality`` do ranking derivam todos daqui.
STRATEGY_PRIORITY: dict[LexicalQueryStrategy, int] = {
    LexicalQueryStrategy.EXACT: 4,
    LexicalQueryStrategy.REDUCED_AND: 3,
    LexicalQueryStrategy.CANONICAL_RELAXED_AND: 2,
    LexicalQueryStrategy.REDUCED_OR: 1,
}


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


def is_informative_surface(surface: str, functional: frozenset[str]) -> bool:
    """O token é informativo? (nem funcional, nem operador, nem letra isolada).

    Regra única partilhada pelo planeador e pelo reranking, para que a
    consulta e o conteúdo sejam filtrados exatamente da mesma forma.
    """
    if len(surface) == 1 and surface.isalpha():
        return False
    if surface in WEBSEARCH_OPERATORS:
        return False
    return surface not in functional


def uses_advanced_syntax(normalized_query: str) -> bool:
    """Sintaxe websearch explícita: aspas, termos negativos ou o operador
    OR (a normalização já converteu tudo para minúsculas).

    Acessor público: além de restringir o plano à variante exact, a
    elegibilidade precisa de saber que a consulta é explicitamente
    operatória, porque nesse caso a conjunção FTS **não** é garantida (uma
    união `a OR b` corresponde a apenas um dos lados por desenho).
    """
    if '"' in normalized_query:
        return True
    for token in normalized_query.split(" "):
        if token in WEBSEARCH_OPERATORS:
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
        if not is_informative_surface(token, functional):
            continue
        if token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= MAX_INFORMATIVE_TERMS:
            break
    return tuple(terms)


def contextual_terms(normalized_query: str, language: str) -> tuple[str, ...]:
    """Termos informativos **não canónicos** da consulta, por ordem.

    Exclui ordinais e intervalos: são exatamente os termos que ancoram a
    variante ``canonical_relaxed_and``. Para "exames da primeira chamada"
    devolve ``("exames", "chamada")``; para "periodo de inscricoes de
    01a12" devolve ``("periodo", "inscricoes")``. Uma consulta composta
    apenas por ordinais/intervalos devolve uma tupla vazia — e nunca gera
    consulta relaxada, porque procurar só pelo dígito ou pelos endpoints
    seria uma expansão cardinal ampla.
    """
    functional = _functional_terms_for(language) or frozenset()
    representation = build_lexical_representation(normalized_query, language)
    terms: list[str] = []
    seen: set[str] = set()
    for token in representation.tokens:
        if token.kind in CANONICAL_KINDS:
            continue
        if not is_informative_surface(token.surface, functional):
            continue
        if token.surface in seen:
            continue
        seen.add(token.surface)
        terms.append(token.surface)
        if len(terms) >= MAX_INFORMATIVE_TERMS:
            break
    return tuple(terms)


def _has_canonical_unit(representation: LexicalRepresentation) -> bool:
    return any(token.kind in CANONICAL_KINDS for token in representation.tokens)


def plan_lexical_query(normalized_query: str, language: str) -> LexicalQueryPlan:
    """Produz variantes ordenadas por prioridade para uma consulta normalizada.

    Consultas simples sem termos informativos num idioma com lista própria
    produzem um plano vazio. Nos restantes casos, a variante exact preserva
    o comportamento atual; variantes reduzidas só são acrescentadas quando
    diferem da exata e quando a relaxação é segura.
    """
    exact = LexicalQueryVariant(LexicalQueryStrategy.EXACT, normalized_query)

    if uses_advanced_syntax(normalized_query):
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

    contextual = contextual_terms(normalized_query, language)
    if not contextual:
        # Consulta composta apenas por ordinais/intervalos ("primeira",
        # "01a12"): sem termo contextual que a ancore, qualquer relaxação
        # degeneraria numa pesquisa cardinal ampla. Só a variante exact.
        return LexicalQueryPlan((exact,))

    variants = [exact]
    # A exact já é conjuntiva sobre todos os tokens; reduced_and só vale
    # a pena se algum token foi de facto removido.
    if list(informative) != _raw_tokens(normalized_query):
        variants.append(
            LexicalQueryVariant(
                LexicalQueryStrategy.REDUCED_AND, " ".join(informative)
            )
        )
    # A relaxação canónica remove o ordinal/intervalo **apenas da consulta
    # FTS**: um documento que escreva "1.ª" onde a pergunta diz "primeira"
    # (ou "1 a 12" onde a pergunta diz "01a12") continua recuperável pelo
    # contexto. O marcador canónico permanece obrigatório na elegibilidade
    # e no ranking (ver app.retrieval.eligibility).
    representation = build_lexical_representation(normalized_query, language)
    if _has_canonical_unit(representation) and list(contextual) != list(informative):
        variants.append(
            LexicalQueryVariant(
                LexicalQueryStrategy.CANONICAL_RELAXED_AND, " ".join(contextual)
            )
        )
    # Com um único termo informativo, OR e AND são a mesma consulta.
    if len(informative) >= 2:
        variants.append(
            LexicalQueryVariant(
                LexicalQueryStrategy.REDUCED_OR, " OR ".join(informative)
            )
        )
    return LexicalQueryPlan(tuple(variants))
