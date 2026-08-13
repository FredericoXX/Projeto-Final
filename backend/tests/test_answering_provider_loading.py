"""O SDK do fornecedor só é carregado quando o fornecedor é resolvido.

Antes da A6.1, `app/answering/__init__.py` reexportava a factory, que
importava o adapter no topo do módulo: importar qualquer coisa sob
`app.answering.*` — incluindo os contratos neutros de `base.py` — puxava
o SDK da OpenAI, mesmo com outro provider configurado ou nenhum.

As propriedades ficam fixadas em **subprocessos limpos**: dentro do
processo do pytest o SDK já foi importado por `test_answering_openai.py`,
pelo que `sys.modules` aqui não prova nada. Nenhum teste faz chamadas de
rede nem exige `OPENAI_API_KEY`.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.answering.base import GENERATOR_UNAVAILABLE_MESSAGE

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEPENDENCIES_PATH = BACKEND_DIR / "app" / "answering" / "dependencies.py"
PROVIDER_MODULE = "app.answering.providers.openai"


# --- Anulação das fixtures de base de dados do conftest -------------------------


@pytest.fixture(scope="session", autouse=True)
def _override_get_db() -> None:
    """Anula a fixture homónima do conftest: aqui não há dependência de DB."""


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    """Anula a fixture homónima do conftest: aqui não há tabelas a truncar."""


def _run_probe(snippet: str, **environment_overrides: str) -> str:
    """Corre uma sonda de import num interpretador limpo.

    O ambiente do processo atual é herdado (as Settings precisam da
    configuração de base de dados para validar), com as substituições
    pedidas por cima. As variáveis de ambiente precedem o `env_file` na
    resolução das Settings, por isso a substituição é efetiva mesmo com
    um `.env` presente na raiz do repositório.
    """
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


# --- Sondas de import -----------------------------------------------------------


_NEUTRAL_CONTRACTS_SNIPPET = """
import sys

import app.answering.base

assert "openai" not in sys.modules, "os contratos neutros carregaram o SDK"
print("ok")
"""


def test_neutral_contracts_are_importable_without_the_provider_sdk() -> None:
    """`app.answering.base` não conhece fornecedor — nem por efeito colateral.

    Esta é a propriedade que dá conteúdo à afirmação de que o contrato é
    neutro: não basta o módulo não declarar `import openai`, é preciso
    que importá-lo não carregue o SDK.
    """
    assert "ok" in _run_probe(_NEUTRAL_CONTRACTS_SNIPPET)


_APPLICATION_SNIPPET = """
import sys

from app.main import app

assert app.title, "a aplicacao nao se construiu"
assert "openai" not in sys.modules, "o arranque da aplicacao carregou o SDK"
print("ok")
"""


def test_application_is_importable_without_the_provider_sdk() -> None:
    """Construir a aplicação não carrega o SDK.

    O FastAPI resolve `Depends(get_answer_generator)` por pedido, não no
    import, pelo que a aplicação inteira — rotas de answering incluídas —
    se constrói sem o fornecedor.
    """
    assert "ok" in _run_probe(_APPLICATION_SNIPPET)


_UNKNOWN_PROVIDER_SNIPPET = """
import sys

from app.answering.base import AnswerGeneratorUnavailableError
from app.answering.dependencies import get_answer_generator

try:
    get_answer_generator()
except AnswerGeneratorUnavailableError as exc:
    assert str(exc) == "Answer generation is not configured on this server."
else:
    raise SystemExit("um provider desconhecido devolveu um gerador utilizavel")

assert "openai" not in sys.modules, "um provider desconhecido carregou o SDK"
print("ok")
"""


def test_unknown_provider_fails_without_loading_the_provider_sdk() -> None:
    """Provider desconhecido → indisponível (503), e sem pagar o SDK.

    Este era o custo concreto: `scripts/evaluate_answering_offline.py`
    define deliberadamente um provider que nenhum adapter reconhece e,
    ainda assim, o processo carregava o SDK inteiro.
    """
    output = _run_probe(
        _UNKNOWN_PROVIDER_SNIPPET,
        ANSWER_GENERATOR_PROVIDER="offline-disabled",
    )
    assert "ok" in output


_CONFIGURED_PROVIDER_SNIPPET = """
import sys

from app.answering.dependencies import get_answer_generator

assert "openai" not in sys.modules, "o SDK foi carregado antes de resolver o provider"

generator = get_answer_generator()

assert type(generator).__name__ == "OpenAIAnswerGenerator", type(generator).__name__
assert "openai" in sys.modules, "o adapter foi resolvido sem carregar o SDK"
print("ok")
"""


def test_configured_provider_still_resolves_and_only_then_loads_the_sdk() -> None:
    """O import tardio não partiu a resolução: adia-a, apenas.

    Com `openai` configurado, a factory continua a devolver o adapter
    real — e o SDK entra em `sys.modules` exatamente nesse momento, não
    antes. Sem chave: instanciar o adapter não constrói cliente nenhum.
    """
    output = _run_probe(
        _CONFIGURED_PROVIDER_SNIPPET,
        ANSWER_GENERATOR_PROVIDER="openai",
    )
    assert "ok" in output


# --- Estrutura que sustenta as propriedades acima --------------------------------


def test_package_does_not_reexport_the_composition_root() -> None:
    """O `__init__` do pacote exporta contratos, não a factory.

    O carregamento tardio é garantido em `dependencies.py`; esta asserção
    protege separadamente a fronteira pública entre contratos e composição.
    """
    import app.answering as answering_package

    assert "get_answer_generator" not in answering_package.__all__
    assert not hasattr(answering_package, "get_answer_generator")


def _module_level_imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_the_provider_adapter_is_imported_inside_the_branch_that_uses_it() -> None:
    """A propriedade é estrutural, não uma coincidência de execução.

    Um import do adapter no topo de `dependencies.py` reporia o
    carregamento antecipado sem quebrar nenhum comportamento — as sondas
    de import apanhariam-no, mas só em subprocesso. Este teste falha
    imediatamente e diz porquê.
    """
    tree = ast.parse(DEPENDENCIES_PATH.read_text(encoding="utf-8"))

    top_level = _module_level_imported_names(tree)
    assert PROVIDER_MODULE not in top_level
    assert not any(name.split(".")[0] == "openai" for name in top_level)

    factory = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_answer_generator"
    )
    provider_imports = [
        node
        for node in ast.walk(factory)
        if isinstance(node, ast.ImportFrom) and node.module == PROVIDER_MODULE
    ]
    assert len(provider_imports) == 1


def test_the_unavailable_message_is_shared_and_not_duplicated() -> None:
    """A factory e o adapter falham com a mesma mensagem, do mesmo sítio.

    A mensagem passou para `base.py` precisamente para que a factory a
    pudesse usar sem importar o adapter. Se voltasse a ser definida no
    adapter, ou divergisse, o corpo do 503 deixaria de ser único.
    """
    from app.answering.providers import openai as provider_module

    assert provider_module.GENERATOR_UNAVAILABLE_MESSAGE is GENERATOR_UNAVAILABLE_MESSAGE
    assert GENERATOR_UNAVAILABLE_MESSAGE == (
        "Answer generation is not configured on this server."
    )

    provider_source = (
        BACKEND_DIR / "app" / "answering" / "providers" / "openai.py"
    ).read_text(encoding="utf-8")
    assert "GENERATOR_UNAVAILABLE_MESSAGE = " not in provider_source
