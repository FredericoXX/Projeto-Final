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

Os identificadores estão em `config.METRIC_IDS`, com a origem de cada um. São
opções metodológicas provisórias, **não conteúdo normativo demonstrado da
v1.7** (`"normative": false`), e não servem para declarar conformidade
integral:

| ID | Métrica | Origem |
| --- | --- | --- |
| M1, M2 | ANSWER não aceitável; não-ANSWER fora do aceitável | prompt v1.7 disponível |
| M3 | matriz de confusão das quatro ações (ação preferida × ação da condição, falha técnica à parte), acordo estrito e aceitável | revisão de 2026-10-23; **não provém do prompt v1.7 disponível** |
| M4 | encaminhamento excessivo e insuficiente | dedução provisória |
| M5 | destino correto, condicional e total | dedução provisória |
| M6 | citações inadmissíveis | tema do prompt; identificador da revisão de 2026-10-23 |
| M7 | qualidade da mensagem, só com juízos humanos | dedução provisória |
| M8 | erros de estimação de P-e2e por dimensão | dedução provisória |
| M9 | — | por atribuir |

M6 resolve cada citação **no packet da própria condição**, até ao documento, à
versão e ao segmento, e verifica-a na data de referência com a semântica de
C9/C10. O mesmo `E1` pode ser vigente em P-e2e e caducado em A-sem-filtro.

As comparações emparelhadas estão em `config.PAIRED_COMPARISONS`. São uma
proposta configurável, derivada da definição das condições. Fazem parte do
artefacto congelado `config`, por isso ficam congeladas antes da avaliação, e
uma alteração muda o digest.

Todas as comparações têm o mesmo enquadramento estatístico:

- a **unidade estatística** é o caso, na execução principal; as três execuções
  não multiplicam a amostra;
- o **intervalo** é a diferença p(first) − p(second), com IC de Newcombe
  (método 10) a 95 %;
- cada resultado do relatório repete o efeito isolado, o desfecho, o
  denominador e a unidade.

| Par (first − second) | Efeito isolado | Medidas |
| --- | --- | --- |
| P-e2e − B0 | a política v1.7 completa contra o fluxo B0 | ação aceitável, ação estrita |
| P-e2e − B1-plena | regras determinísticas contra um modelo que estima e escolhe, com o mesmo packet, definições e regras | ação aceitável, ação estrita |
| P-e2e − B1-composição | composição da ação pelas regras contra pelo modelo, com as mesmas estimativas D1–D5 e o mesmo D6 | ação aceitável, ação estrita |
| P-oráculo − P-e2e | os erros de estimação: dimensões adjudicadas contra estimadas, com a mesma política | ação aceitável, ação estrita |
| B0 − A-sem-filtro | o filtro de validade C9/C10, e nada mais | citação inadmissível |
| P-e2e − A-sem-diagnóstico | o diagnóstico temporal e o seu efeito na mensagem | mensagem aceitável (juízo humano) |

| Medida | Desfecho por caso | Denominador |
| --- | --- | --- |
| ação aceitável | a ação pertence às aceitáveis adjudicadas | casos sem falha técnica nas duas condições |
| ação estrita | a ação é a preferida adjudicada | casos sem falha técnica nas duas condições |
| citação inadmissível | pelo menos uma citação inadmissível no packet da própria condição; sem citações conta como não | casos sem falha técnica nas duas condições |
| mensagem aceitável | juízo humano identificado de "aceitável" | casos sem falha técnica e com juízo humano nas duas condições |

Os casos excluídos são contados por motivo: falha técnica, ou falta de juízo
humano. Um IC que inclui zero não demonstra equivalência.

Limiares como κ = 0,60, δ = 5 pp e divergência de 20 % continuam propostas
configuráveis, com justificação pendente.
