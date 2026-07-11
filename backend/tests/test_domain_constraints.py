"""Direct-to-PostgreSQL tests for the domain-value CHECK constraints
(migration 5f638cb2d2c3 / models User, Conversation and Message).

The API schemas already reject invalid roles/statuses at the request
layer, so these tests bypass it on purpose and build rows directly
through the ORM, to confirm the same invariant — users.role,
conversations.status and messages.role can only hold their allowed
values — is also enforced by PostgreSQL itself, as a defense-in-depth
guarantee independent of the application code.

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


def _make_user(institution: Institution, role: str = "user") -> User:
    return User(
        institution_id=institution.id,
        full_name="Test User",
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        role=role,
        is_active=True,
    )


@pytest.fixture
def db_session(test_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = test_session_factory()
    yield session
    session.rollback()
    session.close()


def test_user_with_allowed_role_is_accepted(db_session: Session) -> None:
    institution = _make_institution()
    db_session.add(institution)
    db_session.flush()

    user = _make_user(institution, role="staff")
    db_session.add(user)
    db_session.commit()

    assert user.id is not None


def test_user_with_invalid_role_is_rejected(db_session: Session) -> None:
    institution = _make_institution()
    db_session.add(institution)
    db_session.flush()

    user = _make_user(institution, role="superuser")
    db_session.add(user)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_conversation_with_allowed_status_is_accepted(db_session: Session) -> None:
    institution = _make_institution()
    db_session.add(institution)
    db_session.flush()

    user = _make_user(institution)
    db_session.add(user)
    db_session.flush()

    conversation = Conversation(
        institution_id=institution.id, user_id=user.id, status="archived"
    )
    db_session.add(conversation)
    db_session.commit()

    assert conversation.id is not None


def test_conversation_with_invalid_status_is_rejected(db_session: Session) -> None:
    institution = _make_institution()
    db_session.add(institution)
    db_session.flush()

    user = _make_user(institution)
    db_session.add(user)
    db_session.flush()

    conversation = Conversation(
        institution_id=institution.id, user_id=user.id, status="reopened"
    )
    db_session.add(conversation)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_message_with_allowed_role_is_accepted(db_session: Session) -> None:
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


def test_message_with_invalid_role_is_rejected(db_session: Session) -> None:
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
        user_id=user.id,
        role="moderator",
        content="hello",
    )
    db_session.add(message)
    with pytest.raises(IntegrityError):
        db_session.commit()
