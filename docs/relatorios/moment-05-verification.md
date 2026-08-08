# Verificação — Momento 5, Fase 3 (baseline)

Segundo [`05-verification-template.md`](../ai/05-verification-template.md).

Este relatório **não recalcula nada**. Todos os resultados de avaliação vivem em
[`moment-05-baseline-p1.json`](moment-05-baseline-p1.json), que é a fonte
primária; aqui apenas se identificam e se referenciam.

## Identificação

| Campo | Valor |
| --- | --- |
| Título | Baseline estrutural offline do Momento 5 (população P1) |
| Branch | `feat/moment-05-phase-3` |
| Data | 2026-08-08 |
| Repositório | `FredericoXX/Projeto-Final` |
| Origem | Momento 5, Fase 3 — [`moment-05.md`](../ai/moments/moment-05.md) |
| Gate aplicado | **backend**, segundo [`03-quality-gates.md`](../ai/03-quality-gates.md) |

## Veredicto

**Aprovado com correções.** O gate de backend está verde e a baseline P1 é
reproduzível. Existe um achado menor, já resolvido nesta fase (A1), e um achado
que permanece por pertencer ao fecho do momento (A2). Nenhuma correção
comportamental foi implementada, conforme o âmbito.

A Fase 3 e o Momento 5 **não estão concluídos**: passam a estar apenas com o
merge humano do Pull Request desta branch. Após esse merge, resta o Momento 6 —
UX e experiência operacional.

> **Atualização de fecho (2026-08-08).** A Fase 3 foi aprovada pelo merge humano
> do Pull Request #32, integrado na `main` em `0ed640cb`. Uma verificação
> posterior encontrou o achado A3 abaixo, corrigido na branch
> `fix/moment-05-closeout`: R1 passou a ser condição de publicação da baseline.
> Os resultados históricos desta verificação não foram alterados — a baseline
> continua a mesma e o `result_digest` é o mesmo.

## Estado inicial

| Item | Valor |
| --- | --- |
| `BASE_SHA` | `aa72fcd5f0bb2fd5ed7ebc637a39f1e0c69235ec` |
| Branch criada a partir de | `main` em `aa72fcd`, que integrou o Pull Request #31 (Fase 2) |
| Working tree antes de começar | limpa (`git status --porcelain` sem saída) |
| Migration em head | `e7b1c9d4a2f0`, head única |
| Commits / push / Pull Request | nenhum |

CI de `aa72fcd` verificada antes de começar: workflow *Backend checks*,
conclusão `success`.

## Baseline

Medições feitas **antes** de qualquer alteração, sobre `aa72fcd` intacto.

| Verificação | Resultado |
| --- | --- |
| Carregamento dos artefactos | corpus `1.0.0` com 19 casos e rubrica `1.0.0` com 11 critérios, ambos válidos |
| `python -m scripts.evaluate_answering_offline` (1.ª execução) | 19 casos, `result_digest` `75d9361…1dd345` |
| `python -m scripts.evaluate_answering_offline` (2.ª execução, output distinto) | 19 casos, mesmo `result_digest` |
| R1 | `results` idênticos e `result_digest` idêntico entre as duas execuções |

O mecanismo da Fase 2 funcionou sobre a `main` sem qualquer alteração, o que
confirmou não ser necessário tocar-lhe.

## Problema reproduzido

Verificado **por execução**, não assumido:

- os 19 casos atravessam a implementação real de
  `app.services.answering_service.ask`;
- os cinco casos de rejeição terminam em `InvalidGeneratedAnswerError` levantada
  pela implementação real de `validate_generated_answer`, com os cinco reason
  codes distintos;
- R1 confirmado por duas execuções completas, primeiro pelo CLI da Fase 2 e
  depois, de novo, dentro do compositor da baseline.

Verificado **por leitura**: o relatório de execução da Fase 2 não declara o
estatuto por população, não declara as métricas humanas como não medidas, não
regista a confirmação de R1 e não classifica as células `fail` — as quatro
declarações que o critério de paragem da Fase 3 exige.

## Alterações

