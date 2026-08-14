from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.core.contact import normalize_contact_email, normalize_contact_url
from app.core.language import normalize_language_code

NAME_MAX_LENGTH = 255
CODE_MAX_LENGTH = 50
DOMAIN_MAX_LENGTH = 255
MAX_SUPPORTED_LANGUAGES = 20
HUMAN_SUPPORT_NAME_MAX_LENGTH = 255

HUMAN_SUPPORT_CONFIGURATION_ERROR = (
    "human support must be either fully unset or have human_support_name "
    "together with at least one of human_support_email / human_support_url"
)


def is_valid_human_support_configuration(
    name: str | None,
    email: str | None,
    url: str | None,
) -> bool:
    """Invariante do destino humano: ou nada configurado, ou nome com pelo
    menos uma via de contacto.

    Fonte única da regra, partilhada pelo schema de criação e por
    ``institution_service`` (que a aplica sobre o estado *final* de um PATCH
    parcial). Espelha ``ck_institutions_human_support_configuration``.
    """
    if name is None and email is None and url is None:
        return True
    return name is not None and (email is not None or url is not None)


def _normalize_language_list(value: list[str]) -> list[str]:
    # Remove duplicados após a normalização, preservando a primeira
    # ocorrência e a ordem original de introdução.
    normalized: list[str] = []
    seen: set[str] = set()
    for language in value:
        candidate = normalize_language_code(language)
        if candidate not in seen:
            seen.add(candidate)
            normalized.append(candidate)
    if not normalized:
        msg = "supported_languages must contain at least one language"
        raise ValueError(msg)
    if len(normalized) > MAX_SUPPORTED_LANGUAGES:
        msg = f"supported_languages must contain at most {MAX_SUPPORTED_LANGUAGES} languages"
        raise ValueError(msg)
    return normalized


# Partilhados entre o schema de criação e o de atualização parcial, para que a
# mesma normalização se aplique nos dois caminhos sem duplicar as regras.
def _normalize_human_support_name(value: str | None) -> str | None:
    if value is None:
        return value
    normalized = value.strip()
    if not normalized:
        msg = "human_support_name must not be empty or whitespace only"
        raise ValueError(msg)
    if len(normalized) > HUMAN_SUPPORT_NAME_MAX_LENGTH:
        msg = (
            "human_support_name must be at most "
            f"{HUMAN_SUPPORT_NAME_MAX_LENGTH} characters long"
        )
        raise ValueError(msg)
    return normalized


def _normalize_human_support_email(value: str | None) -> str | None:
    if value is None:
        return value
    return normalize_contact_email(value, field="human_support_email")


def _normalize_human_support_url(value: str | None) -> str | None:
    if value is None:
        return value
    return normalize_contact_url(value, field="human_support_url")


class InstitutionBase(BaseModel):
    name: str
    code: str
    domain: str | None = None
    default_language: str
    supported_languages: list[str]
    is_active: bool = True

    # Destino humano default da instituição (encaminhamento E1). Opcionais:
    # uma instituição sem atendimento humano configurado continua válida.
    human_support_name: str | None = None
    human_support_email: str | None = None
    human_support_url: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "name must not be empty or whitespace only"
            raise ValueError(msg)
        if len(normalized) > NAME_MAX_LENGTH:
            msg = f"name must be at most {NAME_MAX_LENGTH} characters long"
            raise ValueError(msg)
        return normalized

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            msg = "code must not be empty or whitespace only"
            raise ValueError(msg)
        if len(normalized) > CODE_MAX_LENGTH:
            msg = f"code must be at most {CODE_MAX_LENGTH} characters long"
            raise ValueError(msg)
        return normalized

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            msg = "domain must not be empty or whitespace only"
            raise ValueError(msg)
        if len(normalized) > DOMAIN_MAX_LENGTH:
            msg = f"domain must be at most {DOMAIN_MAX_LENGTH} characters long"
            raise ValueError(msg)
        return normalized

    @field_validator("default_language")
    @classmethod
    def normalize_default_language(cls, value: str) -> str:
        return normalize_language_code(value)

    @field_validator("supported_languages")
    @classmethod
    def normalize_supported_languages(cls, value: list[str]) -> list[str]:
        return _normalize_language_list(value)

    @field_validator("human_support_name")
    @classmethod
    def normalize_human_support_name(cls, value: str | None) -> str | None:
        return _normalize_human_support_name(value)

    @field_validator("human_support_email")
    @classmethod
    def normalize_human_support_email(cls, value: str | None) -> str | None:
        return _normalize_human_support_email(value)

    @field_validator("human_support_url")
    @classmethod
    def normalize_human_support_url(cls, value: str | None) -> str | None:
        return _normalize_human_support_url(value)


