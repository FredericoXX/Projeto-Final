"""Contratos de embeddings e o adapter OpenAI (D4.8).

Nenhum teste faz chamadas de rede nem exige ``OPENAI_API_KEY``: o cliente é
injetado. O que se fixa aqui é o que o adapter promete — ordem preservada,
dimensão verificada, erros sanitizados — e a fronteira de carregamento do SDK,
nas mesmas condições da A6.1.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.embeddings.base import (
    EMBEDDING_MODEL_UNAVAILABLE_MESSAGE,
    EmbeddingError,
    EmbeddingIdentity,
    EmbeddingModelUnavailableError,
)
from app.embeddings.providers.openai import (
    BATCH_SIZE,
    KNOWN_MODEL_DIMENSIONS,
    OpenAIEmbeddingModel,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEPENDENCIES_PATH = BACKEND_DIR / "app" / "embeddings" / "dependencies.py"
PROVIDER_MODULE = "app.embeddings.providers.openai"

MODEL = "text-embedding-3-small"
DIMENSION = KNOWN_MODEL_DIMENSIONS[MODEL]


# --- Anulação das fixtures de base de dados do conftest -------------------------


@pytest.fixture(scope="session", autouse=True)
def _override_get_db() -> None:
    """Anula a fixture homónima do conftest: aqui não há dependência de DB."""


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    """Anula a fixture homónima do conftest: aqui não há tabelas a truncar."""


# --- Duplos do SDK ---------------------------------------------------------------


class _Item:
    def __init__(self, index: int, embedding: list[float]) -> None:
        self.index = index
        self.embedding = embedding


class _Response:
    def __init__(self, data: list[Any]) -> None:
        self.data = data


class _Embeddings:
    def __init__(self, responder: Any) -> None:
        self._responder = responder
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._responder(kwargs)


class _Client:
    def __init__(self, responder: Any) -> None:
        self.embeddings = _Embeddings(responder)


def _vector(seed: float) -> list[float]:
    return [seed] * DIMENSION


def _ordered_responder(payload: dict[str, Any]) -> _Response:
    return _Response(
        [_Item(index, _vector(float(index))) for index in range(len(payload["input"]))]
    )


# --- Identidade ------------------------------------------------------------------


def test_identity_rejects_a_non_positive_dimension() -> None:
    """Um vetor de dimensão zero não é um vetor; falha na construção."""
    with pytest.raises(ValueError, match="dimension must be positive"):
        EmbeddingIdentity(
            provider="fake",
            model="fake",
            dimension=0,
            normalization="none",
            similarity_metric="cosine",
            configuration_version="v1",
        )


def test_the_adapter_declares_the_full_identity_before_embedding_anything() -> None:
    """A indexação precisa da identidade antes de existir vetor nenhum."""
    model = OpenAIEmbeddingModel(model=MODEL, client=_Client(_ordered_responder))

    identity = model.identity
    assert identity.provider == "openai"
    assert identity.model == MODEL
    assert identity.dimension == DIMENSION
    assert identity.similarity_metric == "cosine"
    # A aplicação não normaliza: declarar "l2_unit" seria falso sobre o que fica
    # guardado, mesmo que o fornecedor devolva vetores de norma ~1.
    assert identity.normalization == "none"
    assert identity.configuration_version == "openai_embeddings_v1"
    assert model.identity is identity


@pytest.mark.parametrize("model", [None, "", "text-embedding-unknown-9"])
def test_an_unusable_model_is_refused_at_construction(model: str | None) -> None:
    """Falha já, e não a meio de uma indexação de milhares de segmentos."""
    with pytest.raises(EmbeddingModelUnavailableError) as info:
        OpenAIEmbeddingModel(model=model, client=_Client(_ordered_responder))
    assert str(info.value) == EMBEDDING_MODEL_UNAVAILABLE_MESSAGE


# --- Ordem, dimensão e integridade da resposta -----------------------------------


def test_vectors_come_back_in_the_order_the_texts_were_given() -> None:
    model = OpenAIEmbeddingModel(model=MODEL, client=_Client(_ordered_responder))

    vectors = model.embed(["a", "b", "c"])

    assert [vector[0] for vector in vectors] == [0.0, 1.0, 2.0]
    assert all(isinstance(vector, tuple) for vector in vectors)


def test_a_shuffled_response_is_reordered_by_index_and_not_by_arrival() -> None:
    """A correspondência texto ↔ vetor não pode depender da ordem de chegada.

    Uma troca silenciosa produziria um índice plausível e completamente errado:
    cada segmento ficaria com o vetor de outro, e nada falharia.
    """

    def shuffled(payload: dict[str, Any]) -> _Response:
        count = len(payload["input"])
        items = [_Item(index, _vector(float(index))) for index in range(count)]
        return _Response(list(reversed(items)))

    model = OpenAIEmbeddingModel(model=MODEL, client=_Client(shuffled))

    vectors = model.embed(["a", "b", "c"])

    assert [vector[0] for vector in vectors] == [0.0, 1.0, 2.0]


def test_a_vector_of_the_wrong_width_is_refused() -> None:
    """Um modelo que mude de largura falha em vez de contaminar o índice."""

    def narrow(payload: dict[str, Any]) -> _Response:
        return _Response([_Item(0, [0.5] * (DIMENSION - 1))])

    model = OpenAIEmbeddingModel(model=MODEL, client=_Client(narrow))

    with pytest.raises(EmbeddingError):
        model.embed(["a"])


def test_a_response_with_the_wrong_number_of_vectors_is_refused() -> None:
    def truncated(payload: dict[str, Any]) -> _Response:
        return _Response([_Item(0, _vector(0.0))])

    model = OpenAIEmbeddingModel(model=MODEL, client=_Client(truncated))

    with pytest.raises(EmbeddingError):
        model.embed(["a", "b"])


def test_a_response_with_repeated_indices_is_refused() -> None:
    """Índices repetidos deixariam um texto sem vetor e outro com dois."""

    def repeated(payload: dict[str, Any]) -> _Response:
        return _Response([_Item(0, _vector(0.0)), _Item(0, _vector(1.0))])

    model = OpenAIEmbeddingModel(model=MODEL, client=_Client(repeated))

    with pytest.raises(EmbeddingError):
        model.embed(["a", "b"])


def test_a_response_without_data_is_refused() -> None:
    class _NoData:
        pass

    model = OpenAIEmbeddingModel(
        model=MODEL, client=_Client(lambda payload: _NoData())
    )

    with pytest.raises(EmbeddingError):
        model.embed(["a"])


def test_a_non_numeric_component_is_refused() -> None:
    def textual(payload: dict[str, Any]) -> _Response:
        # Ignorado por mypy de propósito: o ponto do teste é exatamente o que o
        # tipo declarado proíbe e um fornecedor real pode devolver.
        components: list[Any] = ["nao numerico", *([0.0] * (DIMENSION - 1))]
        return _Response([_Item(0, components)])

    model = OpenAIEmbeddingModel(model=MODEL, client=_Client(textual))

    with pytest.raises(EmbeddingError):
        model.embed(["a"])


def test_an_empty_input_never_reaches_the_provider() -> None:
    client = _Client(_ordered_responder)
    model = OpenAIEmbeddingModel(model=MODEL, client=client)

    assert model.embed([]) == ()
    assert client.embeddings.calls == []


# --- Lotes -----------------------------------------------------------------------


def test_large_inputs_are_split_into_batches_without_losing_order() -> None:
    """O agrupamento é do adapter; o consumidor entrega a lista inteira."""
    client = _Client(_ordered_responder)
    model = OpenAIEmbeddingModel(model=MODEL, client=client)
    texts = [f"texto {index}" for index in range(BATCH_SIZE + 3)]

    vectors = model.embed(texts)

    assert len(vectors) == len(texts)
    assert len(client.embeddings.calls) == 2
    assert len(client.embeddings.calls[0]["input"]) == BATCH_SIZE
    assert len(client.embeddings.calls[1]["input"]) == 3
    # Cada lote reinicia a contagem de índices, e o adapter concatena-os pela
    # ordem dos lotes: o vetor 129 é o terceiro do segundo lote.
    assert [vector[0] for vector in vectors[BATCH_SIZE:]] == [0.0, 1.0, 2.0]


def test_the_request_pins_the_model_and_the_encoding_format() -> None:
    """O formato de codificação faz parte da configuração, não é um default."""
    client = _Client(_ordered_responder)
    model = OpenAIEmbeddingModel(model=MODEL, client=client)

    model.embed(["a"])

    call = client.embeddings.calls[0]
    assert call["model"] == MODEL
    assert call["encoding_format"] == "float"
    assert call["input"] == ["a"]


# --- Sanitização de erros --------------------------------------------------------


def test_a_provider_error_never_leaks_the_text_or_the_provider_type() -> None:
    """A mensagem que sai é curta e fixa, como no adapter de geração."""
    import openai

    secret = "conteudo institucional que nao pode aparecer"

    def failing(payload: dict[str, Any]) -> Any:
        raise openai.APIError(
            f"boom {secret}", request=None, body=None  # type: ignore[arg-type]
        )

    model = OpenAIEmbeddingModel(model=MODEL, client=_Client(failing))

    with pytest.raises(EmbeddingError) as info:
        model.embed([secret])

    message = str(info.value)
    assert secret not in message
    assert "openai" not in message.lower()
    assert info.value.__cause__ is None


def test_an_unexpected_error_receives_the_same_sanitisation() -> None:
    def exploding(payload: dict[str, Any]) -> Any:
        raise RuntimeError("detalhe interno com a chave sk-secreta")

    model = OpenAIEmbeddingModel(model=MODEL, client=_Client(exploding))

    with pytest.raises(EmbeddingError) as info:
        model.embed(["a"])

    assert "sk-secreta" not in str(info.value)


def test_without_a_key_the_model_is_unavailable_rather_than_failing_obscurely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "openai_api_key", None)
    model = OpenAIEmbeddingModel(model=MODEL)

    with pytest.raises(EmbeddingModelUnavailableError):
        model.embed(["a"])


# --- Fronteira de carregamento do SDK --------------------------------------------


def _run_probe(snippet: str, **environment_overrides: str) -> str:
    environment = dict(os.environ)
    environment.update(environment_overrides)
    environment["PYTHONPATH"] = str(BACKEND_DIR)

    result = subprocess.run(  # noqa: S603 - comando fixo, sem entrada externa
        [sys.executable, "-c", snippet],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


_NEUTRAL_CONTRACTS_SNIPPET = """
import sys

