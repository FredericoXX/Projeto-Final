# A6.0 — Caracterização da independência de fornecedor e modelo

**Observação:** 2026-08-12 · `main` em `d6dd75bd8aa6a802d6850018803eb4c91ec92f97`
· repositório `FredericoXX/Projeto-Final`

**Natureza:** caracterização e modelação arquitetural. Não altera comportamento,
não implementa fornecedores nem abstrações. Nenhum ficheiro de produção foi
tocado para produzir este documento.

## VEREDITO

```
A6.0: PRONTA PARA REVISÃO
```

## Pergunta central

> Até que ponto o answering é atualmente independente do fornecedor e do modelo,
> e qual é a menor alteração arquitetural necessária — se alguma — para tornar
> essa substituibilidade real sem criar abstração especulativa?

Resposta curta: **o contrato é neutro e o adapter está corretamente isolado; o
que não é neutro é o carregamento.** O SDK da OpenAI é importado por qualquer
consumidor dos contratos de answering, independentemente do fornecedor
configurado, porque `app/answering/__init__.py` reexporta a composition root.

---

## 1. Estado atual

### 1.1 Contrato de geração — `app/answering/base.py`

```python
class AnswerGenerator(Protocol):
    def generate(self, context: AnsweringContext) -> GeneratedAnswer: ...
```

```python
@dataclass(frozen=True)
class AnsweringContext:
    query: str
    language: str
    institution_name: str
    evidence: tuple[ContextEvidence, ...]
    max_context_chars: int


@dataclass(frozen=True)
class GeneratedAnswer:
    answer: str
    cited_evidence_ids: tuple[str, ...]
```

O módulo importa exatamente dois pacotes internos — `app.core.exceptions` e
`app.retrieval.base` — e nenhum SDK. Nenhum campo nomeia fornecedor, modelo,
tokens, temperatura, custo ou latência.

### 1.2 Composition root — `app/answering/dependencies.py` (19 linhas)

```python
from app.answering.providers.openai import (
    GENERATOR_UNAVAILABLE_MESSAGE,
    OpenAIAnswerGenerator,
)

def get_answer_generator() -> AnswerGenerator:
    if settings.answer_generator_provider == "openai":
        return OpenAIAnswerGenerator()
    raise AnswerGeneratorUnavailableError(GENERATOR_UNAVAILABLE_MESSAGE)
```

Resolver o provider **nunca falha por falta de credenciais**: a chave só é
exigida quando o cliente é construído, na primeira geração real. Um provider
desconhecido falha aqui, com 503, e nunca no arranque.

### 1.3 Adapter — `app/answering/providers/openai.py` (149 linhas)

Único módulo de produção que faz `import openai`. Contém o modelo
(`settings.openai_model`), a chave, o timeout, a política de retries
(`max_retries=0`, decisão explícita da aplicação), o `response_format` em
`json_schema` e o parsing defensivo da resposta.

### 1.4 Settings — `app/core/config.py`

```python
answer_generator_provider: str = "openai"
answering_default_top_k: int = 5
answering_max_top_k: int = 10
answering_max_context_chars: int = 12000
answering_max_answer_chars: int = 4000

openai_api_key: str | None = None
openai_model: str | None = None
openai_timeout_seconds: int = 30
```

### 1.5 Instalação

`backend/requirements.txt`, linha 18: `openai==2.45.0`, sem condição. O
`backend/pyproject.toml` **não declara um bloco `[project]`** — só configura
`ruff` e `pytest` — pelo que não existe hoje nenhum mecanismo de extras. A CI
(`.github/workflows/backend-checks.yml`) faz `pip install -r requirements.txt`.

---

## 2. Grafo de dependências real

```
api/routes/answering.py        api/routes/conversations.py
        │                              │
        │  Depends(get_answer_generator)
        ▼                              ▼
services/answering_service.py   services/conversation_answering_service.py
        │
        │  usa apenas o Protocol
        ▼
answering/base.py  ── AnswerGenerator · AnsweringContext · GeneratedAnswer
        ▲
        │  implementado (estruturalmente) por
        │
answering/providers/openai.py ──────────────► openai SDK
        ▲
        │  instanciado por
        │
answering/dependencies.py  ── get_answer_generator()
        ▲
        │  reexportado por  ◄── ponto crítico
        │
answering/__init__.py
```

