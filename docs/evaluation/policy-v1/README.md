# Conjunto de avaliação da política v1 (P2)

> **Preparado, vazio, sem rótulos.** Este diretório define o formato do
> **conjunto de avaliação da política v1**, que usa exclusivamente o
> corpus/suplemento **P2**. Não contém casos nem rótulos: nenhum foi
> fabricado. P1 e os artefactos de D4.10/D4.10a (incluindo os rótulos
> pendentes, como DX028) não são lidos, convertidos nem reclassificados.

## Artefactos

| Ficheiro | Fonte de verdade | Conteúdo |
| --- | --- | --- |
| [`cases.schema.json`](cases.schema.json) | `EvaluationCaseSet` em `app/evaluation/policy_v1/executor.py` | casos: pedido, idioma, data de referência fixa, papel simulado |
| [`labels.schema.json`](labels.schema.json) | `LabelSet` em `app/evaluation/policy_v1/labels.py` | rótulos humanos dependentes por dimensão |
| [`message-ratings.schema.json`](message-ratings.schema.json) | `BoundMessageRatingSet` em `app/evaluation/policy_v1/message_ratings.py` | juízos humanos M7, um por mensagem, ligados à recolha, ao caso, à condição, à execução, ao texto exato, ao packet e ao resultado |
| [`message-ratings-draft.schema.json`](message-ratings-draft.schema.json) | `MessageRatingDraft` no mesmo módulo | rascunho exportado para revisão, com os juízos a `"pending"` |
| [`collection-report.schema.json`](collection-report.schema.json) | `CollectionReport` em `app/evaluation/policy_v1/report.py` | relatório arquivado pela recolha (formato `policy_v1_report_2` e o anterior, sem versão) |

Um teste falha se algum destes esquemas divergir dos modelos. A regeneração
faz-se com `python -m scripts.p2_labels_tool schema --kind KIND --output ...`
(`labels`, `cases`, `message-ratings`, `message-ratings-draft`,
`collection-report`).

O procedimento operacional do piloto de desenvolvimento está em
[`pilot-runbook.md`](pilot-runbook.md).

Rótulos:

- N/A é sempre `null` num campo próprio, nunca uma categoria.
- Materialidade, desambiguação e cobertura de D3 são campos distintos.
- `partial_misleading` só se aplica a suficiência parcial.
- Cada caso tem as ações aceitáveis e uma **ação preferida**, que pertence às
  aceitáveis (esquema `policy_v1_labels_2`). A ação preferida dá a linha da
  matriz de confusão (M3) e separa o acordo estrito do acordo aceitável.
- Uma adjudicação identifica os adjudicadores.

## Proposta de dimensionamento

28 casos dev e 136 de teste, mais F14 em separado. É uma proposta **sujeita a
calibração e dimensionamento**, registada em
`app/evaluation/policy_v1/config.py`. O conjunto de teste é reservado: nunca é
usado para afinação, e o executor recusa ensaios de desenvolvimento com
conjuntos que não sejam `policy-v1-dev*`.

## Fluxo previsto

1. Casos escritos por pessoas, com dados sintéticos ou autorizados.
2. Dois anotadores (A1, A2) rotulam independentemente.
3. `p2_labels_tool check A1.json A2.json` reporta:
   - N;
   - acordo bruto;
   - κ, quando aplicável;
   - matriz de desacordos;
   - IC;
   - aplicabilidade assimétrica.

   Trocar A1 por A2 preserva o resultado. Sem A2, só é possível um **piloto
   declarado**, não concordância interanotadores.
4. Adjudicação identificada.
5. `export_policy_v1_corpus_inventory --institution-code CODE --output F`
   exporta da base o **inventário documental** da instituição: todos os
   documentos, versões e segmentos, incluindo os caducados, os inativos e os
   restritos por papel, com metadados e hashes e sem conteúdo. É este o
   manifesto documental congelado.
6. `freeze_policy_v1_artifacts` congela os ficheiros (casos, inventário
   documental como `manifest`, rótulos e snapshot do catálogo institucional, com
   âmbito D1 e serviços D6) e gera a partir do código em execução a política,
   o esquema, os prompts e a configuração. Regista SHA-256, versão da receita e
   do Python e o commit, e recusa uma árvore de trabalho por limpar ou um
   inventário que não valide.
