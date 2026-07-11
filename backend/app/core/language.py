"""Shared language-code helpers, reused by the institution, conversation
and message schemas/services so a code like "PT_pt" always normalizes the
same way and "is this language supported here" is only implemented once.
"""

from app.core.exceptions import ValidationError

LANGUAGE_MIN_LENGTH = 2
LANGUAGE_MAX_LENGTH = 8


def normalize_language_code(value: str) -> str:
    """Format-only normalization: trims, lowercases and turns "_" into "-"
    (e.g. "PT_pt" -> "pt-pt"). Raises ValueError so Pydantic field
    validators can call this directly."""
    normalized = value.strip().lower().replace("_", "-")
    if not (LANGUAGE_MIN_LENGTH <= len(normalized) <= LANGUAGE_MAX_LENGTH):
        msg = (
            f"language must be between {LANGUAGE_MIN_LENGTH} and "
            f"{LANGUAGE_MAX_LENGTH} characters long"
        )
        raise ValueError(msg)
    return normalized


def resolve_language(
    requested: str | None,
    *,
    supported_languages: list[str],
    fallback: str,
) -> str:
    """Resolve the language to store on a conversation/message: `fallback`
    (already assumed valid) when `requested` is omitted, otherwise the
    normalized `requested` value, provided it is one of
    `supported_languages`. Raises the domain ValidationError (-> 422) when
    the requested language isn't supported, since this check depends on
    institution data that schemas can't see."""
    if requested is None:
        return fallback
    normalized = normalize_language_code(requested)
    if normalized not in supported_languages:
        msg = f"language '{normalized}' is not supported by this institution"
        raise ValidationError(msg)
    return normalized