| Ficheiro | Alterado ou novo | Razão |
| --- | --- | --- |
| `backend/app/evaluation/baseline.py` | novo | composição pura: recebe dois relatórios já produzidos e acrescenta o estatuto das populações, as métricas humanas não medidas derivadas da rubrica, o registo de R1 e a classificação das células `fail`. Não executa avaliação, não constrói relatórios e não calcula métricas nem digests — não importa `compute_result_digest` |
| `backend/scripts/build_moment05_baseline.py` | novo | entrypoint fino; invoca o entrypoint da Fase 2 duas vezes para uma diretoria temporária, lê os dois relatórios e compõe a baseline. Reutiliza a política de caminhos, a resolução do `commit_sha` e a neutralização do fornecedor da Fase 2 em vez de as duplicar |
| `backend/tests/test_evaluation_baseline.py` | novo | testes da composição, das declarações e do artefacto versionado |
| [`moment-05-baseline-p1.json`](moment-05-baseline-p1.json) | novo | a baseline; fonte primária única |
| [`02-current-state.md`](../ai/02-current-state.md) | alterado | snapshot em `aa72fcd`; Fase 2 aprovada pelo PR #31; Fase 3 em curso |
| [`moment-05.md`](../ai/moments/moment-05.md) | alterado | aprovação da Fase 2, branch da Fase 3, estado das fases |
| [`answering.md`](../answering.md) | alterado | registo da existência e do alcance da baseline, com ligação; sem duplicar a especificação |

Decisão de calibração declarada: a classificação das células `fail` é
**estrutural**, não interpretativa. A regra completa está no campo
`findings.classification_rule` do JSON.

## Ficheiros deliberadamente não alterados

- **Mecanismo da Fase 2** (`runner.py`, `harness.py`, `results.py`, o CLI e os
  respetivos testes) — nenhum ficheiro foi alterado. A Fase 3 executa e
  interpreta; não redesenha. O `result_digest` é produzido pela Fase 2 e a Fase
  3 preserva-o: o relatório embutido é o que o entrypoint da Fase 2 escreveu,
  com um único campo ajustado, `execution_metadata.output_path`, que é metadado
  volátil fora do digest e cujo valor original seria um caminho local de
  máquina.
- **Corpus e rubrica aprovados** — fixados pelo merge do Pull Request #30.
- **D1 a D11** — nenhuma contradição encontrada que impedisse a implementação.
- **`answering`, `retrieval`, OCR, chunking, frontend, API, base de dados,
  migrations, `message_sources`, política de elegibilidade, issue #24 e
  provider** — fora de âmbito; nenhum defeito comportamental foi encontrado que
  os obrigasse a mudar, e mesmo que tivesse sido, a correção pertence à Fase 4.
- **Resumo em Markdown da baseline** — D9 torna-o opcional; não é produzido,
  para que exista uma só fonte de resultados.

## Testes focados

| Comando | Passed | Failed | Skipped | Warnings | Duração |
| --- | --- | --- | --- | --- | --- |
| `pytest tests/test_evaluation_baseline.py -q` | 28 | 0 | 0 | 1 pré-existente | 1.74 s |
| `pytest tests/test_evaluation_assets.py tests/test_evaluation_runner.py tests/test_evaluation_cli.py tests/test_evaluation_baseline.py -q` | 195 | 0 | 0 | 1 pré-existente | 5.68 s |

O warning é o `StarletteDeprecationWarning` de
`fastapi/testclient.py`, anterior a este trabalho.

## Validação completa

Gate de backend executado no estado final da branch.

| Verificação | Resultado |
| --- | --- |
| `docker compose config --quiet` | válido, sem saída |
| `python -c "from app.main import app; print(app.title)"` | `Agentic Institutional Assistant` |
| `python -m pip check` | `No broken requirements found.` |
| `ruff check .` | `All checks passed!` |
| `mypy app tests scripts` | `Success: no issues found in 151 source files` |
| `pytest -q` | 1118 passed, 1 warning pré-existente, 210.26 s |
| `alembic upgrade head` | sem operações pendentes |
| `alembic current` / `alembic heads` | `e7b1c9d4a2f0 (head)`, head única |
| `alembic check` | `No new upgrade operations detected.` |
| `git diff --check` | verde |

Nenhum passo do workflow foi alterado.

## Resultados da baseline

Referências ao JSON; nenhum número aqui é recalculado.