A última aresta é a que importa. `app/answering/__init__.py` faz
`from app.answering.dependencies import get_answer_generator`, e por isso
**importar qualquer módulo sob `app.answering.*` executa o `__init__` do pacote e
carrega o SDK** — mesmo que o consumidor só queira os contratos neutros.

---

## 3. Fronteiras por camada

| Camada | Conhece OpenAI? | Deveria conhecer? |
| --- | --- | --- |
| `api/routes/answering.py`, `conversations.py` | não | não |
| `services/answering_service.py`, `conversation_answering_service.py` | não por import próprio; **sim transitivamente** | não |
| `answering/base.py` | não | não |
| `answering/prompts.py`, `context.py`, `validation.py`, `fallback.py` | não | não |
| `answering/dependencies.py` | **sim** | **sim** — é a composition root |
| `answering/providers/openai.py` | **sim** | **sim** — é o adapter |
| `core/config.py` | **sim** (3 settings + 1 validação) | sim, com ressalva (ver F5) |
| `evaluation/` | não por import próprio; **sim transitivamente** | não |
| `diagnostics/` | não — e há teste que o fixa (`test_78`) | não |
| `schemas/`, `models/`, `alembic/`, `frontend/` | não | não |
| `tests/` | sim, em 3 módulos dedicados | sim |

A distinção "não por import próprio / sim transitivamente" não é uma
subtileza retórica: o docstring de `answering_service.py` afirma «não importa
SDKs de fornecedores», o que é literalmente verdade para as suas próprias
declarações `import`, e continua a ser falso quanto ao efeito de carregar esse
módulo.

---

## 4. Comportamento de import

Sondas executadas num interpretador limpo, sem rede e sem chamadas ao
fornecedor. Cada sonda importa um módulo e observa `sys.modules`.

```
import app.main                    → openai carregado: SIM   (778 submódulos)
import app.answering.base          → openai carregado: SIM
import app.services.answering_service → openai carregado: SIM
import app.evaluation.runner       → openai carregado: SIM
import app.evaluation.harness      → openai carregado: SIM
import app.evaluation.assets       → openai carregado: NÃO
import app.core.config             → openai carregado: NÃO
import app.retrieval.lexical       → openai carregado: NÃO
import app.api.routes.documents    → openai carregado: NÃO
```

Módulos de `app.answering` carregados por `import app.answering.base`:

```
app.answering
app.answering.base
app.answering.context
app.answering.dependencies      ◄── pelo __init__ do pacote
app.answering.prompts
app.answering.providers
app.answering.providers.openai  ◄── e daqui o SDK
```

Custo, medição única numa máquina de desenvolvimento (só a ordem de grandeza é
significativa):

| Import | Tempo |
| --- | ---: |
| `import openai` isolado | 2.515 s |
| `import app.retrieval.base` | 1.133 s |
| `import app.main` | 3.786 s |

Cerca de dois terços do tempo de import da aplicação é o SDK de um fornecedor
que pode nunca ser contactado — e que, nas suítes de teste e na avaliação
offline, nunca é.

---

## 5. Os quatro níveis

| Nível | Neutro hoje? | Evidência |
| --- | --- | --- |
| **L1 — contrato de geração** | **SIM** | `base.py` não importa SDK; `AnswerGenerator` é `Protocol` estrutural; oito módulos de teste implementam-no com classes próprias que não herdam de nada |
| **L2 — adapter** | **SIM** | `providers/openai.py` é o único módulo de produção com `import openai`; converte toda a exceção do SDK em erro interno |
| **L3 — composition root** | **PARCIAL** | conhecer um provider concreto é a função da composition root e está correto; o que não está é o import ser eager e o pacote reexportá-lo |
| **L4 — instalação/runtime** | **NÃO** | `openai==2.45.0` é dependência incondicional, sem extras; a CI instala-a sempre |

As duas perguntas do §24 e do §25 do enunciado têm, por isso, respostas
diferentes:

