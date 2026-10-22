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
5. `freeze_policy_v1_artifacts` congela corpus, manifesto, rótulos e o snapshot
   do catálogo institucional (âmbito D1 e serviços D6), a partir de ficheiros, e
   política, esquema, prompts e configuração, gerados a partir do código em
   execução. Regista SHA-256, versão da receita e do Python e o
   commit, e recusa uma árvore de trabalho por limpar.
6. Só então `run_policy_v1_evaluation --formal` aceita correr. Verifica todos
   os artefactos — os gerados a partir do código voltam a ser calculados —,
   o commit igual ao `HEAD`, a árvore limpa e o catálogo **ativo na base de
   dados** igual ao congelado. `p2_labels_tool oracle` verifica a adjudicação,
   o ficheiro de casos, o catálogo e a política, o esquema, os prompts e a
   configuração.
7. Os juízos de qualidade da mensagem (`--message-ratings`) e a inspeção das
   atribuições de erro são humanos.

Limiares como κ = 0,60, δ = 5 pp e divergência de 20 % continuam propostas
configuráveis, com justificação pendente.
