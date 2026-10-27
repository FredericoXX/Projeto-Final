# Piloto P2 da política v1.7 — runbook operacional

> **Preparado, não executado.** Em 2026-10-27 não existe neste repositório
> nenhum documento P2, catálogo do piloto, caso, rótulo, avaliação de mensagens
> nem resultado do piloto. Este runbook descreve a sequência para os produzir
> fora do repositório e verificar o comportamento real dos modelos. Os comandos
> foram verificados contra o código; nenhuma chamada paga foi feita.

## 0. O que este piloto é — e o que não é

| Nível | O que demonstra | Onde está |
| --- | --- | --- |
| Validação técnica | o código faz o que declara, com fixtures sintéticas e doubles | `backend/tests/` |
| **Ensaio de desenvolvimento (este piloto)** | o comportamento real dos estimadores e da geração em casos de desenvolvimento P2, contra juízos humanos | fora do repositório |
| Avaliação formal | as hipóteses H1–H6 sobre o conjunto reservado, com protocolo congelado | ainda não preparada |

- Os **28 casos de desenvolvimento e 136 de teste** são uma proposta registada em
  `config.EVALUATION_CONFIG["sets"]`, sujeita a justificação e dimensionamento.
  Não são requisitos aprovados.
- A afinação usa **só** casos `policy-v1-dev*`. O conjunto reservado nunca é
  usado para afinar: o executor e a reanálise recusam-no fora do modo formal.
- P1 e os artefactos de D4.10/D4.10a não são convertidos em P2.
- Nenhum modelo cria rótulos, juízos de mensagens, justificações, ações
  preferidas ou adjudicações.
- Documentos institucionais, casos, rótulos, relatórios e avaliações do piloto
  não entram no repositório (constituição, secção 2). Exemplos sintéticos só
  existem como fixtures técnicas identificadas em `backend/tests/`.

## 1. Pré-requisitos

- **Base de dados dedicada ao piloto**, com PostgreSQL/pgvector e
  `alembic upgrade head`. `DATABASE_URL` aponta para ela durante todo o piloto.
  Nunca a base de testes (é truncada a cada teste) nem uma base com dados a
  preservar.
- `ENVIRONMENT=development`. Os ensaios de desenvolvimento só correm em
  `development`/`test`, e a ablação A-sem-filtro recusa qualquer outro ambiente
  (`executor._b0_packet`).
- Fornecedor configurado só no ambiente do piloto: `OPENAI_API_KEY`,
  `OPENAI_MODEL`, `ANSWER_GENERATOR_PROVIDER=openai`,
  `DECISION_ESTIMATOR_PROVIDER=openai` e, opcionalmente,
  `DECISION_ESTIMATOR_MODEL` (sem valor, usa `OPENAI_MODEL`; o modelo B1 é o
  mesmo).
- **Orçamento de chamadas.** Por caso e por execução: até 2 do gerador (B0 e
  A-sem-filtro, quando há passagens), 1 a 3 dos estimadores (a análise sempre;
  a avaliação quando há evidência; o procedimento no caminho de restrições),
  até 1 do gerador em P-e2e (só ANSWER) e até 2 do modelo B1. São três execuções
  numeradas.
- **Configuração fixa** antes de exportar snapshots: `ANSWERING_DEFAULT_TOP_K`,
  `DECISION_RETRIEVAL_TOP_K`, `ANSWERING_MAX_CONTEXT_CHARS`,
  `ANSWERING_MAX_ANSWER_CHARS`, `RETRIEVAL_MIN_RELEVANCE_SCORE`, modelos,
  timeout e tentativas. O snapshot de cada caso e o artefacto `config`
  dependem deles.
- Pessoas identificadas: autores dos casos, dois anotadores independentes (A1,
  A2), adjudicadores e avaliadores das mensagens. Sem A2, o piloto é declarado
  como tal e não reporta concordância entre anotadores.

Todos os comandos `python -m scripts....` correm a partir de `backend/`, com o
ambiente virtual ativo.

## 2. Instituição de teste isolada