- **É possível implementar um gerador não-OpenAI sem alterar os contratos?**
  Sim, e já está provado empiricamente — ver §8.
- **É possível a aplicação funcionar com outro provider sem importar/instalar o
  SDK da OpenAI?** Não. Importar, não; instalar, também não.

---

## 6. Substituibilidade — o que seria preciso hoje

Ficheiros que precisariam de alteração para acrescentar um fornecedor `X`:

| Ficheiro | Alteração | Natureza |
| --- | --- | --- |
| `backend/requirements.txt` | acrescentar o SDK de `X` | dependência |
| `backend/app/answering/providers/x.py` | novo adapter | novo ficheiro |
| `backend/app/answering/dependencies.py` | um ramo `if` | composition root |
| `backend/app/core/config.py` | settings de `X` | configuração |
| `.env.example` | documentar as novas variáveis | configuração |
| `backend/tests/test_answering_x.py` | testes do adapter | novo ficheiro |
| `docs/answering.md` | registar o fornecedor suportado | documentação |

**Zero alterações** em `api/routes/`, `services/`, `schemas/`, `models/`,
`alembic/`, `frontend/`, `retrieval/` ou `decision/`. A superfície de mudança
está inteiramente na composition root e abaixo dela, que é onde deve estar.

---

## 7. Provider ≠ Model ≠ Estratégia

| Conceito | Onde vive hoje | Correto? |
| --- | --- | --- |
| provider | `settings.answer_generator_provider` + ramo em `dependencies.py` | sim |
| model | `settings.openai_model`, lido só em `OpenAIAnswerGenerator.generate` | sim |
| API key | `settings.openai_api_key`, lida só em `_build_client` | sim |
| timeout | `settings.openai_timeout_seconds` | sim, com ressalva (F5) |
| prompts | `answering/prompts.py`, neutro | sim |
| structured output | `_RESPONSE_FORMAT` em `providers/openai.py` | sim |
| error translation | `providers/openai.py` | sim |
| política de retries | `providers/openai.py` (`max_retries=0`) | sim |

Trocar `gpt-X` por `gpt-Y` é hoje uma alteração de **variável de ambiente**, sem
qualquer alteração de código: é configuração do adapter, não troca de provider.
A arquitetura atual não confunde os dois conceitos.

A **estratégia de geração** (resposta estruturada, validação adicional,
multi-step) também não está modelada como provider — e não deve passar a estar.
Hoje a estratégia está distribuída por `prompts.py` (instrução), `context.py`
(seleção e serialização de evidências) e `validation.py` (aceitação
determinística), todos neutros, e é isso que permite que uma estratégia futura
mude sem tocar em fornecedor nenhum.

---

## 8. Substituibilidade provada, não postulada

Não foi criado nenhum gerador novo para este relatório: a evidência já existe na
suíte. Oito módulos de teste substituem o gerador por
`app.dependency_overrides[get_answer_generator]`, com classes que implementam
apenas `generate(context) -> GeneratedAnswer`, não herdam de nada e não conhecem
fornecedor:

| Classe substituta | Ficheiro |
| --- | --- |
| `FakeAnswerGenerator` | `tests/test_answering_endpoint.py` |
| `FakeAnswerGenerator` (reutilizado) | `tests/test_conversation_lifecycle.py` |
| geradores locais | `tests/test_conversation_answering.py` |
| `_FirstEvidenceGenerator` | `tests/test_referenced_document_versions.py` |
| `RecordingAnswerGenerator` | `tests/test_message_source_uses_citation_persistence_eligibility.py` |
| geradores de caracterização | `tests/test_moment06_answering_characterisation.py`, `test_moment06_public_contracts_characterisation.py`, `test_moment06_evidence_eligibility_characterisation.py` |
| `FakeAnswerGenerator` do harness | `app/evaluation/harness.py` |

O serviço, a rota e os schemas nunca souberam que o gerador tinha mudado. **L1
está provado neutro por uso, não por asserção.**

---

## 9. Erros

