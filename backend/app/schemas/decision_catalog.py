"""Schemas da configuração versionada da política de decisão (D1 e D6).

A configuração tem duas partes: a descrição do domínio de atendimento contra
a qual o âmbito (D1) é estimado, e o catálogo de serviços com competência
declarada por tema (D6). Os contactos são validados com a mesma normalização
do destino humano do E1 (:mod:`app.core.contact`).

Regras de validação, todas determinísticas:

- códigos de tema e de serviço únicos e com formato estável;
- cada serviço tem pelo menos um contacto e pelo menos um tema;
- os temas de um serviço existem no catálogo;
- **cada tema tem no máximo um serviço competente**, para que a resolução do
  destino seja única e reprodutível. Um tema sem serviço é permitido: para
  ele, a política não tem destino e abstém-se em vez de encaminhar.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.contact import normalize_contact_email, normalize_contact_url

_CODE_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"

Code = Annotated[str, Field(pattern=_CODE_PATTERN)]


class CatalogTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Code
    label: Annotated[str, Field(min_length=1, max_length=200)]


class CatalogService(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: Code
    name: Annotated[str, Field(min_length=1, max_length=255)]
    email: str | None = None
    url: str | None = None
    topics: Annotated[list[Code], Field(min_length=1)]

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "name must not be empty or whitespace only"
            raise ValueError(msg)
        return stripped

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return None if value is None else normalize_contact_email(value, field="email")

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str | None) -> str | None:
        return None if value is None else normalize_contact_url(value, field="url")

    @model_validator(mode="after")
    def check_contact(self) -> "CatalogService":
        if self.email is None and self.url is None:
            msg = "a service needs at least one contact (email or url)"
            raise ValueError(msg)
        if len(set(self.topics)) != len(self.topics):
            msg = "service topics must be unique"
            raise ValueError(msg)
        return self


class DecisionCatalogWrite(BaseModel):
    """Nova versão da configuração. Substitui a ativa; nunca a altera."""

    model_config = ConfigDict(extra="forbid")

    scope_description: Annotated[str, Field(min_length=20, max_length=4000)]
    topics: Annotated[list[CatalogTopic], Field(min_length=1, max_length=100)]
    services: Annotated[list[CatalogService], Field(max_length=100)] = []

    @model_validator(mode="after")
    def check_catalog(self) -> "DecisionCatalogWrite":
        codes = [topic.code for topic in self.topics]
        if len(set(codes)) != len(codes):
            msg = "topic codes must be unique"
            raise ValueError(msg)
        service_ids = [service.service_id for service in self.services]
        if len(set(service_ids)) != len(service_ids):
            msg = "service ids must be unique"
            raise ValueError(msg)
        owner: dict[str, str] = {}
        for service in self.services:
            for topic in service.topics:
                if topic not in codes:
                    msg = f"service {service.service_id} refers to unknown topic {topic}"
                    raise ValueError(msg)
                if topic in owner:
                    msg = (
                        f"topic {topic} has more than one competent service "
                        f"({owner[topic]}, {service.service_id})"
                    )
                    raise ValueError(msg)
                owner[topic] = service.service_id
        return self


class DecisionCatalogRead(BaseModel):
    id: UUID
    version: int
    is_active: bool
    scope_description: str
    topics: list[CatalogTopic]
    services: list[CatalogService]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DecisionCatalogListResponse(BaseModel):
    items: list[DecisionCatalogRead]
