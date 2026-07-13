"""Construção do contexto documental que alimenta o gerador.

Cada evidência recebe um identificador estável dentro do pedido (E1, E2,
...), pela ordem do ranking do retriever. Todo o conteúdo não confiável
(títulos, URLs, conteúdo dos chunks) é enviado ao modelo como valores de
uma estrutura JSON produzida por json.dumps — nunca por concatenação com
delimitadores textuais, que um documento malicioso poderia imitar para
"fechar" a zona de dados. O conteúdo original nunca é alterado no objeto
interno; campos internos (normalized_content, search_vector,
storage_path, institution_id, checksums) nunca entram no contexto.

A serialização estruturada reduz ambiguidades de fronteira e impede que
o conteúdo documental altere sintaticamente a estrutura construída pela
aplicação. O conteúdo continua a ser tratado como não confiável e
sujeito às instruções de isolamento do prompt.
"""

import json
from collections.abc import Sequence

from app.answering.base import ContextEvidence
from app.retrieval.base import Evidence


def evidence_payload(entry: ContextEvidence) -> dict:
    """Representação JSON-safe de uma evidência: apenas metadados públicos
    e o conteúdo original do chunk, sempre como valores (nunca estrutura)."""
    evidence = entry.evidence
    return {
        "evidence_id": entry.evidence_id,
        "document_title": evidence.document_title,
        "source_url": evidence.source_url,
        "official_source": evidence.official_source,
        "content": evidence.content,
    }


def context_payload(
    entries: Sequence[ContextEvidence],
    *,
    query: str,
    language: str,
    institution_name: str,
) -> dict:
    """Envelope completo de dados enviado ao modelo."""
    return {
        "institution_name": institution_name,
        "question": query,
        "language": language,
        "evidence": [evidence_payload(entry) for entry in entries],
    }


def serialize_context_payload(
    entries: Sequence[ContextEvidence],
    *,
    query: str,
    language: str,
    institution_name: str,
) -> str:
    """Serializa exatamente o JSON usado como mensagem do utilizador."""
    return json.dumps(
        context_payload(
            entries,
            query=query,
            language=language,
            institution_name=institution_name,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def select_evidence(
    evidence: Sequence[Evidence],
    max_context_chars: int,
    *,
    query: str = "",
    language: str = "",
    institution_name: str = "",
) -> tuple[ContextEvidence, ...]:
    """Seleciona evidências completas, pela ordem do ranking, até ao limite.

    Regras:
    - chunks duplicados (mesmo chunk_id) nunca entram duas vezes;
    - só entram evidências cuja serialização completa caiba no limite —
      nunca se trunca JSON nem se corta um chunk a meio;
    - exceção documentada: a melhor evidência entra sempre, mesmo que a
      sua serialização exceda sozinha max_context_chars — sem ela não
      haveria contexto nenhum e o pedido regrediria para fallback com
      evidências encontradas;
    - a numeração E1, E2, ... segue a ordem de entrada no contexto.
    """
    selected: list[ContextEvidence] = []
    seen_chunk_ids = set()

    for candidate in evidence:
        if candidate.chunk_id in seen_chunk_ids:
            continue
        entry = ContextEvidence(
            evidence_id=f"E{len(selected) + 1}",
            evidence=candidate,
        )
        candidate_selection = (*selected, entry)
        serialized_chars = len(
            serialize_context_payload(
                candidate_selection,
                query=query,
                language=language,
                institution_name=institution_name,
            )
        )
        if selected and serialized_chars > max_context_chars:
            # Limite atingido: para de adicionar (a ordem do ranking já
            # garantiu que ficam as melhores evidências).
            break
        selected.append(entry)
        seen_chunk_ids.add(candidate.chunk_id)

    return tuple(selected)