| Falha | Exceção interna | HTTP | Tipo do fornecedor vaza? |
| --- | --- | ---: | --- |
| provider desconhecido | `AnswerGeneratorUnavailableError` | 503 `service_unavailable` | não |
| chave ausente | `AnswerGeneratorUnavailableError` | 503 | não |
| modelo ausente | `AnswerGeneratorUnavailableError` | 503 | não |
| erro do SDK (`openai.OpenAIError`, incl. timeout) | `AnswerGenerationError` | 502 `upstream_error` | não — `except openai.OpenAIError` + `from None` |
| erro inesperado durante a chamada | `AnswerGenerationError` | 502 | não — `except Exception` genérico |
| resposta sem `choices` / sem conteúdo / não-JSON / campos inválidos | `AnswerGenerationError` | 502 | não |
| citação de ID inexistente, resposta vazia ou longa demais | `InvalidGeneratedAnswerError` | 502 | não |

O adapter regista **apenas `type(exc).__name__`** e usa `from None`, para que a
exceção original não reapareça num traceback superior. Isto está fixado por
teste com sentinelas para chave, pergunta, conteúdo documental, cabeçalho de
autorização e resposta do fornecedor.

**Uma ressalva honesta (F4):** `_build_client()` é chamado **fora** do bloco
`try`. Se a construção do cliente levantasse, a exceção escaparia sem conversão.
Tentei construir um caso reprodutível e **não consegui**: com o `openai==2.45.0`
instalado, os pontos de `raise` do construtor exigem `provider=`,
`workload_identity=` ou uma chave vazia — e a chave vazia já está barrada pelo
`if not api_key` imediatamente antes. Uma sonda com `OPENAI_BASE_URL` malformado
construiu o cliente sem erro. É portanto uma **lacuna latente da fronteira**, não
uma fuga demonstrada, e não serve de justificação para mudar arquitetura.

---

## 10. Structured output

`_RESPONSE_FORMAT` usa `{"type": "json_schema", "strict": True}` — mecanismo
específico da OpenAI, inteiramente contido no adapter. `GeneratedAnswer` não o
conhece: é um par `(answer, cited_evidence_ids)`.

O ponto decisivo é que **o adapter não confia no structured output**.
`_parse_completion` revalida tudo: presença de `choices`, tipo do conteúdo, JSON
válido, `payload` ser um dicionário, `answer` ser `str`, `cited_evidence_ids` ser
`list`, e cada elemento ser `str`. Um fornecedor sem `json_schema` seria
implementável pedindo JSON na instrução e reutilizando exatamente este parsing.

**O contrato não depende da feature. Só o adapter a usa.**

---

## 11. Prompts

`app/answering/prompts.py` não importa SDK e devolve `(system_prompt,
user_prompt)` como duas strings. O mapeamento para `messages=[{"role":
"system"}, {"role": "user"}]` acontece no adapter, que é onde pertence.

A instrução de sistema é estática e deliberadamente agnóstica — a regra 8 chega a
proibir o modelo de mencionar «which provider or model generated the answer».

O único resíduo de forma é o par `(system, user)`, que assume uma API de chat com
instrução de sistema separada. É uma convenção partilhada pelos fornecedores
relevantes e, na prática, não constitui acoplamento. **Não recomendo mexer.**

---

## 12. Modelo e metadados experimentais

`settings.openai_model` é lido num único sítio: `OpenAIAnswerGenerator.generate`.
`AnswerGenerator` não expõe modelo, e `GeneratedAnswer` não transporta
`provider` nem `model`.

Isto está **correto para esta fase**. Nenhum consumidor operacional — rota,
service, validação, persistência de fontes — precisa de saber que modelo
respondeu, e acrescentar esses campos ao contrato runtime tornaria o domínio
dependente de um conceito de fornecedor que hoje não tem.

A necessidade científica é real mas é **outra**: uma experiência reprodutível tem
de registar provider, modelo, parâmetros e data. Isso é **metadado experimental**,
capturado pelo desenho da experiência — como a baseline do Momento 5 já faz com
`commit_sha` e `result_digest` — e não pertence a `GeneratedAnswer`. Decisão:
`DEFER` para o desenho experimental.

---

## 13. Cobertura de testes