import app.embeddings

assert "openai" not in sys.modules, "os contratos neutros carregaram o SDK"
print("ok")
"""


def test_the_neutral_contracts_do_not_load_the_provider_sdk() -> None:
    """A mesma propriedade que a A6.1 fixou para a geração de respostas."""
    assert "ok" in _run_probe(_NEUTRAL_CONTRACTS_SNIPPET)


_UNKNOWN_PROVIDER_SNIPPET = """
import sys

from app.embeddings.base import EmbeddingModelUnavailableError
from app.embeddings.dependencies import get_embedding_model

try:
    get_embedding_model()
except EmbeddingModelUnavailableError:
    pass
else:
    raise SystemExit("um provider desconhecido devolveu um modelo utilizavel")

assert "openai" not in sys.modules, "um provider desconhecido carregou o SDK"
print("ok")
"""


def test_an_unknown_provider_fails_without_loading_the_provider_sdk() -> None:
    assert "ok" in _run_probe(
        _UNKNOWN_PROVIDER_SNIPPET, EMBEDDING_PROVIDER="offline-disabled"
    )


def test_the_package_does_not_reexport_the_composition_root() -> None:
    import app.embeddings as embeddings_package

    assert "get_embedding_model" not in embeddings_package.__all__
    assert not hasattr(embeddings_package, "get_embedding_model")


def _module_level_imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_the_adapter_is_imported_inside_the_branch_that_instantiates_it() -> None:
    """Propriedade estrutural: um import no topo reporia o carregamento eager."""
    tree = ast.parse(DEPENDENCIES_PATH.read_text(encoding="utf-8"))

    top_level = _module_level_imported_names(tree)
    assert PROVIDER_MODULE not in top_level
    assert not any(name.split(".")[0] == "openai" for name in top_level)

    factory = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_embedding_model"
    )
    provider_imports = [
        node
        for node in ast.walk(factory)
        if isinstance(node, ast.ImportFrom) and node.module == PROVIDER_MODULE
    ]
    assert len(provider_imports) == 1


def test_the_unavailable_message_lives_in_the_contract_and_is_not_duplicated() -> None:
    from app.embeddings.providers import openai as provider_module

    assert (
        provider_module.EMBEDDING_MODEL_UNAVAILABLE_MESSAGE
        is EMBEDDING_MODEL_UNAVAILABLE_MESSAGE
    )
    provider_source = (
        BACKEND_DIR / "app" / "embeddings" / "providers" / "openai.py"
    ).read_text(encoding="utf-8")
    assert "EMBEDDING_MODEL_UNAVAILABLE_MESSAGE = " not in provider_source