1. Criar a instituição com `X-Bootstrap-Token` (`POST /api/v1/institutions`),
   com um código próprio do piloto, por exemplo `P2-PILOT`.
2. Registar o primeiro administrador
   (`POST /api/v1/auth/register-initial-admin`) e iniciar sessão.
3. Criar um gestor documental (`POST /api/v1/users`, papel
   `knowledge_manager`).

Detalhe em [`README.md`](../../../README.md#inicialização-de-uma-instituição).
O isolamento entre instituições depende dos filtros da aplicação (constituição,
secção 1): uma base dedicada evita misturar o piloto com outros dados.

## 3. Catálogo de âmbito e serviços competentes

O administrador publica o catálogo com `PUT /api/v1/decision/catalog`:
`scope_description` (âmbito, D1), `topics` e `services` (serviço competente por
tema, D6). Regras em
[`docs/decision-policy.md`](../../decision-policy.md#2-ativar-em-desenvolvimento).

- Cada publicação cria uma versão nova. A versão ativa na recolha tem de ser a
  congelada: não republicar entre o congelamento e a recolha.
- Contactos reais só com autorização; caso contrário, contactos sintéticos
  (`example.org`) declarados como tal.
- Para congelar, guardar de `GET /api/v1/decision/catalog` apenas `version`,
  `scope_description`, `topics` e `services`.

## 4. Documentos e metadados

O gestor documental cria cada documento lógico (`POST /api/v1/documents`) e
carrega a versão (`POST /api/v1/documents/{id}/versions`), que tem de ficar
`processed`. Campos em [`docs/document-core.md`](../../document-core.md).

| Situação a exercitar | Representação |
| --- | --- |
| informação vigente | `valid_from`/`valid_until` do documento lógico abrangem a data de referência (limites inclusivos) |
| informação caducada | um documento lógico com `valid_until` anterior à data de referência; o diagnóstico temporal só o nomeia |
| calendários coexistentes | documentos lógicos distintos, cada um com o seu intervalo |
| documento restrito (C13) | `access_roles` com os papéis autorizados; lista vazia = sem restrição |
| fonte não oficial | `official_source=false` (fora do contexto quando `official_only`) |
| conflito | dois documentos vigentes que divergem sobre o mesmo item nas mesmas condições |

Documentos reais só com autorização e nunca no repositório. Documentos escritos
para o piloto são sintéticos e os casos que deles dependem levam
`source_kind="synthetic"`.

## 5. Casos de desenvolvimento

Ficheiro conforme [`cases.schema.json`](cases.schema.json), escrito por pessoas:

```json
{
  "schema_version": "policy_v1_cases_1",
  "set_id": "policy-v1-dev-pilot-1",
  "corpus": "P2",
  "institution_code": "P2-PILOT",
  "cases": [
    {
      "case_id": "DEV-001",
      "query": "…",
      "language": "pt",
      "reference_date": "2026-10-01",
      "requester_role": "student",
      "official_only": true,
      "family": "F02",
      "source_kind": "synthetic",
      "expected_snapshot_id": null
    }
  ]
}
```

- `set_id` começa por `policy-v1-dev`: o executor e a reanálise de
  desenvolvimento recusam outros conjuntos.
- `family` — F01–F15, segundo o documento de trabalho v1.7. As famílias que a
  implementação nomeia estão em [specification-v1-7.md](specification-v1-7.md):
  F02/F03 (admissibilidade e informação fora de vigor), F05 (suporte parcial),
  F07/F08/F09 e F15 (esclarecimento), F14 (autorização por papel, sempre em
  estrato próprio). A família de cada caso é um juízo do autor, não do código.
- `source_kind` — `real` para pedidos de origem real autorizada; `synthetic`
  para pedidos escritos para o teste. Casos sintéticos nunca entram no agregado
  principal de fontes reais; F06/F14 construídos sinteticamente são
  identificados como tal.
- `reference_date` — uma data fixa por caso, nunca o relógio do servidor.
  Escolhê-la deliberadamente para os casos de vigência (incluindo os limites).
- `requester_role` — `admin`, `knowledge_manager`, `staff`, `student` ou
  `user`: papel simulado só no executor offline; entra na recuperação (C13).
- `expected_snapshot_id` — `null` ao escrever; é preenchido pelo exportador do
  passo 6, nunca à mão.

Cobrir as quatro ações (ANSWER, CLARIFY, ABSTAIN, ESCALATE) e as situações
críticas: suporte parcial, conflito, ambiguidade material, informação caducada,
documentos restritos, fora de âmbito e dado pessoal.

## 6. Fixar snapshots antes da rotulagem

```powershell
python -m scripts.export_policy_v1_case_snapshots --cases cases.json --output cases-bound.json
python -m scripts.export_policy_v1_corpus_inventory --institution-code P2-PILOT --output inventory.json
```

O primeiro fixa `expected_snapshot_id` por caso (corpus visível ao papel, na
data de referência); o segundo exporta o inventário documental (sem conteúdo).
Nenhum chama modelos. A partir daqui a base não muda — documentos, versões,
papéis, vigência e catálogo. Uma alteração obriga a exportar de novo e a rever
os rótulos afetados.

## 7. Rotulagem independente e adjudicação

1. A1 e A2 rotulam em separado, conforme [`labels.schema.json`](labels.schema.json):
   D1–D6, ações aceitáveis, ação preferida e `trace` (família, origem,
   `snapshot_id`, justificação escrita, itens, leituras e conflitos), com
   evidências por **chunk ID do corpus**, nunca por `E1`/`E2`.
2. `python -m scripts.p2_labels_tool check A1.json A2.json --output acordo.json`
   reporta N, acordo, κ, desacordos, IC e aplicabilidade assimétrica.
3. Adjudicadores identificados escrevem a adjudicação
   (`annotator.role="adjudication"`, `adjudicators`).

**Em falta no repositório:** uma exportação do corpus para anotação, com o texto
e o chunk ID de cada segmento. Até existir, os anotadores leem os documentos
pela API (`GET /api/v1/documents/{id}/versions/{version_id}/content`) e obtêm os
IDs com uma consulta só de leitura à base do piloto, por exemplo:

```sql
SELECT c.id AS chunk_id, d.title, c.chunk_index, c.content
FROM document_chunks c
JOIN documents d ON d.id = c.document_id
JOIN institutions i ON i.id = c.institution_id
WHERE i.code = 'P2-PILOT'
ORDER BY d.title, c.document_version_id, c.chunk_index;
```

Esta saída contém conteúdo documental e fica no ambiente autorizado. A avaliação
formal recusa evidências que o papel do caso não possa ver na data de referência.

## 8. Congelar

Com a árvore de trabalho limpa:

```powershell
python -m scripts.freeze_policy_v1_artifacts `
  --artifact corpus=v1=cases-bound.json `
  --artifact manifest=v1=inventory.json `
  --artifact labels=v1=adjudicacao.json `
  --artifact catalog=v1=catalogo.json `
  --commit <SHA do HEAD> --output-dir freeze-dev-1
```

Os artefactos `policy`, `schema`, `prompts` e `config` são gerados do código em
execução. Alterar esquemas, prompts, configuração ou política obriga a congelar
de novo.

## 9. Recolha (chamadas pagas)

```powershell
python -m scripts.run_policy_v1_evaluation --cases cases-bound.json `
  --adjudication adjudicacao.json --freeze-manifest freeze-dev-1/freeze-manifest.json `
  --commit <SHA> --output recolha-dev-1.json
```

- Chama os modelos **uma vez**: três execuções numeradas por condição com
  modelo, uma de P-oráculo. A primeira execução é a principal.
- O relatório (`policy_v1_report_2`) regista `collection_id`, `collected_at`,
  o estado do Git, a configuração de execução e os digests dos casos, da
  adjudicação, do manifesto, do inventário e do catálogo.
- Nunca sobrescreve um relatório existente e recusa `--message-ratings`.
- Contém pedidos, passagens e mensagens: fica no ambiente autorizado.

## 10. Exportar as mensagens para revisão

```powershell
python -m scripts.export_policy_v1_message_review --report recolha-dev-1.json --output-dir revisao-dev-1
```

Escreve `review-material.md` (o que o avaliador lê, **com conteúdo
documental**), `ratings-draft.json` (o rascunho a preencher) e
`review-manifest.json` (proveniência). Só entram as mensagens da execução
principal sem falha técnica. A condição de cada mensagem fica visível: decidir
antes se o protocolo exige revisão cega.

## 11. Avaliações humanas (M7)

1. Cada avaliador preenche a sua cópia do rascunho: `rater_id`, `acceptable`
   (`true`/`false`) e cada critério (`true`, `false` ou `null` = não aplicável).
   Os critérios obrigatórios de cada mensagem estão no material.
2. Mensagens não avaliadas são retiradas do ficheiro. `"pending"` é recusado.
3. Para concluir, o ficheiro passa a `schema_version`
   `policy_v1_message_ratings_2` e declara `provenance`:
   - um avaliador por mensagem: `{"kind": "one_rater_per_message", "raters": [...]}`;
   - vários avaliadores: as divergências são resolvidas por pessoas
     identificadas, que escrevem um ficheiro consolidado com
     `{"kind": "human_consolidation", "raters": [...], "consolidated_by": [...]}`.
     Não há média, votação nem adjudicação automática. Os ficheiros individuais
     ficam guardados como proveniência.

Cada juízo fica ligado à recolha (`collection_id`, SHA-256 do relatório), ao
caso, à condição, à execução, ao hash do texto, ao packet e ao resultado. Um
juízo que não corresponda exatamente é recusado.

## 12. Reanálise offline

```powershell
python -m scripts.score_policy_v1_report --report recolha-dev-1.json `
  --cases cases-bound.json --adjudication adjudicacao.json `
  --freeze-manifest freeze-dev-1/freeze-manifest.json `
  --message-ratings avaliacoes-dev-1.json --output analise-dev-1.json
```

Sem base de dados, rede, modelos, chaves nem configuração da aplicação (`.env`,
`DATABASE_URL`, `JWT_SECRET_KEY`). Verifica a recolha contra os ficheiros e o
congelamento — incluindo que o manifesto é o que a recolha leu e usa a mesma
receita —, recalcula as métricas pela mesma função da recolha
(primeiro sem juízos, comparando com as arquivadas) e aplica os juízos M7. A
análise regista o relatório de origem, os hashes das entradas, as versões, o
commit da recolha e o da análise, e `case_traces`: para cada caso, a
adjudicação, os documentos do packet, as estimativas, a regra, a mensagem, o
juízo e a pertença a cada métrica, com as falhas técnicas à parte.

## 13. Inspeção dos erros e calibração

- Ler `error_attribution_p_e2e` (M9): o replay **propõe** causas
  (`inspection.status = "pending"`); a confirmação é humana.
- Procurar, caso a caso: classificação errada do âmbito, leituras artificiais,
  suporte documental mal interpretado, encaminhamento excessivo, falhas da
  geração e falhas técnicas.
- Registar cada alteração de calibração num registo próprio, fora do
  repositório se tiver conteúdo: data, `collection_id` da recolha, SHA-256 da análise,
  problema observado, casos de desenvolvimento em que se baseia, alteração feita
  e commit. Só casos de desenvolvimento justificam alterações.
- Depois de alterar prompts, regras, configuração ou esquemas: congelar de novo
  e fazer **outra** recolha. Os juízos de uma recolha nunca são transferidos
  para outra.

## 14. Elementos em falta (2026-10-27)

- corpus P2: documentos autorizados ou sintéticos identificados, com vigência,
  oficialidade e permissões;
- catálogo do piloto (âmbito, temas, serviços competentes e contactos);
- casos de desenvolvimento escritos por pessoas, e a justificação do seu número;
- anotadores A1 e A2, adjudicadores e avaliadores M7 identificados;
- decisão sobre revisão cega das mensagens;
- credenciais do fornecedor e orçamento para a recolha;
- exportação do corpus para anotação (secção 7);
- referência às definições das famílias F01–F15, que estão no documento de
  trabalho v1.7 e não no repositório.
