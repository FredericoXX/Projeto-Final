"""PostgreSQL integrity tests for conversational replies and cited sources.

These tests deliberately bypass the API and services.  Their purpose is to
prove that the database itself preserves conversation/tenant boundaries and
the immutable relationship between an assistant answer and its source chunks.
"""

import hashlib
import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.conversation import Conversation
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.institution import Institution
from app.models.message import Message
from app.models.message_source import MessageSource
from app.models.user import User


@pytest.fixture
def db_session(test_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = test_session_factory()
    yield session
    session.rollback()
    session.close()


def _create_tenant(session: Session) -> tuple[Institution, User, Conversation]:
    suffix = uuid.uuid4().hex[:8]
    institution = Institution(
        name=f"Institution {suffix}",
        code=f"SRC-{suffix.upper()}",
        default_language="pt",
        supported_languages=["pt", "en"],
    )
    session.add(institution)
    session.flush()

    user = User(
        institution_id=institution.id,
        full_name="Integrity User",
        email=f"source-{suffix}@example.com",
        password_hash="not-a-real-hash",
        role="user",
        is_active=True,
    )
    session.add(user)
    session.flush()

    conversation = Conversation(
        institution_id=institution.id,
        user_id=user.id,
        title="Integrity conversation",
        language="pt",
        status="active",
    )
    session.add(conversation)
    session.flush()
    return institution, user, conversation


def _create_conversation(
    session: Session,
    institution: Institution,
    user: User,
) -> Conversation:
    conversation = Conversation(
        institution_id=institution.id,
        user_id=user.id,
        title="Other conversation",
        language="pt",
        status="active",
    )
    session.add(conversation)
    session.flush()
    return conversation


def _create_message(
    session: Session,
    institution: Institution,
    conversation: Conversation,
    user: User,
    *,
    role: str,
    reply_to: Message | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation.id,
        institution_id=institution.id,
        user_id=None if role == "assistant" else user.id,
        reply_to_message_id=reply_to.id if reply_to is not None else None,
        role=role,
        content=f"{role} message",
        language="pt",
    )
    session.add(message)
    session.flush()
    return message


def _create_document_graph(
    session: Session,
    institution: Institution,
    user: User,
    *,
    chunk_index: int = 0,
) -> tuple[Document, DocumentVersion, DocumentChunk]:
    suffix = uuid.uuid4().hex
    document = Document(
        institution_id=institution.id,
        created_by_user_id=user.id,
        title=f"Source document {suffix[:8]}",
        language="pt",
        source_url=f"https://example.com/{suffix}",
        official_source=True,
        valid_from=date(2026, 1, 1),
        valid_until=date(2026, 12, 31),
    )
    session.add(document)
    session.flush()

    version = DocumentVersion(
        document_id=document.id,
        institution_id=institution.id,
        uploaded_by_user_id=user.id,
        version_number=1,
        original_filename=f"{suffix}.txt",
        mime_type="text/plain",
        size_bytes=20,
        checksum_sha256=hashlib.sha256(f"version-{suffix}".encode()).hexdigest(),
        storage_path=f"{institution.id}/{document.id}/{suffix}/source.txt",
        processing_status="processed",
    )
    session.add(version)
    session.flush()

    content = f"Source chunk {suffix}"
    chunk = DocumentChunk(
        institution_id=institution.id,
        document_id=document.id,
        document_version_id=version.id,
        chunk_index=chunk_index,
        content=content,
        normalized_content=content.lower(),
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        start_char=0,
        end_char=len(content),
        language="pt",
    )
    session.add(chunk)
    session.flush()
    return document, version, chunk


def _create_additional_chunk(
    session: Session,
    document: Document,
    version: DocumentVersion,
    *,
    chunk_index: int,
) -> DocumentChunk:
    content = f"Additional source chunk {uuid.uuid4().hex}"
    chunk = DocumentChunk(
        institution_id=document.institution_id,
        document_id=document.id,
        document_version_id=version.id,
        chunk_index=chunk_index,
        content=content,
        normalized_content=content.lower(),
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        start_char=0,
        end_char=len(content),
        language=document.language,
    )
    session.add(chunk)
    session.flush()
    return chunk


def _source_values(
    message: Message,
    document: Document,
    version: DocumentVersion,
    chunk: DocumentChunk,
    **overrides: object,
) -> dict[str, object]:
    values: dict[str, object] = {
        "institution_id": message.institution_id,
        "message_id": message.id,
        "message_role": message.role,
        "chunk_id": chunk.id,
        "document_id": document.id,
        "document_version_id": version.id,
        "evidence_id": "E1",
        "citation_index": 0,
        "document_title": document.title,
        "chunk_index": chunk.chunk_index,
        "source_url": document.source_url,
        "official_source": document.official_source,
        "language": document.language,
        "valid_from": document.valid_from,
        "valid_until": document.valid_until,
        "content_sha256": chunk.content_sha256,
    }
    values.update(overrides)
    return values


def test_reply_to_message_in_same_conversation_and_tenant_is_allowed(
    db_session: Session,
) -> None:
    institution, user, conversation = _create_tenant(db_session)
    question = _create_message(
        db_session, institution, conversation, user, role="user"
    )
    answer = _create_message(
        db_session,
        institution,
        conversation,
        user,
        role="assistant",
        reply_to=question,
    )

    db_session.commit()

    assert answer.reply_to_message_id == question.id


def test_reply_to_message_from_another_conversation_is_rejected(
    db_session: Session,
) -> None:
    institution, user, conversation_a = _create_tenant(db_session)
    conversation_b = _create_conversation(db_session, institution, user)
    question = _create_message(
        db_session, institution, conversation_a, user, role="user"
    )

    answer = Message(
        conversation_id=conversation_b.id,
        institution_id=institution.id,
        user_id=None,
        reply_to_message_id=question.id,
        role="assistant",
        content="Cross-conversation answer",
        language="pt",
    )
    db_session.add(answer)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_reply_to_message_from_another_tenant_is_rejected(
    db_session: Session,
) -> None:
    institution_a, user_a, conversation_a = _create_tenant(db_session)
    institution_b, user_b, conversation_b = _create_tenant(db_session)
    question_a = _create_message(
        db_session, institution_a, conversation_a, user_a, role="user"
    )

    answer_b = Message(
        conversation_id=conversation_b.id,
        institution_id=institution_b.id,
        user_id=None,
        reply_to_message_id=question_a.id,
        role="assistant",
        content="Cross-tenant answer",
        language="pt",
    )
    db_session.add(answer_b)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_message_cannot_reply_to_itself(db_session: Session) -> None:
    institution, user, conversation = _create_tenant(db_session)
    message_id = uuid.uuid4()
    message = Message(
        id=message_id,
        conversation_id=conversation.id,
        institution_id=institution.id,
        user_id=user.id,
        reply_to_message_id=message_id,
        role="user",
        content="Self reply",
        language="pt",
    )
    db_session.add(message)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_assistant_message_source_with_consistent_chunk_is_allowed(
    db_session: Session,
) -> None:
    institution, user, conversation = _create_tenant(db_session)
    answer = _create_message(
        db_session, institution, conversation, user, role="assistant"
    )
    document, version, chunk = _create_document_graph(db_session, institution, user)
    source = MessageSource(**_source_values(answer, document, version, chunk))
    db_session.add(source)

    db_session.commit()

    assert source.id is not None
    assert source.message_id == answer.id
    assert source.chunk_id == chunk.id


@pytest.mark.parametrize("role", ["user", "system"])
def test_sources_for_non_assistant_messages_are_rejected(
    db_session: Session,
    role: str,
) -> None:
    institution, user, conversation = _create_tenant(db_session)
    message = _create_message(
        db_session, institution, conversation, user, role=role
    )
    document, version, chunk = _create_document_graph(db_session, institution, user)
    db_session.add(MessageSource(**_source_values(message, document, version, chunk)))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_message_source_cannot_cross_tenant_boundary(db_session: Session) -> None:
    institution_a, user_a, conversation_a = _create_tenant(db_session)
    answer_a = _create_message(
        db_session, institution_a, conversation_a, user_a, role="assistant"
    )
    institution_b, user_b, _ = _create_tenant(db_session)
    document_b, version_b, chunk_b = _create_document_graph(
        db_session, institution_b, user_b
    )

    values = _source_values(answer_a, document_b, version_b, chunk_b)
    values["institution_id"] = institution_b.id
    db_session.add(MessageSource(**values))

    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize(
    "mismatched_field",
    ["chunk_id", "document_version_id", "document_id"],
)
def test_message_source_rejects_inconsistent_chunk_version_document_combination(
    db_session: Session,
    mismatched_field: str,
) -> None:
    institution, user, conversation = _create_tenant(db_session)
    answer = _create_message(
        db_session, institution, conversation, user, role="assistant"
    )
    document_a, version_a, chunk_a = _create_document_graph(
        db_session, institution, user
    )
    document_b, version_b, chunk_b = _create_document_graph(
        db_session, institution, user
    )
    replacement = {
        "chunk_id": chunk_b.id,
        "document_version_id": version_b.id,
        "document_id": document_b.id,
    }[mismatched_field]
    values = _source_values(answer, document_a, version_a, chunk_a)
    values[mismatched_field] = replacement
    db_session.add(MessageSource(**values))

    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize(
    "duplicate_field",
    ["evidence_id", "citation_index", "chunk_id"],
)
def test_message_source_rejects_duplicate_identifiers_per_message(
    db_session: Session,
    duplicate_field: str,
) -> None:
    institution, user, conversation = _create_tenant(db_session)
    answer = _create_message(
        db_session, institution, conversation, user, role="assistant"
    )
    document, version, chunk_a = _create_document_graph(
        db_session, institution, user
    )
    chunk_b = _create_additional_chunk(
        db_session, document, version, chunk_index=1
    )

    first = MessageSource(**_source_values(answer, document, version, chunk_a))
    db_session.add(first)
    db_session.flush()

    second_values = _source_values(
        answer,
        document,
        version,
        chunk_b,
        evidence_id="E2",
        citation_index=1,
    )
    if duplicate_field == "evidence_id":
        second_values["evidence_id"] = first.evidence_id
    elif duplicate_field == "citation_index":
        second_values["citation_index"] = first.citation_index
    else:
        second_values["chunk_id"] = chunk_a.id
        second_values["chunk_index"] = chunk_a.chunk_index
    db_session.add(MessageSource(**second_values))

    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize(
    "overrides",
    [
        {"citation_index": -1},
        {"chunk_index": -1},
        {"evidence_id": "   "},
        {"evidence_id": "E0"},
        {"evidence_id": "e1"},
        {"document_title": "   "},
        {"language": "   "},
        {"content_sha256": "a" * 63},
        {"valid_from": date(2026, 12, 31), "valid_until": date(2026, 1, 1)},
    ],
    ids=[
        "negative-citation-index",
        "negative-chunk-index",
        "blank-evidence",
        "invalid-evidence-zero",
        "invalid-evidence-case",
        "blank-title",
        "blank-language",
        "invalid-checksum-length",
        "invalid-validity-range",
    ],
)
def test_message_source_check_constraints_reject_invalid_snapshots(
    db_session: Session,
    overrides: dict[str, object],
) -> None:
    institution, user, conversation = _create_tenant(db_session)
    answer = _create_message(
        db_session, institution, conversation, user, role="assistant"
    )
    document, version, chunk = _create_document_graph(db_session, institution, user)
    db_session.add(
        MessageSource(**_source_values(answer, document, version, chunk, **overrides))
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_deleting_message_cascades_to_its_sources(db_session: Session) -> None:
    institution, user, conversation = _create_tenant(db_session)
    answer = _create_message(
        db_session, institution, conversation, user, role="assistant"
    )
    document, version, chunk = _create_document_graph(db_session, institution, user)
    source = MessageSource(**_source_values(answer, document, version, chunk))
    db_session.add(source)
    db_session.commit()
    source_id = source.id

    db_session.delete(answer)
    db_session.commit()

    assert db_session.get(MessageSource, source_id) is None


def test_deleting_referenced_chunk_is_restricted(db_session: Session) -> None:
    institution, user, conversation = _create_tenant(db_session)
    answer = _create_message(
        db_session, institution, conversation, user, role="assistant"
    )
    document, version, chunk = _create_document_graph(db_session, institution, user)
    source = MessageSource(**_source_values(answer, document, version, chunk))
    db_session.add(source)
    db_session.commit()

    db_session.delete(chunk)
    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()
    assert db_session.get(MessageSource, source.id) is not None


def test_updating_referenced_chunk_is_restricted(db_session: Session) -> None:
    institution, user, conversation = _create_tenant(db_session)
    answer = _create_message(
        db_session, institution, conversation, user, role="assistant"
    )
    document, version, chunk = _create_document_graph(db_session, institution, user)
    source = MessageSource(**_source_values(answer, document, version, chunk))
    db_session.add(source)
    db_session.commit()

    original_content = chunk.content
    chunk.content = "Referenced source changed in place"
    chunk.normalized_content = chunk.content.lower()
    chunk.content_sha256 = hashlib.sha256(chunk.content.encode()).hexdigest()
    chunk.end_char = len(chunk.content)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()
    stored = db_session.get(DocumentChunk, chunk.id)
    assert stored is not None
    assert stored.content == original_content


def test_updating_unreferenced_chunk_is_allowed(db_session: Session) -> None:
    institution, user, _ = _create_tenant(db_session)
    document, version, _ = _create_document_graph(db_session, institution, user)
    chunk = _create_additional_chunk(
        db_session,
        document,
        version,
        chunk_index=1,
    )
    db_session.commit()

    replacement = "Unreferenced source changed in place"
    chunk.content = replacement
    chunk.normalized_content = replacement.lower()
    chunk.content_sha256 = hashlib.sha256(replacement.encode()).hexdigest()
    chunk.end_char = len(replacement)
    db_session.commit()

    stored = db_session.get(DocumentChunk, chunk.id)
    assert stored is not None
    assert stored.content == replacement