| Comportamento | Teste existente? | Ficheiro |
| --- | --- | --- |
| adapter: caminho feliz e parsing | sim | `test_answering_openai.py` |
| adapter: modelo, roles e `response_format` enviados | sim | `test_answering_openai.py:95` |
| chave ausente → 503 | sim | `test_answering_openai.py:102`, `test_answering_endpoint.py:387` |
| modelo ausente → 503 | sim | `test_answering_openai.py:109` |
| provider desconhecido → 503 | **sim, mas indireto** | `test_evaluation_cli.py:314` (subprocesso) |
| timeout do SDK → 502 | sim | `test_answering_openai.py:118` |
| erro do SDK não vaza chave/pergunta/conteúdo | sim | `test_answering_openai.py:125` |
| erro inesperado → 502 seguro | sim | `test_answering_openai.py:176` |
| retries do SDK desligados | sim | `test_answering_openai.py:154` |
| respostas inutilizáveis rejeitadas (9 variantes) | sim | `test_answering_openai.py:183` |
| gerador falso substitui o provider | sim | 8 módulos, via `dependency_overrides` |
| aplicação arranca sem credenciais | sim | `test_moment06_answering_characterisation.py:205` |
| resposta HTTP nunca contém "openai" nem a chave | sim | `test_answering_endpoint.py:427`, `:450` |
| diagnóstico não importa nem constrói cliente OpenAI | sim | `test_document_pipeline_diagnostics.py:1512`, `:1518` |
| OCR não importa bibliotecas de rede/OpenAI | sim | `test_document_extraction_ocr.py:836` |
| avaliação offline não constrói o gerador real | sim | `test_evaluation_runner.py:594` |
| `app.evaluation.assets` valida sem carregar `openai` | sim | `test_evaluation_assets.py:775` |
| **`import app.main` não carrega o SDK** | **não** | — (e a propriedade **é falsa** hoje) |
| **contratos neutros importáveis sem o SDK** | **não** | — (falsa hoje) |
| **falha na construção do cliente não atravessa a fronteira** | **não** | — (F4, latente) |

A cobertura da fronteira é boa e tem uma assimetria clara: está exaustivamente
provado que o SDK **não é usado** onde não deve, e não está provado em lado
nenhum que **não é carregado**.

---

## 14. Achados

**F1 — `app/answering/__init__.py` reexporta a composition root.** *(architectural)*
`from app.answering.dependencies import get_answer_generator` no `__init__` faz
com que qualquer import sob `app.answering.*` carregue o adapter e o SDK. Nenhum
módulo do repositório consome esse reexport: a única importação a partir do
pacote é `from app.answering import dependencies`
(`test_evaluation_runner.py:593`), que continuaria a funcionar sem ele.

**F2 — o SDK é carregado mesmo quando o provider configurado não é OpenAI.** *(architectural)*
`scripts/evaluate_answering_offline.py` define deliberadamente
`ANSWER_GENERATOR_PROVIDER="offline-disabled"`, `OPENAI_API_KEY=""` e
`OPENAI_MODEL=""` antes do primeiro import — e o processo carrega, ainda assim,
os 778 módulos do SDK. É o critério explícito do §72 do enunciado, verificado.

**F3 — `openai` é dependência incondicional de instalação.** *(technical debt)*
`requirements.txt` linha 18, sem extras; `pyproject.toml` sem bloco `[project]`.
Não é possível instalar o backend sem o SDK.

**F4 — `_build_client()` está fora do `try` do adapter.** *(follow-up)*
Lacuna latente da fronteira de erros. Não consegui construir um caso reprodutível
com a versão instalada — ver §9.

**F5 — `openai_timeout_seconds` é validado no validador genérico.** *(follow-up)*
`check_answering_configuration` valida uma definição específica do adapter, ao
lado das definições neutras de answering. Acoplamento cosmético, sem efeito
funcional.

**F6 — o ramo "provider desconhecido" da composition root não tem teste próprio.** *(follow-up)*
Está coberto, mas como asserção lateral do subprocesso de isolamento do CLI de
avaliação (`test_evaluation_cli.py:314`). Um teste unitário direto de
`get_answer_generator()` com `answer_generator_provider` alterado tornaria a
propriedade legível onde ela vive.

