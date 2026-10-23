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
| [`message-ratings.schema.json`](message-ratings.schema.json) | `MessageRatingSet` em `app/evaluation/policy_v1/labels.py` | juízos humanos da qualidade da mensagem (M7), um por caso e condição |

Um teste falha se `labels.schema.json` divergir dos modelos. A regeneração faz-se
com `python -m scripts.p2_labels_tool schema --output ...`.

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
7. Só então `run_policy_v1_evaluation --formal` aceita correr. Verifica:
   - todos os artefactos, recalculando os gerados a partir do código;
   - o commit igual ao `HEAD` e a árvore limpa;
   - o catálogo ativo e o inventário documental, **lidos da base de dados**,
     iguais aos congelados.

   O inventário volta a ser lido antes do relatório: se a base mudou durante a
   execução, o relatório não é escrito. `p2_labels_tool oracle` verifica a
   adjudicação, o ficheiro de casos, o catálogo e a política, o esquema, os
   prompts e a configuração. O P-oráculo não usa evidência, por isso não lê o
   inventário.
8. Os juízos de qualidade da mensagem (`--message-ratings`) e a inspeção das
   atribuições de erro são humanos.

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
