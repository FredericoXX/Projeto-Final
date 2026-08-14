"""Validação determinística de contactos institucionais — testes puros.

Sem PostgreSQL, sem ``TestClient``, sem fixtures: o sujeito é uma função pura,
tal como em ``test_evidence_retrievability_unit.py``.

O objetivo declarado destas regras (A2.3a, secção 10) é impedir dados
manifestamente inválidos e **URLs perigosos** — não implementar a RFC 5322. Os
testes fixam esse alcance nos dois sentidos: o que tem de ser recusado, e o que
não deve ser recusado só por o validador ser simples.
"""

import pytest

from app.core.contact import (
    EMAIL_MAX_LENGTH,
    URL_MAX_LENGTH,
    normalize_contact_email,
    normalize_contact_url,
)

# --- Email ----------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "support@example.invalid",
        "academic.services@sub.example.invalid",
        "support+geral@example.invalid",
        "a@b.co",
    ],
)
def test_valid_emails_are_accepted(value: str) -> None:
    assert normalize_contact_email(value) == value


def test_outer_whitespace_is_stripped() -> None:
    assert normalize_contact_email("  support@example.invalid \n") == "support@example.invalid"


def test_local_part_case_is_preserved() -> None:
    """A parte local é sensível a maiúsculas: normalizá-la podia mudar o destinatário."""
    assert normalize_contact_email("Academic.Services@Example.invalid") == (
        "Academic.Services@Example.invalid"
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "support",
        "@example.invalid",
        "support@",
        "support@@example.invalid",
        "support@localhost",
        "sup port@example.invalid",
        "support\t@example.invalid",
        "support@example..invalid",
        "support@-example.invalid",
        "support@example-.invalid",
        ".support@example.invalid",
        "support.@example.invalid",
        "sup..port@example.invalid",
        "Support <support@example.invalid>",
        "support@example.invalid, other@example.invalid",
        "support@exa mple.invalid",
        "support@example.inv alid",
        "support\n@example.invalid",
    ],
)
def test_invalid_emails_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_contact_email(value)


def test_email_length_limit_is_enforced() -> None:
    too_long = "a" * (EMAIL_MAX_LENGTH + 1)
    with pytest.raises(ValueError):
        normalize_contact_email(f"{too_long}@example.invalid")


def test_email_header_injection_is_rejected() -> None:
    """CR/LF num contacto é a forma clássica de injetar cabeçalhos."""
    with pytest.raises(ValueError):
        normalize_contact_email("support@example.invalid\r\nBcc: victim@example.invalid")


# --- URL ------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "http://example.invalid",
        "https://example.invalid",
        "https://example.invalid/servicos/academicos",
        "https://example.invalid:8443/apoio?tema=matricula#contactos",
        "HTTPS://example.invalid",
    ],
)
def test_http_and_https_urls_are_accepted(value: str) -> None:
    assert normalize_contact_url(value) == value


def test_url_outer_whitespace_is_stripped() -> None:
    assert normalize_contact_url("  https://example.invalid  ") == "https://example.invalid"


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "  javascript:alert(1)  ",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "file:///etc/passwd",
        "ftp://example.invalid/ficheiro",
        "mailto:support@example.invalid",
        "tel:+123456789",
        "vbscript:msgbox(1)",
    ],
)
def test_dangerous_or_unsupported_schemes_are_rejected(value: str) -> None:
    """Lista de inclusão: um esquema novo é recusado sem ninguém o prever."""
    with pytest.raises(ValueError):
        normalize_contact_url(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "example.invalid",
        "/servicos/academicos",
        "//example.invalid",
        "http://",
        "http:/example.invalid",
        "https://exa mple.invalid",
        "https://example.invalid/a\nb",
    ],
)
def test_invalid_urls_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_contact_url(value)


def test_url_length_limit_is_enforced() -> None:
    too_long = "https://example.invalid/" + ("a" * URL_MAX_LENGTH)
    with pytest.raises(ValueError):
        normalize_contact_url(too_long)


def test_javascript_url_with_embedded_http_is_still_rejected() -> None:
    """O esquema é decidido pelo prefixo, não por conter "http" algures."""
    with pytest.raises(ValueError):
        normalize_contact_url("javascript:window.location='http://example.invalid'")
