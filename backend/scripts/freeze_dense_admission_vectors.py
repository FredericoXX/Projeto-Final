"""Congela os vetores das perguntas do dataset de admissão (D4.8.2a).

Uso (a partir de ``backend/``, com o virtual environment ativo):

    python -m scripts.freeze_dense_admission_vectors \
        --dataset ../docs/evaluation/dense-admission-dataset-v1.json \
        --output ../docs/evaluation/dense-admission-frozen-vectors-v1.json \
        [--overwrite]

**É o único comando desta fase que contacta o fornecedor de embeddings.** Corre
uma vez; a calibração e a avaliação leem o ficheiro que ele escreve.

Porque é que os vetores são congelados
--------------------------------------

A D4.8 mediu (§8.1) que embeber o **mesmo** texto com o **mesmo** modelo produz
vetores diferentes entre chamadas, na ordem de 1e-4 na similaridade do cosseno;
a D4.8.1 voltou a medi-lo no embedding da pergunta, com desvio até 1,78e-3. Uma
regra de admissão compara similaridades com um limiar. Se o vetor da pergunta
mudasse a cada execução, uma pergunta perto do limiar podia ser admitida numa
execução e recusada na seguinte, e a experiência deixaria de ter decisões
reprodutíveis — que é precisamente o que ela se propõe medir.

Congelar não é uma otimização de custo. É a condição para que «a política
decidiu X nesta pergunta» seja uma afirmação estável.

O que fica guardado, e porquê tudo isso
---------------------------------------

Cada vetor viaja com a identidade **completa** do modelo, o SHA-256 do texto
efetivamente embebido e o digest do próprio vetor. Os três respondem a perguntas
diferentes, e nenhum substitui os outros:

- a identidade diz **que modelo e que configuração** produziram o vetor — dois
  modelos produzem vetores da mesma dimensão que não são comparáveis;
- o ``content_sha256`` diz **sobre que texto** — é o que apanha a pergunta
  editada depois de embebida, caso em que tudo parece consistente e o vetor
  descreve outra coisa;
- o ``vector_digest`` diz que o vetor **não foi alterado** depois de escrito.

O ficheiro guarda também o vetor em bruto, porque sem ele não há execução
possível sem voltar ao fornecedor.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from app.evaluation.dense_admission import frozen_vectors_digest
from app.evaluation.dense_admission_vectors import (
    content_sha256,
    vector_digest,
    verify_frozen_vectors,
)
from scripts.embed_pilot_corpus import DEFAULT_EMBEDDING_MODEL
from scripts.evaluate_retrieval_experiment import (
    EXIT_BASELINE_MISMATCH,
    EXIT_OK,
    EXIT_OUTPUT_EXISTS,
    ExperimentError,
    _load_json,
)

FREEZE_VERSION: Final = "d4.8.2a-frozen-question-vectors-1"

#: Lote enviado ao fornecedor. Pequeno porque o conjunto é pequeno: agrupar mais
#: não muda nada aqui e agrupar menos multiplicaria chamadas sem razão.
BATCH_SIZE: Final = 16


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except ExperimentError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.exit_code


def _run(args: argparse.Namespace) -> int:
    if args.output.exists() and not args.overwrite:
        raise ExperimentError(
            f"refusing to overwrite {args.output} without --overwrite",
            EXIT_OUTPUT_EXISTS,
        )

    dataset = _load_json(args.dataset)
    questions = dataset["questions"]
    if not questions:
        raise ExperimentError("the dataset has no questions", EXIT_BASELINE_MISMATCH)

    from app.embeddings.dependencies import get_embedding_model

    embedding_model = get_embedding_model(args.embedding_model)
    identity = embedding_model.identity

    texts = [str(question["question"]) for question in questions]
    vectors: list[tuple[float, ...]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        produced = embedding_model.embed(batch)
        if len(produced) != len(batch):
            raise ExperimentError(
                "the embedding model returned a different number of vectors than "
                "the number of texts sent",
                EXIT_BASELINE_MISMATCH,
            )
        vectors.extend(produced)

    entries: list[dict[str, Any]] = []
    for question, vector in zip(questions, vectors, strict=True):
        values = [float(component) for component in vector]
        entries.append(
            {
                "question_id": question["question_id"],
                "content_sha256": content_sha256(str(question["question"])),
                "provider": identity.provider,
                "model": identity.model,
                "dimension": identity.dimension,
                "normalization": identity.normalization,
                "similarity_metric": identity.similarity_metric,
                "configuration_version": identity.configuration_version,
                "vector_digest": vector_digest(values),
                "vector": values,
            }
        )
    entries.sort(key=lambda entry: str(entry["question_id"]))

    # O que se acabou de escrever tem de passar as guardas que quem lê vai
    # aplicar. Verificar aqui não é redundante: um ficheiro que só falhasse do
    # lado do leitor deixaria a suspeita entre o produtor e o consumidor.
    problems = verify_frozen_vectors(entries, questions, identity)
    if problems:
        raise ExperimentError(
            "the vectors just produced do not satisfy the frozen-vector guards: "
            + "; ".join(problems),
            EXIT_BASELINE_MISMATCH,
        )

    payload: dict[str, Any] = {
        "schema_version": "1",
        "contract": "dense_admission_frozen_vectors",
        "freeze_version": FREEZE_VERSION,
        "dataset_version": dataset["dataset_version"],
        "scope_note": (
            "Vetores das perguntas, congelados uma unica vez. A calibracao e a "
            "avaliacao NAO contactam o fornecedor: leem este ficheiro atraves de "
            "FrozenQuestionEmbeddings, que procura o vetor pelo SHA-256 do texto e "
            "levanta erro se o texto for desconhecido. E o que garante que nenhuma "
            "chamada nova ao fornecedor altera uma decisao de admissao."
        ),
        "embedding": {
            "provider": identity.provider,
            "model": identity.model,
            "dimension": identity.dimension,
            "normalization": identity.normalization,
            "similarity_metric": identity.similarity_metric,
            "configuration_version": identity.configuration_version,
        },
        "questions_frozen": len(entries),
        "vectors": entries,
    }
    payload["frozen_vectors_digest"] = frozen_vectors_digest(entries)
    payload["frozen_at"] = datetime.now(UTC).isoformat()

    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"perguntas vetorizadas : {len(entries)}")
    print(f"identidade            : {identity.provider}:{identity.model}")
    print(f"frozen_vectors_digest : {payload['frozen_vectors_digest']}")
    print(f"written               : {args.output}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