class InstitutionCreate(InstitutionBase):
    # extra="forbid" apenas aqui (não em InstitutionBase, de que
    # InstitutionRead também herda): payloads de escrita com campos
    # desconhecidos devolvem 422 em vez de serem ignorados.
    model_config = ConfigDict(extra="forbid")

    # Espelha a check constraint da base de dados, permitindo devolver
    # o erro de validação ao cliente antes de tentar o INSERT.
    @model_validator(mode="after")
    def check_default_language_is_supported(self) -> "InstitutionCreate":
        if self.default_language not in self.supported_languages:
            msg = "default_language must be one of supported_languages"
            raise ValueError(msg)
        return self

    # Espelha ck_institutions_human_support_configuration pela mesma razão:
    # o cliente recebe 422 em vez de um erro de constraint no INSERT.
    @model_validator(mode="after")
    def check_human_support_configuration(self) -> "InstitutionCreate":
        if not is_valid_human_support_configuration(
            self.human_support_name,
            self.human_support_email,
            self.human_support_url,
        ):
            raise ValueError(HUMAN_SUPPORT_CONFIGURATION_ERROR)
        return self


class InstitutionAdminUpdate(BaseModel):
    """Payload for PATCH /institutions/{id}, used by an institutional
    admin updating their own institution.

    is_active is deliberately not a field here: an institutional admin
    can lock themselves and everyone else out by deactivating their own
    institution, with no recovery path through this endpoint. Activation
    /deactivation is only possible through the bootstrap-only status
    endpoint (see InstitutionStatusUpdate). extra="forbid" turns an
    attempt to send is_active into a 422 instead of silently ignoring it.
    """

    model_config = ConfigDict(extra="forbid")

    # Todos os campos são opcionais para suportar atualizações parciais (PATCH);
    # a consistência entre default_language e supported_languages é validada
    # depois, ao nível do serviço, com base no estado final da entidade.
    name: str | None = None
    code: str | None = None
    domain: str | None = None
    default_language: str | None = None
    supported_languages: list[str] | None = None

    # None tem aqui os dois significados possíveis de um PATCH: campo ausente
    # (não mexer) ou enviado explicitamente como null (limpar). A distinção é
    # feita por exclude_unset no serviço, como nos restantes campos; enviar
    # null nos três limpa a configuração e volta ao estado "não configurada".
    human_support_name: str | None = None
    human_support_email: str | None = None
    human_support_url: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            msg = "name must not be empty or whitespace only"
            raise ValueError(msg)
        if len(normalized) > NAME_MAX_LENGTH:
            msg = f"name must be at most {NAME_MAX_LENGTH} characters long"
            raise ValueError(msg)
        return normalized

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().upper()
        if not normalized:
            msg = "code must not be empty or whitespace only"
            raise ValueError(msg)
        if len(normalized) > CODE_MAX_LENGTH:
            msg = f"code must be at most {CODE_MAX_LENGTH} characters long"
            raise ValueError(msg)
        return normalized

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            msg = "domain must not be empty or whitespace only"
            raise ValueError(msg)
        if len(normalized) > DOMAIN_MAX_LENGTH:
            msg = f"domain must be at most {DOMAIN_MAX_LENGTH} characters long"
            raise ValueError(msg)
        return normalized

    @field_validator("default_language")
    @classmethod
    def normalize_default_language(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return normalize_language_code(value)

    @field_validator("supported_languages")
    @classmethod
    def normalize_supported_languages(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        return _normalize_language_list(value)

    @field_validator("human_support_name")
    @classmethod
    def normalize_human_support_name(cls, value: str | None) -> str | None:
        return _normalize_human_support_name(value)

    @field_validator("human_support_email")
    @classmethod
    def normalize_human_support_email(cls, value: str | None) -> str | None:
        return _normalize_human_support_email(value)

    @field_validator("human_support_url")
    @classmethod
    def normalize_human_support_url(cls, value: str | None) -> str | None:
        return _normalize_human_support_url(value)


class InstitutionStatusUpdate(BaseModel):
    """Payload for the bootstrap-only PATCH /bootstrap/institutions/{id}/status
    endpoint. Deliberately limited to is_active — extra="forbid" means this
    endpoint can never be used to sneak in other field changes."""

    model_config = ConfigDict(extra="forbid")

    is_active: bool


class InstitutionRead(InstitutionBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InstitutionListResponse(BaseModel):
    items: list[InstitutionRead]
    total: int
    limit: int
    offset: int