| Item | Valor |
| --- | --- |
| População medida | **P1** — estrutural offline |
| SHA avaliado | `aa72fcd5f0bb2fd5ed7ebc637a39f1e0c69235ec` |
| Casos executados | 19 |
| `result_digest` (sha256) | `75d936182d9b8a675b43da208f04e1e7168c439c1fdbace04a865283731dd345` |
| R1 | confirmado: `results` e `result_digest` idênticos em duas execuções completas |
| P2 — respostas gravadas, juízo humano | **`not_measured`** |
| P3 — fornecedor real | **`not_measured`** |
| Métricas humanas e partes humanas das híbridas | **`not_measured`**, os 11 critérios da rubrica |

Perfil de A1–A8: **8 células `fail` em 7 casos**, todas explicadas — 2
`declared_source_divergence` (C012 e C013, as divergências deliberadas
introduzidas na Fase 1) e 6 `expected_rejection` (C015 a C019, onde a violação
estrutural é o defeito que o caso codifica). **Zero células `unexplained`.**

`A7` — o desfecho observado corresponde ao declarado, incluindo o reason code
nas rejeições — está `pass` nos 19 casos.

**Nenhum defeito real da aplicação foi observado em P1.** Não há, por isso,
camada de origem a classificar, e
`findings.behavioural_corrections_applied` é `false`.

## Achados

| # | Severidade | Achado | Evidência | Estado |
| --- | --- | --- | --- | --- |
| A1 | Baixa | O relatório de execução da Fase 2 grava `output_path` como caminho absoluto da máquina. Aceitável num ficheiro temporário, inaceitável num artefacto versionado, que o gate de documentação proíbe | O CLI da Fase 2 gravou `C:/…/scratchpad/r1.json` nas execuções de verificação | resolvido — o compositor grava o caminho relativo ao repositório, fixado por teste. O CLI da Fase 2 não foi alterado |
| A2 | Baixa | [`02-current-state.md`](../ai/02-current-state.md) mantém "não existe medição reprodutível da qualidade das respostas", verdadeiro em `aa72fcd` e inexato depois do merge desta fase | Secção *Limitações conhecidas* do snapshot | resolvido no fecho — o snapshot passou a `0ed640cb` e a limitação foi substituída pelo alcance real da baseline (só P1; P2/P3 não medidas) |
| A3 | Média | `build_moment05_baseline` registava `results_identical` e `digest_identical` mas publicava a baseline mesmo quando qualquer um era `false`; uma execução não reproduzível podia substituir uma baseline válida | Encontrado por verificação posterior ao merge do PR #32 | resolvido em `fix/moment-05-closeout` — R1 é verificado antes de qualquer escrita e uma execução não reproduzível termina com código 5 sem publicar |

Nenhum dos achados exige alteração de comportamento da aplicação.

## Limitações remanescentes

O que esta baseline **não** garante:

- não mede qualidade **semântica**: correção factual, fidelidade à evidência,
  completude, clareza e concisão dependem de P2 e ficam não medidas;
- não mede o **gerador real**: as respostas avaliadas vêm de um gerador falso
  com output declarado no corpus, e nenhum resultado é apresentado como
  qualidade do fornecedor configurado;
- o material é **sintético**; o comportamento sobre documentos institucionais
  reais continua a exigir validação humana;
- nada aqui torna o sistema livre de alucinações — a validação da camada
  continua estrutural, não semântica;
- **sem pesos e sem score agregado**: o resultado é um perfil por caso e por
  cenário, não um número comparável;
- a baseline fica comparável entre momentos, mas **não** foi criado gate
  automático de comparação.

A lista completa consta do campo `limitations` do JSON.

## Comandos não executados

- **Avaliação humana (P2)** e **execução com fornecedor real (P3)** — não
  executadas, por serem opcionais segundo D5 e D11 e por não existir decisão
  posterior que as exija. Estão declaradas como `not_measured`, nunca como zero
  e nunca omitidas.
- **Gate de frontend** — não aplicável: nenhum ficheiro de `frontend/` foi
  tocado.

Nenhum outro passo do enunciado ficou por executar.

## Confirmações Git

| Ação | Estado |
| --- | --- |
| Commit | não |
| Push | não |
| Pull Request | não |
| Merge / rebase / squash / tag | não |
| Alteração direta da `main` | não |
| `git reset --hard` / `clean` / `stash` / `restore` | não |
| Migration nova ou alterada | não |
| Base de desenvolvimento alterada | não — a avaliação corre com uma sessão-sentinela que recusa qualquer acesso inesperado |
| Rede usada durante os testes | não |
| Documentos institucionais reais usados | não — o corpus é integralmente sintético |
| Ficheiros alterados fora do âmbito declarado | não |
