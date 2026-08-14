"""Mensagem determinística de encaminhamento humano (E1).

Função pura, local e **sem qualquer LLM** — o padrão é o de
:mod:`app.core.conversation_title` e :mod:`app.answering.fallback`: texto fixo
por idioma, versionado no código, com o inglês como fallback documentado para
um idioma sem redação própria. Não há aqui tradução automática nem geração.

A redação é deliberadamente conservadora quanto ao que E1 é. O sistema
**direciona** o utilizador para um destino humano; não cria um caso, não
notifica ninguém, não atribui operador e não promete prazo de resposta. Uma
frase como "um operador entrará em contacto" seria factualmente falsa neste
nível de maturidade (ver A2.2, secção 7.6.1).
"""

from dataclasses import dataclass

# Identidade da redação, guardada no snapshot da mensagem. Sem ela, uma
# mensagem histórica não seria interpretável depois de o texto mudar — é o
# mesmo argumento de `score_semantics.version` no retrieval.
HANDOFF_MESSAGE_VERSION = "human_handoff_e1_v1"

_DEFAULT_MESSAGE_LANGUAGE = "en"


@dataclass(frozen=True)
class HumanSupportDestination:
    """Destino humano tal como será apresentado ao utilizador.

    Imutável de propósito: é copiado da instituição no momento do
    encaminhamento e persistido como snapshot, não como referência viva.
    ``name`` é obrigatório; pelo menos um de ``email``/``url`` está presente
    (invariante garantida por ``ck_institutions_human_support_configuration``).
    """

    name: str
    email: str | None
    url: str | None


_TEMPLATES: dict[str, dict[str, str]] = {
    "pt": {
        "intro": (
            "Este pedido será melhor tratado por atendimento humano. "
            "Contacte diretamente o serviço indicado."
        ),
        "name": "Serviço",
        "email": "Email",
        "url": "Ligação",
    },
    "en": {
        "intro": (
            "This request is better handled by human support. "
            "Please contact the service listed below directly."
        ),
        "name": "Service",
        "email": "Email",
        "url": "Link",
    },
}


def _resolve_template(language: str) -> dict[str, str]:
    """Mesma resolução de :func:`app.answering.fallback.get_fallback_message`:
    código completo ("pt-pt"), depois subtag primária ("pt"), depois inglês."""
    normalized = language.strip().lower()
    if normalized in _TEMPLATES:
        return _TEMPLATES[normalized]
    primary = normalized.split("-")[0]
    if primary in _TEMPLATES:
        return _TEMPLATES[primary]
    return _TEMPLATES[_DEFAULT_MESSAGE_LANGUAGE]


def build_handoff_message(language: str, destination: HumanSupportDestination) -> str:
    """Compõe a mensagem apresentada ao utilizador, sem chamar nada externo."""
    template = _resolve_template(language)
    lines = [template["intro"], "", f"{template['name']}: {destination.name}"]
    if destination.email is not None:
        lines.append(f"{template['email']}: {destination.email}")
    if destination.url is not None:
        lines.append(f"{template['url']}: {destination.url}")
    return "\n".join(lines)
