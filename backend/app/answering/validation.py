"""Validação determinística da resposta gerada.

Nenhum segundo LLM valida a saída nesta etapa: todas as regras são
verificáveis deterministicamente. Uma violação rejeita a geração por
inteiro (InvalidGeneratedAnswerError) — nunca se adivinha a fonte nem se
devolve a resposta como answered.

Os motivos de rejeição são códigos estáveis controlados pela aplicação
(REASON_*): nunca incluem valores devolvidos pelo fornecedor (IDs,
resposta, citações), porque esse conteúdo é não confiável e não pode
chegar aos logs.
"""

from collections.abc import Collection

from app.answering.base import GeneratedAnswer, InvalidGeneratedAnswerError

# Mensagem única e segura para o exterior; o código estável do motivo
# fica em reason_code, apenas para os logs do chamador.
INVALID_ANSWER_MESSAGE = "The generated answer failed validation and was rejected."

REASON_EMPTY_ANSWER = "empty_answer"
REASON_ANSWER_TOO_LONG = "answer_too_long"
REASON_MISSING_CITATIONS = "missing_citations"
REASON_DUPLICATE_EVIDENCE_IDS = "duplicate_evidence_ids"
REASON_UNKNOWN_EVIDENCE_IDS = "unknown_evidence_ids"


def validate_generated_answer(
    generated: GeneratedAnswer,
    allowed_evidence_ids: Collection[str],
    max_answer_chars: int,
) -> tuple[str, ...]:
    """Valida a resposta e devolve as citações pela ordem em que o gerador
    as citou (é essa a ordem das sources na resposta pública).

    Rejeita: answer vazio ou só com espaços; answer acima do limite;
    lista de citações vazia (uma resposta answered exige pelo menos uma
    fonte); IDs duplicados; qualquer ID que não exista no contexto.
    """
    if not generated.answer or not generated.answer.strip():
        raise InvalidGeneratedAnswerError(INVALID_ANSWER_MESSAGE, REASON_EMPTY_ANSWER)
    if len(generated.answer) > max_answer_chars:
        raise InvalidGeneratedAnswerError(INVALID_ANSWER_MESSAGE, REASON_ANSWER_TOO_LONG)
    if not generated.cited_evidence_ids:
        raise InvalidGeneratedAnswerError(INVALID_ANSWER_MESSAGE, REASON_MISSING_CITATIONS)
    if len(set(generated.cited_evidence_ids)) != len(generated.cited_evidence_ids):
        raise InvalidGeneratedAnswerError(
            INVALID_ANSWER_MESSAGE, REASON_DUPLICATE_EVIDENCE_IDS
        )

    invalid_count = sum(
        1
        for evidence_id in generated.cited_evidence_ids
        if evidence_id not in allowed_evidence_ids
    )
    if invalid_count:
        # IDs inventados (ex.: E3 quando só existem E1 e E2) rejeitam a
        # geração. Só a contagem é preservada — os valores vêm do
        # fornecedor e nunca entram na exceção nem nos logs.
        raise InvalidGeneratedAnswerError(
            INVALID_ANSWER_MESSAGE,
            REASON_UNKNOWN_EVIDENCE_IDS,
            invalid_count=invalid_count,
        )

    return tuple(generated.cited_evidence_ids)