7. Só então `run_policy_v1_evaluation --formal` aceita correr (num ensaio de
   desenvolvimento com adjudicação e manifesto verificam-se os artefactos, o
   catálogo e o inventário, mas não o commit, a árvore de trabalho nem os traços
   formais). Verifica:
   - todos os artefactos, recalculando os gerados a partir do código;
   - o commit igual ao `HEAD` e a árvore limpa;
   - o catálogo ativo e o inventário documental, **lidos da base de dados**,
     iguais aos congelados.

   O inventário volta a ser lido antes do relatório: se a base mudou durante a
   execução, o relatório não é escrito. `p2_labels_tool oracle` verifica a
   adjudicação, o ficheiro de casos, o catálogo e a política, o esquema, os
   prompts e a configuração. O P-oráculo não usa evidência, por isso não lê o
   inventário.
8. A recolha chama os modelos **uma vez** e arquiva as respostas; não aceita
   juízos de mensagens. `export_policy_v1_message_review` exporta as mensagens
   para revisão humana, e `score_policy_v1_report` recalcula as métricas sobre
   essas mesmas respostas, sem novas chamadas (secção seguinte).
9. Os juízos de qualidade da mensagem e a inspeção das atribuições de erro são
   humanos.

## Recolha, revisão humana e reanálise offline

```text
run_policy_v1_evaluation        → recolha.json            (modelos chamados uma vez)
export_policy_v1_message_review → review-material.md      (para o avaliador; conteúdo documental)
                                  ratings-draft.json       (rascunho a preencher)
                                  review-manifest.json     (proveniência)
pessoas                         → avaliacoes.json          (policy_v1_message_ratings_2)
score_policy_v1_report          → analise.json             (sem base de dados, rede ou modelos)
```

**Relatório da recolha** (`policy_v1_report_2`): além dos packets, resultados e
métricas, regista `collection_id`, `collected_at`, o estado do Git observado
(`git`), a configuração de execução (`runtime`) e os digests dos casos, da
adjudicação, do manifesto de congelamento, do inventário documental e do
catálogo (`inputs`). O executor nunca sobrescreve um relatório existente.

**Identidade das mensagens.** Cada juízo M7 identifica a recolha
(`source_report`: `collection_id` e SHA-256 dos bytes do relatório), o caso, a
condição, a execução (só a principal), `message_sha256` — SHA-256 dos bytes
UTF-8 do texto exato, sem normalização —, `packet_digest` e `outcome_id` — o
SHA-256 canónico do resultado arquivado. A exportação e a validação usam as
mesmas funções (`message_ratings.py`). São recusados juízos sobre mensagens
inexistentes ou alteradas, de outra recolha, condição ou execução, duplicados,
sobre falhas técnicas ou P-oráculo, com `"pending"`, com booleanos em texto, ou
sem juízo num critério obrigatório para a mensagem (ANSWER, R10, CLARIFY,
ESCALATE, F02). `null` é não aplicável; `false` é avaliação negativa.

**Um juízo por mensagem.** M7 usa uma avaliação consolidada por mensagem. Com
vários avaliadores, pessoas identificadas consolidam as divergências
(`provenance.kind = "human_consolidation"`, `consolidated_by`); não há média
nem adjudicação automática. Sem juízos — ou sem nenhum que se aplique às
mensagens de uma condição ou de um estrato —, M7 fica **não medida**, nunca
0/0.

**Reanálise.** `score_policy_v1_report` recebe `--report`, `--cases`,
`--adjudication`, `--freeze-manifest`, opcionalmente `--message-ratings` e
`--corpus-inventory`, e `--output` (caminho novo, diferente das entradas). Não
importa a configuração da aplicação: corre sem `.env`, `DATABASE_URL`,
`JWT_SECRET_KEY` ou chaves. Antes de calcular, verifica: o contrato do relatório,
o digest de cada packet e, por condição, as estimativas arquivadas (P-e2e e
A-sem-diagnóstico têm de trazer entradas da política com tipos JSON estritos —
`"false"`, `0` ou `1` não passam por booleanos —, válidas e canónicas; B0,
A-sem-filtro, P-oráculo e as falhas técnicas, nenhumas); a coerência entre
packets, resultados e execuções; o contrato e a receita do manifesto de
congelamento, e que é o mesmo que a recolha leu (bytes canónicos do conteúdo);
os casos e a adjudicação contra a recolha e o congelamento, com o mesmo `set_id`
no relatório, nos casos e na adjudicação (a recolha e `p2_labels_tool oracle`
recusam essa incompatibilidade antes de correr); que a recolha correu
o código congelado; o catálogo, o inventário e a configuração registados contra
os congelados; e que o código da análise tem a mesma política e a mesma
configuração da avaliação.
Recalcula as métricas pela mesma função da recolha, com a primeira execução como
principal e o modo da recolha, compara-as com as arquivadas
(`collection_metrics_reproduction`) e só depois aplica os juízos M7. Regista o
relatório de origem, os hashes das entradas, as versões, o commit da recolha e
o da análise, e `case_traces` por caso. Com `--formal`, exige ainda uma recolha
formal `policy_v1_report_2` que registou o seu manifesto, recolha e análise em
árvores limpas, os mesmos esquemas e prompts, o inventário congelado e métricas
reproduzidas; sem `--formal`, só aceita conjuntos `policy-v1-dev*`.

