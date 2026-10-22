from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

EXTERNAL_SUBJECT_MAX_LENGTH = 128


class ExternalIdentityLink(BaseModel):
    """Payload administrativo para associar uma conta a um identificador externo.

    Só ``external_subject``: a instituição vem do admin autenticado, a conta do
    caminho, e o mecanismo e o autor da associação são decididos pelo backend.
    """

    model_config = ConfigDict(extra="forbid")

    external_subject: str

    @field_validator("external_subject")
    @classmethod
    def normalize_external_subject(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "external_subject must not be empty or whitespace only"
            raise ValueError(msg)
        if len(normalized) > EXTERNAL_SUBJECT_MAX_LENGTH:
            msg = f"external_subject must be at most {EXTERNAL_SUBJECT_MAX_LENGTH} characters long"
            raise ValueError(msg)
        return normalized


class ExternalIdentityRead(BaseModel):
    user_id: UUID
    institution_id: UUID
    external_subject: str
    link_method: str
    linked_by_user_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
