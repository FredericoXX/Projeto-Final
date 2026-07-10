"""Direct-to-PostgreSQL tests for the composite multi-institution foreign
keys (migration 3ed4bcad52c8 / models Conversation and Message).

The service layer already enforces institution scoping in application
code (get_accessible_conversation, etc.), so these tests bypass it on
purpose and build rows directly through the ORM, to confirm the same
invariant — a conversation/message can never point at a user or
conversation from a different institution — is also enforced by
PostgreSQL itself, as a defense-in-depth guarantee independent of the
application code.

Runs against the dedicated test database (see conftest.py), using
`test_session_factory` directly rather than the `client` fixture, since
there's no need for the HTTP layer here.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.conversation import Conversation
from app.models.institution import Institution
from app.models.message import Message
from app.models.user import User


def _make_institution() -> Institution:
    return Institution(
        name="Test Institution",
        code=f"TST-{uuid.uuid4().hex[:8].upper()}",
        default_language="pt",
        supported_languages=["pt", "en"],
    )


def _make_user(institution: Institution) -> User:
    return User(
        institution_id=institution.id,
        full_name="Test User",
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        role="user",
        is_active=True,
    )


@pytest.fixture
def db_session(test_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = test_session_factory()
    yield session
    session.rollback()
    session.close()


def test_conversation_rejects_user_from_another_institution(db_session: Session) -> None:
    institution_a = _make_institution()
    institution_b = _make_institution()
    db_session.add_all([institution_a, institution_b])
    db_session.flush()

    user_b = _make_user(institution_b)
    db_session.add(user_b)
    db_session.flush()

    # user_b belongs to institution_b, but the conversation claims
    # institution_a: the composite FK on (user_id, institution_id) must
    # reject this, even though user_b.id alone is a valid user.
    conversation = Conversation(
        institution_id=institution_a.id,
        user_id=user_b.id,
        status="active",
    )
    db_session.add(conversation)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_message_rejects_conversation_from_another_institution(db_session: Session) -> None:
    institution_a = _make_institution()
    institution_b = _make_institution()
    db_session.add_all([institution_a, institution_b])
    db_session.flush()

    user_a = _make_user(institution_a)
    db_session.add(user_a)
    db_session.flush()

    conversation_a = Conversation(
        institution_id=institution_a.id, user_id=user_a.id, status="active"
    )
    db_session.add(conversation_a)
    db_session.flush()

    # conversation_a belongs to institution_a; the message falsely claims
    # institution_b. The composite FK on (conversation_id, institution_id)
    # must reject this.
    message = Message(
        conversation_id=conversation_a.id,
        institution_id=institution_b.id,
        role="user",
        content="hello",
    )
    db_session.add(message)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_message_rejects_user_from_another_institution(db_session: Session) -> None:
    institution_a = _make_institution()
    institution_b = _make_institution()
    db_session.add_all([institution_a, institution_b])
    db_session.flush()

    user_a = _make_user(institution_a)
    user_b = _make_user(institution_b)
    db_session.add_all([user_a, user_b])
    db_session.flush()

    conversation_a = Conversation(
        institution_id=institution_a.id, user_id=user_a.id, status="active"
    )
    db_session.add(conversation_a)
    db_session.flush()

    # The conversation and institution_id are consistent (institution_a),
    # but user_b belongs to institution_b: the composite FK on
    # (user_id, institution_id) must reject this.
    message = Message(
        conversation_id=conversation_a.id,
        institution_id=institution_a.id,
        user_id=user_b.id,
        role="user",
        content="hello",
    )
    db_session.add(message)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_message_with_null_user_id_is_allowed_regardless_of_institution(
    db_session: Session,
) -> None:
    """A NULL user_id (future automatic "assistant" messages) must not be
    checked by the composite FK at all — PostgreSQL's default MATCH
    SIMPLE behavior skips the constraint when any FK column is NULL."""
    institution = _make_institution()
    db_session.add(institution)
    db_session.flush()

    user = _make_user(institution)
    db_session.add(user)
    db_session.flush()

    conversation = Conversation(
        institution_id=institution.id, user_id=user.id, status="active"
    )
    db_session.add(conversation)
    db_session.flush()

    message = Message(
        conversation_id=conversation.id,
        institution_id=institution.id,
        user_id=None,
        role="assistant",
        content="automated reply",
    )
    db_session.add(message)
    db_session.commit()

    assert message.id is not None