**Relatórios anteriores** (sem `report_schema_version`) são aceites só em
reanálise de desenvolvimento, com `verification.level = "legacy_partial"` e a
lista do que não registaram em `verification.unverifiable` (adjudicação e
manifesto usados na recolha, inventário documental, configuração de execução e
estado do Git).
Nunca recebem conformidade formal. Os juízos do formato v1
(`policy_v1_message_ratings_1`, só caso e condição) não são aceites pela
reanálise: não dizem que texto foi julgado.

## Métricas e comparações

A correspondência com o documento de trabalho v1.7 está em
[specification-v1-7.md](specification-v1-7.md). A configuração
`config.METRIC_IDS` identifica a origem das definições; isso não equivale a
aprovação científica nem a avaliação concluída.

| ID | Métrica |
| --- | --- |
| M1 | ANSWER quando ANSWER não é aceitável. |
| M2 | Não-ANSWER fora do conjunto aceitável quando ANSWER é aceitável. |
| M3 | Ação preferida × produzida; acordo estrito/aceitável e precisão/recall por ação. |
| M4 | Não encaminhar quando ESCALATE é a ação preferida, mesmo que ABSTAIN também seja aceitável. |
| M5 | Destino correto entre encaminhamentos produzidos aceitáveis e, em total, entre casos com ESCALATE preferido. |
| M6 | Citações inadmissíveis, resolvidas no packet da própria condição. |
| M7 | Juízos humanos por critério da rubrica, distinguindo não aplicável de falha. |
| M8 | Erros por dimensão, confusões direcionais, acordo e incerteza. |
| M9 | Atribuição de erro por replay e inspeção humana; causas múltiplas/indeterminadas admitidas. |

O encaminhamento excessivo é um indicador suplementar, não M4. P-oráculo
contra P-e2e é um contraste diagnóstico, não prova causal isolada dos erros
de recuperação, estimação ou regra.

M6 resolve cada citação no packet da própria condição, até ao documento, à
versão e ao segmento, e verifica C9/C10 na data de referência.

H1/H1b usam M1 em P-e2e contra B0, B1-plena e B1-composição: McNemar exato
bilateral e correção de Holm sobre os três contrastes. H2 usa a diferença
emparelhada de M2; a margem proposta de 5 pp continua sem justificação e não
habilita uma conclusão confirmatória. H5b compara a presença do aviso temporal
em F02; a utilidade da mensagem exige juízo humano separado.

As comparações e os limiares configuráveis integram o artefacto `config`
congelado. A unidade é o caso na primeira execução numerada. As três execuções
não multiplicam N. Os IC das diferenças são Newcombe (método 10), a 95 %;
um IC que inclua zero não demonstra equivalência. Falhas técnicas e juízos
humanos ausentes são contados separadamente.

## Preparação dos casos e rótulos

Acrescentar `family` (F01–F15) e `source_kind` (`real` ou `synthetic`) a cada
caso antes de exportar os snapshots:

```bash
python -m scripts.export_policy_v1_case_snapshots --cases cases.json --output cases-bound.json
```

O exportador fixa `expected_snapshot_id` sem chamar modelos ou produzir
rótulos. A adjudicação humana deve preencher `trace` segundo o esquema:
família, origem, snapshot, justificação, itens, leituras e evidências por
**chunk ID do corpus**, não pelos identificadores locais E1/E2. A avaliação
formal recusa rótulos ausentes, incoerentes ou ligados a evidências
inadmissíveis. Metadados opcionais apenas preservam fixtures técnicas antigas;
não dispensam os requisitos de uma execução formal.

Casos sintéticos nunca entram no agregado principal de fontes reais. F14 é
sempre separado, também por origem. As famílias são reportadas dentro do seu
estrato. M7 exige a rubrica humana por critério quando forem fornecidos juízos
numa execução formal. Alterar os esquemas muda os digests: congelar novamente
todos os artefactos antes da avaliação. Não migrar automaticamente rótulos
humanos antigos.