---

## 15. Alternativas

### A — manter a arquitetura atual

**Benefício:** custo zero, risco zero; o contrato já é neutro e a substituição já
está provada por oito módulos de teste.
**Custo:** F1 e F2 permanecem; a afirmação de neutralidade da dissertação fica
mais fraca do que podia ser, porque nem sequer os contratos neutros são
importáveis sem o SDK.
**Risco:** nenhum técnico; um risco de exposição em defesa — «se o gerador é
substituível, porque é que desligar o provider continua a carregar o SDK?».
**Necessidade atual:** não resolve um problema demonstrado.

### B — import tardio na factory e emagrecimento do `__init__` *(mínima)*

O adapter passa a ser importado dentro do ramo que o instancia, e o `__init__` do
pacote deixa de reexportar a composition root.

**Benefício:** resolve F1 e F2 na íntegra; os contratos neutros passam a ser
importáveis sem SDK; a aplicação só paga o SDK quando o provider OpenAI é
efetivamente resolvido.
**Custo:** cerca de dez linhas em dois ficheiros, mais dois ou três testes de
caracterização. Nenhuma abstração nova, nenhum conceito novo.
**Risco:** baixo. Move o `ImportError` de um SDK em falta do arranque para a
primeira geração — o que é coerente com o comportamento já documentado, em que a
indisponibilidade se manifesta na geração e não no arranque. Um `import` dentro de
função é uma exceção deliberada ao estilo do repositório e precisa de comentário
que a justifique.
**Necessidade atual:** sim — é o único caminho mínimo que fecha F2.

### C — registry/factory extensível de providers

**Benefício:** acrescentar fornecedores sem tocar num `if`.
**Custo:** um mapa nome → factory, um ponto de registo, e a decisão de onde os
adapters se registam.
**Risco:** overengineering. Existe **um** provider real. Um registry com uma
entrada é indireção sem benefício, e o `if` de uma linha continua a ser a forma
mais legível de exprimir uma escolha entre uma alternativa.
**Necessidade atual:** **não.** O critério do §74 — uma necessidade que não seja
«talvez um dia haja outro provider» — não se verifica.

### D — tornar `openai` dependência opcional (extras)

**Benefício:** instalar o backend sem SDK de fornecedor; útil se alguma vez
existir um deployment só de retrieval ou uma imagem mínima de avaliação.
**Custo:** obriga a criar um bloco `[project]` em `pyproject.toml` ou um segundo
ficheiro de requisitos, a decidir o que a CI instala, e a manter as duas
combinações verdes.
**Risco:** complexidade de packaging real, por um benefício hoje hipotético.
**Necessidade atual:** **não agora.** B entrega quase todo o benefício prático —
não pagar o custo do SDK quando não é usado — sem tocar em packaging.

---

## 16. Matriz de decisão

| Critério | A (manter) | **B (import tardio)** | C (registry) | D (extras) |
| --- | --- | --- | --- | --- |
| simplicidade | máxima | alta — menos acoplamento, sem conceitos novos | média | baixa |
| substituibilidade real | parcial (L4 falha) | boa (L3 resolvido, L4 mantém-se) | igual a B | completa |
| testabilidade | boa | melhor — contratos importáveis isoladamente | igual a B | melhor ainda |
| acoplamento | eager, atravessa o pacote | confinado ao ramo que instancia | idem | idem |
| custo | zero | ~10 linhas, 2 ficheiros | moderado | alto (packaging + CI) |
| adequação ao protótipo | aceitável | boa | má | prematura |
| adequação à DSR | fraca — a afirmação de neutralidade fica por demonstrar | boa — torna a propriedade verificável por teste | neutra | boa, mas fora de tempo |
| risco de overengineering | nenhum | baixo | **alto** | médio |

---

## 17. Decisões pontuais

