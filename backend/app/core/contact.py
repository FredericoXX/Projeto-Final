"""Validação determinística de contactos institucionais (email e URL).

Deliberadamente **não** implementa a RFC 5322 nem a RFC 3986: o objetivo é
recusar dados manifestamente inválidos e, sobretudo, esquemas de URL perigosos
(``javascript:``, ``data:``, ``file:``, ``ftp:``) antes de um contacto chegar a
ser renderizado como ligação. Um validador completo de email exigiria uma
dependência nova para ganhar precisão que nenhuma decisão do sistema usa.

As funções levantam ``ValueError`` — e não o ``ValidationError`` de domínio —
para que os ``field_validator`` do Pydantic as possam chamar diretamente, tal
como acontece em :func:`app.core.language.normalize_language_code`.
"""

from urllib.parse import urlsplit

EMAIL_MAX_LENGTH = 320
EMAIL_LOCAL_MAX_LENGTH = 64
EMAIL_DOMAIN_MAX_LENGTH = 255
DOMAIN_LABEL_MAX_LENGTH = 63

URL_MAX_LENGTH = 2048

# Apenas estes dois esquemas produzem uma ligação navegável segura. A lista é
# de inclusão, não de exclusão: um esquema novo é recusado por omissão, sem
# depender de conhecer previamente todos os esquemas perigosos.
ALLOWED_URL_SCHEMES = frozenset({"http", "https"})

# Caracteres que nunca pertencem a um endereço de email real e que, se
# passassem, apareceriam num cabeçalho ou numa ligação mailto.
_FORBIDDEN_EMAIL_CHARACTERS = frozenset('<>()[]\\,;:"')

_DOMAIN_LABEL_EXTRA_CHARACTERS = frozenset("-")


def _reject_whitespace_and_control_characters(value: str, field: str) -> None:
    if any(character.isspace() for character in value):
        msg = f"{field} must not contain whitespace"
        raise ValueError(msg)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        msg = f"{field} must not contain control characters"
        raise ValueError(msg)


def _validate_domain(domain: str, field: str) -> None:
    if not domain or len(domain) > EMAIL_DOMAIN_MAX_LENGTH:
        msg = f"{field} must contain a valid domain"
        raise ValueError(msg)
    labels = domain.split(".")
    # Um domínio sem ponto ("suporte@localhost") é recusado: um destino
    # institucional tem de ser contactável a partir de fora da instituição.
    if len(labels) < 2:
        msg = f"{field} domain must contain at least one dot"
        raise ValueError(msg)
    for label in labels:
        if not label or len(label) > DOMAIN_LABEL_MAX_LENGTH:
            msg = f"{field} domain has an empty or oversized label"
            raise ValueError(msg)
        if label.startswith("-") or label.endswith("-"):
            msg = f"{field} domain label must not start or end with '-'"
            raise ValueError(msg)
        if not all(
            character.isalnum() or character in _DOMAIN_LABEL_EXTRA_CHARACTERS
            for character in label
        ):
            msg = f"{field} domain contains invalid characters"
            raise ValueError(msg)


def normalize_contact_email(value: str, *, field: str = "email") -> str:
    """Normaliza e valida estruturalmente um endereço de email de contacto.

    Remove apenas espaços exteriores; whitespace interior é erro, não algo a
    corrigir silenciosamente. O resultado preserva as maiúsculas escritas pelo
    administrador — a parte local de um email é sensível a maiúsculas, e
    reescrevê-la poderia alterar o destinatário.
    """
    normalized = value.strip()
    if not normalized:
        msg = f"{field} must not be empty or whitespace only"
        raise ValueError(msg)
    if len(normalized) > EMAIL_MAX_LENGTH:
        msg = f"{field} must be at most {EMAIL_MAX_LENGTH} characters long"
        raise ValueError(msg)

    _reject_whitespace_and_control_characters(normalized, field)

    if any(character in _FORBIDDEN_EMAIL_CHARACTERS for character in normalized):
        msg = f"{field} contains invalid characters"
        raise ValueError(msg)

    if normalized.count("@") != 1:
        msg = f"{field} must contain exactly one '@'"
        raise ValueError(msg)

    local, _, domain = normalized.partition("@")
    if not local or len(local) > EMAIL_LOCAL_MAX_LENGTH:
        msg = f"{field} must contain a valid local part"
        raise ValueError(msg)
    if local.startswith(".") or local.endswith(".") or ".." in local:
        msg = f"{field} local part has misplaced dots"
        raise ValueError(msg)

    _validate_domain(domain, field)
    return normalized


def normalize_contact_url(value: str, *, field: str = "url") -> str:
    """Normaliza e valida um URL de contacto, aceitando apenas http/https.

    Devolve o valor tal como foi escrito (sem espaços exteriores): a
    reconstrução do URL a partir das suas partes poderia alterar um endereço
    válido, e o que interessa fixar aqui é que o esquema é navegável e que
    existe um host.
    """
    normalized = value.strip()
    if not normalized:
        msg = f"{field} must not be empty or whitespace only"
        raise ValueError(msg)
    if len(normalized) > URL_MAX_LENGTH:
        msg = f"{field} must be at most {URL_MAX_LENGTH} characters long"
        raise ValueError(msg)

    _reject_whitespace_and_control_characters(normalized, field)

    try:
        parts = urlsplit(normalized)
    except ValueError as exc:
        msg = f"{field} is not a valid URL"
        raise ValueError(msg) from exc

    if parts.scheme.lower() not in ALLOWED_URL_SCHEMES:
        msg = f"{field} must use the http or https scheme"
        raise ValueError(msg)

    # urlsplit aceita "http:/exemplo" sem host; sem host não há ligação.
    try:
        host = parts.hostname
    except ValueError as exc:
        msg = f"{field} is not a valid URL"
        raise ValueError(msg) from exc
    if not host:
        msg = f"{field} must contain a host"
        raise ValueError(msg)

    return normalized