| Questão | Decisão |
| --- | --- |
| registry de providers | **REJECT** — um provider real; §74 não satisfeito |
| import tardio | **NOW** — resolve F1/F2 sem abstração nova |
| dependência opcional (`extras`) | **LATER** — reavaliar quando existir um segundo adapter ou um deployment sem answering |
| abstração própria de `Model` | **NÃO** — o modelo é configuração do adapter e nada no domínio precisa de o conhecer |
| `provider`/`model` em `GeneratedAnswer` | **DEFER** — metadado experimental, não contrato runtime |
| alterar prompts ou `response_format` | **NÃO** — já estão do lado certo da fronteira |
| segundo fornecedor | **NÃO** — fora do âmbito da A6 |
| segundo LLM de validação | **NÃO** — neutralidade de provider não o justifica |

---

## 18. Recomendação

```
RECOMENDAÇÃO: executar A6.1 — Alternativa B, âmbito mínimo
```

Justificação contra os critérios do §72 do enunciado, um a um:

| Critério | Verifica-se? |
| --- | --- |
| SDK importado mesmo quando o provider não é OpenAI | **SIM** — F2, demonstrado por sonda |
| troca de provider exige alterações fora da composition root | não |
| testes dependem desnecessariamente de OpenAI | **parcialmente** — F1: os contratos neutros não são importáveis sem SDK |
| contrato neutro é violado | não |
| tipos específicos do fornecedor vazam | não demonstrado (F4 é latente) |

Um critério verifica-se por inteiro e outro parcialmente. A recomendação **não**
se apoia em «multi-provider é melhor»: apoia-se num facto medido — configurar
`ANSWER_GENERATOR_PROVIDER="offline-disabled"` continua a carregar 778 módulos de
um SDK que nunca vai ser usado.

---

## 19. Plano mínimo para uma futura A6.1

*Especificação, não implementação. Nada disto foi executado.*

**Objetivo:** o SDK de um fornecedor só é carregado quando esse fornecedor é
efetivamente resolvido. Sem novas abstrações, sem novos conceitos de domínio.

**Ficheiros:**

1. `backend/app/answering/__init__.py` — deixar de reexportar
   `get_answer_generator`. Nenhum consumidor o usa; a única importação a partir
   do pacote é do submódulo `dependencies` e continua a funcionar.
2. `backend/app/answering/dependencies.py` — mover
   `from app.answering.providers.openai import ...` para dentro do ramo
   `if settings.answer_generator_provider == "openai":`, com comentário a
   explicar que o import tardio é deliberado.
3. `backend/app/answering/providers/openai.py` — *(item separável)* mover
   `self._build_client()` para dentro do `try`, fechando F4.

**Testes:**

- `import app.answering.base` não carrega `openai`;
- com `answer_generator_provider` diferente de `"openai"`,
  `get_answer_generator()` levanta `AnswerGeneratorUnavailableError` **sem** que
  `openai` entre em `sys.modules` (subprocesso limpo — F6 fica coberto pelo
  mesmo teste);
- `import app.main` não carrega `openai` — a decidir na revisão se se torna
  contrato ou se fica só caracterizado, já que FastAPI resolve `Depends` no
  arranque mas não os executa;
- se o item 3 for incluído: falha na construção do cliente sai como
  `AnswerGenerationError`.

**Critérios de aceitação:**

- suíte completa sem regressões e sem edições a testes existentes;
- `ruff`, `mypy`, gates de Alembic e compose inalterados;
- digest da baseline do Momento 5 preservado;
- nenhuma alteração em `Evidence`, `RetrievalResult`, schemas HTTP, base de
  dados, migrations ou frontend;
- nenhum consumidor novo dos contratos de `app/decision/`.

**Fora de âmbito da A6.1:** registry, segundo fornecedor, dependência opcional,
`provider`/`model` em `GeneratedAnswer`, alterações a prompts, `response_format`,
validação ou estratégia de geração.

---

## 20. O que este relatório não faz

Não implementa nada. Não cria fornecedores, não cria registry, não torna
dependências opcionais, não persiste `provider`/`model`, não toca em
`ScopeClass`, `RequestConstraint`, `AnswerabilityClass`, `DecisionOutcome`,
`RetrievalResult`, `RetrievalTrace` ou `ScoreSemantics`, e não inicia avaliação
com corpus real.

A execução da A6.1 depende de auditoria independente desta caracterização.
