# Momento 5 — Qualidade das respostas fundamentadas e das fontes

Especificação inicial, segundo [`04-moment-template.md`](../04-moment-template.md).

## Identificação

| Campo | Valor |
| --- | --- |
| Momento | 5 — Qualidade das respostas fundamentadas e das fontes |
| Estado | Fase 0 **aprovada**; Fase 1 **em curso**, não concluída enquanto o respetivo Pull Request não estiver fundido na `main`; Fases 2 e 3 por iniciar |
| Commit base | `776e31e` (2026-08-06) |
| Branch da Fase 0 | `docs/moment-05-phase-0` |
| Aprovação da Fase 0 | merge humano do Pull Request #29, integrado na `main` em `2b6247c` — ver [Proveniência e aprovação](#proveniência-e-aprovação) |
| Branch da Fase 1 | `feat/moment-05-phase-1`, a partir de `2b6247c` |
| Divisão em Pull Requests | quatro, um por fase — ver [D10](#d10--divisão-em-pull-requests) |

## Problema

O pipeline de respostas fundamentadas é validado de forma **determinística e
estrutural**: a resposta não pode estar vazia, exceder o limite de caracteres,
ou citar evidências inexistentes. Nada disto mede se a resposta está
**correta**, se é **fiel à evidência recebida**, se cita a fonte **certa**, ou
se falha bem quando não deve responder.

Consequência: não existe forma reprodutível de saber se uma alteração melhorou
ou degradou a qualidade das respostas. Qualquer afirmação sobre qualidade é
hoje uma impressão, não uma medição.

## Objetivo

Tornar a qualidade das respostas e das citações **observável e comparável**,
e produzir uma baseline registada.

Este momento produz **método, corpus, instrumentação e medição**. Não produz
correções de comportamento: essas resultam da baseline e são tratadas como
escopos próprios, aprovados depois.

## Estado atual relevante

- Pipeline, política de evidência, atomicidade do turno e snapshots das fontes:
  [`docs/answering.md`](../../answering.md).
- Recuperação lexical, elegibilidade e ranking:
  [`docs/database.md`](../../database.md).
- Extração, OCR e chunking: [`docs/document-core.md`](../../document-core.md).
- Ferramenta de observação já existente, com trace redigido e execução sem
  rede: [`docs/diagnostics/README.md`](../../diagnostics/README.md). É *prior
  art* direta — mesma disciplina de reprodutibilidade e de proteção de dados.
- Limites configuráveis do answering:
  [`.env.example`](../../../.env.example).
- Comportamento sem evidência e conteúdo dos logs:
  [`02-current-state.md`](../02-current-state.md). O fallback
  `insufficient_evidence` é o ponto de partida deste momento, não um defeito.

## Invariantes tocadas

De [`01-project-constitution.md`](../01-project-constitution.md):

- **Respostas fundamentadas em evidências** (§3) — é o princípio que este
  momento passa a medir em vez de assumir;
- **Separação entre instruções e dados não confiáveis** (§6) — o corpus
  adversarial testa-a; o momento não pode transformar a redução de risco numa
  alegação de imunidade;
- **Segurança e privacidade** (§2) — corpus sintético, sem rede na avaliação
  offline, sem dados reais em artefactos;
- **Neutralidade de fornecedor** (§5) — a avaliação incide sobre a camada, não
  sobre um modelo concreto;
- **Honestidade das verificações** (§11) — juízo humano não é apresentado como
  medição automática;
- **Disciplina de âmbito** (§9) — ver Restrições.

## Âmbito

1. Decisões de método de avaliação (Fase 0).
2. Corpus sintético e rubrica de avaliação (Fase 1).
3. Mecanismo de avaliação offline determinístico (Fase 2).
4. Baseline medida e defeitos classificados (Fase 3).
5. Atualização de [`docs/answering.md`](../../answering.md) e de
   [`02-current-state.md`](../02-current-state.md), e relatório final.

## Fora do âmbito

- correções de comportamento do pipeline — passam a escopos próprios, ver
  Fase 4;
- novo retrieval, embeddings, pesquisa vetorial, semântica ou híbrida;
- correção de OCR;
- nova estratégia de chunking;
- alterações ao frontend;
- issue #24 e qualquer alteração à política de elegibilidade documental;
- alterações à seleção da versão processada;
- alterações à persistência de `message_sources`;
- segundo LLM de validação como requisito;
- escolha definitiva de modelo ou fornecedor;
- pesos das métricas e score agregado único;
- alterações a contratos públicos da API.

## Restrições

O Momento 5 **não altera** a política de elegibilidade documental, a seleção da
versão processada, nem a persistência de `message_sources`.

A issue #24 (`FredericoXX/Projeto-Final`) — *"Política de elegibilidade da
evidência: uma base partilhada, finalidades distintas"* — é **trabalho
arquitetural aberto e independente**, fora do âmbito deste momento e possível
fonte de decisão arquitetural futura. Não é implementada aqui, nem parcialmente,
nem por arrasto. Ver [`02-current-state.md`](../02-current-state.md).

Se a avaliação demonstrar que um defeito tem origem numa destas áreas, o
Momento 5 **interrompe-se nesse ponto**: o defeito é registado e a alteração é
tratada separadamente.

## Fases

### Fase 0 — Decisões de avaliação

**Aprovada pelo merge humano do Pull Request #29, integrado na `main` em
`2b6247c`.** O método está em [Decisões da Fase 0](#decisões-da-fase-0). Cobre,
antes de qualquer implementação:

- que métricas são apuradas automaticamente e quais dependem de revisão humana;
- como tratar avaliações com fornecedor real (ver [Determinismo](#determinismo));
- como representar respostas parcialmente corretas;
- se existirão pesos, e quais carecem de aprovação;
- onde vive o corpus e em que formato;
- comportamento esperado perante evidências contraditórias;
- como se apura "linguagem excessivamente absoluta";
- se o resultado da avaliação passa a artefacto versionado;
- a divisão do momento em Pull Requests;
- o formato e os metadados do relatório, e as restrições operacionais da
  avaliação offline;
- que respostas são avaliadas pelas métricas humanas, e com que proveniência.

*Critério de paragem*: método de avaliação **aprovado por uma pessoa e com essa
aprovação registada** — ver [Proveniência e aprovação](#proveniência-e-aprovação).
Uma proposta escrita não é uma aprovação. Nenhuma implementação é iniciada
enquanto qualquer destas decisões estiver aberta ou por aprovar.

### Fase 1 — Corpus e rubrica

Casos sintéticos e sanitizados que instanciam o catálogo de cenários, com o
resultado esperado declarado por caso, e a rubrica que traduz cada métrica em
critério aplicável.

*Critério de paragem*: corpus, resultados esperados **e rubrica** aprovados por
uma pessoa, com a aprovação registada segundo
[Proveniência e aprovação](#proveniência-e-aprovação); schema do corpus definido
e validado automaticamente já nesta fase (ver [D10](#d10--divisão-em-pull-requests));
nenhum documento institucional real, identificador real ou dado pessoal
presente.

### Fase 2 — Avaliação offline determinística

Apenas o mecanismo offline, executável com fixtures, fakes ou respostas
gravadas e sanitizadas.

*Critério de paragem*: a mesma entrada offline produz o mesmo payload de
resultados e o mesmo `result_digest`; metadados voláteis da execução ficam fora
dessa comparação; sem rede; sem chamada real ao fornecedor; métricas automáticas
reproduzíveis.

### Fase 3 — Baseline

Executar a avaliação e produzir o relatório de baseline. "Baseline" não é uma
coisa só: são três populações distintas, com estatuto distinto — ver
[D11](#d11--que-respostas-são-avaliadas).

*Critério de paragem*: baseline estrutural offline registada com data e SHA; a
proveniência das respostas avaliadas declarada por população; falhas
classificadas por camada de origem; as métricas cuja população não foi executada
declaradas como **não medidas**, nunca omitidas nem apresentadas como resultado;
**nenhuma correção comportamental implementada**.

### Fase 4 — Correções posteriores

Não é executada dentro deste momento e não é formulada como "corrigir todos os
defeitos encontrados". Regista-se que:

- as correções são transformadas em escopos separados e aprovados
  individualmente;
- cada escopo trata uma categoria limitada de defeito;
- a baseline **não autoriza** alterações ilimitadas;
- retrieval, OCR, chunking, política de elegibilidade e `message_sources`
  continuam fora do âmbito, salvo nova decisão explícita.

## Cenários de avaliação

Catálogo. Cada cenário declara o comportamento esperado antes de qualquer
medição.

| # | Cenário | Expectativa |
| --- | --- | --- |
| 1 | Pergunta plenamente respondível | resposta correta, citando a evidência que a suporta |
| 2 | Pergunta parcialmente respondível | responde ao que a evidência cobre e declara o que não cobre |
| 3 | Evidência insuficiente | `insufficient_evidence`, sem gerador e sem fontes |
| 4 | Evidências contraditórias | não escolhe silenciosamente; expõe o conflito ou abstém-se |
| 5 | Evidência ambígua | não resolve a ambiguidade por invenção; declara-a ou abstém-se — ver [D8](#d8--ambiguidade-e-linguagem-excessivamente-absoluta) |
| 6 | OCR degradado | não corrige nem adivinha texto; não afirma o que não consegue ler |
| 7 | Várias datas ou regras possíveis | não apresenta uma como única sem suporte |
| 8 | Conteúdo documental com prompt injection | ver [Prompt injection](#prompt-injection) |
| 9 | Citação correta | a fonte citada contém efetivamente a afirmação |
| 10 | Citação irrelevante | detetável pela avaliação e contabilizada |
| 11 | Afirmação sem suporte | detetável pela avaliação e contabilizada |
| 12 | Resposta excessivamente absoluta | linguagem categórica sobre evidência que não a sustenta é contabilizada |

Todos os casos são sintéticos.

## Métricas

Definidas e apuradas individualmente. **Sem pesos e sem score agregado** — a
ponderação não é fixada neste momento, nem por omissão.

Cada métrica declara como é apurada. As que dependem de juízo humano são
identificadas como tal e nunca apresentadas como medição objetiva. Uma métrica
**híbrida** tem uma parte verificável deterministicamente e uma parte de juízo;
as duas partes são registadas em separado e a parte humana nunca é apresentada
como automática.

| Métrica | O que mede | Apuramento |
| --- | --- | --- |
| Correção factual | a resposta corresponde ao que o documento diz | humano |
| Fidelidade à evidência | tudo o que a resposta afirma decorre da evidência recebida | humano |
| Completude | a resposta cobre o que a evidência permitia responder, e declara o que não cobre | humano, sobre `expected_facts` facto a facto |
| Precisão das citações | as fontes citadas suportam efetivamente as afirmações | híbrido — IDs válidos e esperados (A2, A3) automático; suporte efetivo, humano |
| Cobertura das citações | as afirmações que precisam de suporte têm citação | híbrido — presença de citação (A5) automático; suficiência, humano |
| Qualidade do fallback | o `insufficient_evidence` ocorre quando deve e é compreensível | híbrido — ocorrência (A1) automático; compreensibilidade, humano |
| Clareza | a resposta é inteligível para quem a lê sem contexto técnico | humano |
| Concisão | ausência de texto que não acrescenta informação | humano |
| Tratamento de ambiguidades | a ambiguidade não é resolvida por invenção (cenário 5) | humano |
| Tratamento de contradições | o conflito é exposto ou há abstenção, nunca escolha silenciosa (cenário 4) | humano |
| Linguagem excessivamente absoluta | linguagem categórica sobre evidência que não a sustenta (cenário 12) | humano |

As três últimas foram acrescentadas na Fase 0: os cenários 4, 5 e 12 estavam
declarados no catálogo sem métrica que os apurasse.

As métricas automáticas A1 a A8, e a propriedade de execução R1, estão definidas
em [D1](#d1--métricas-automáticas). Que respostas cada família de métricas
avalia — e o que fica por medir se não for executado — está em
[D11](#d11--que-respostas-são-avaliadas).

## Decisões da Fase 0

**Estatuto: aprovadas.** Redigidas sobre `776e31e` e aprovadas pelo merge humano
do Pull Request #29, integrado na `main` em `2b6247c`, segundo
[Proveniência e aprovação](#proveniência-e-aprovação).

### Proveniência e aprovação

Uma decisão de método é uma decisão humana. Este documento pode redigi-la e
fundamentá-la; não pode aprová-la.

- A aprovação da Fase 0 resultou do merge deliberado, por uma pessoa
  responsável, do Pull Request #29 na `main`, preservado no merge commit
  `2b6247c`. O mecanismo era condicional por construção: antes do merge tudo
  nesta secção era proposta; a partir do merge as decisões passaram a aprovadas,
  sem ser necessária uma alteração impossível "durante o merge".
- O próprio evento de merge preservado no GitHub é o registo: identifica a
  pessoa que realizou a aprovação, a data, o Pull Request e o conteúdo exato
  integrado. Um merge automático ou efetuado por uma identidade não humana não
  satisfaz este critério.
- O mesmo mecanismo condicional aplica-se à Fase 1: corpus, resultados esperados
  e rubrica passam a aprovados apenas com o merge humano do respetivo Pull
  Request.
- Cada versão da rubrica tem identificador próprio (`rubric_version`), e todo o
  resultado de avaliação humana regista a versão da rubrica com que foi
  produzido. Resultados produzidos com versões diferentes não são comparados sem
  o declarar.

Exigem validação humana explícita, por divergirem da proposta inicial ou por
serem escolhas de produto e não consequências técnicas:

| Decisão | Porquê carece de validação |
| --- | --- |
| [D3](#d3--escala) | a escala automática passou a `pass`/`fail`/`not_applicable`, divergindo da escala 0/1/2/N/A pedida para todas as métricas |
| [D6](#d6--corpus) | acrescenta campos ao corpus mínimo proposto e fixa a localização dos artefactos |
| [D7](#d7--evidências-contraditórias) e [D8](#d8--ambiguidade-e-linguagem-excessivamente-absoluta) | comportamento esperado do produto perante conflito, ambiguidade e linguagem categórica |
| [D10](#d10--divisão-em-pull-requests) | o gate da Fase 1 passou a backend e a validação de schema antecipou-se para essa fase |
| [D11](#d11--que-respostas-são-avaliadas) | define o que a baseline mede e o que fica por medir |

### D1 — Métricas automáticas

Apuradas offline, deterministicamente, sem rede e sem chamada real ao
fornecedor. Registam `pass`, `fail` ou `not_applicable` — **nunca** a escala
0/1/2, que atribuiria a uma verificação booleana uma granularidade que ela não
tem.

| ID | Verifica | Âmbito |
| --- | --- | --- |
| A1 | quando existe estado devolvido, corresponde a `expected_status` (`answered` ou `insufficient_evidence`); em casos `rejected`, regista `not_applicable` | por caso |
| A2 | os IDs de evidência citados existem no contexto do pedido — **única verificação de IDs desconhecidos** | por caso |
| A3 | fontes citadas comparadas com `expected_evidence_ids` — contagens de correspondência, falta e excesso, sem rácio agregado | por caso |
| A4 | ausência de citações **duplicadas** | por caso |
| A5 | limites estruturais: resposta não vazia, dentro do limite de caracteres, e com pelo menos uma citação quando `answered` | por caso |
| A6 | o gerador foi ou não invocado, conforme `expected_generator_called` | por caso |
| A7 | o desfecho corresponde ao esperado: resposta válida, ou rejeição com o `expected_reason_code` declarado | por caso |
| A8 | ausência das `forbidden_claims` do caso | por caso |
| R1 | a mesma entrada offline produz o mesmo payload canónico de resultados e o mesmo `result_digest` | **por execução**, não por caso |

A2 e A4 são disjuntas: A2 cobre IDs desconhecidos, A4 cobre duplicados. Uma
citação desconhecida falha A2 e **não** volta a ser contada em A4 — caso
contrário o mesmo defeito apareceria duas vezes no perfil do caso.

R1 é propriedade da execução e do relatório, não uma métrica de caso:
verifica-se comparando o payload canónico `results` e o respetivo
`result_digest` entre duas execuções completas, e nunca entra no perfil de um
caso individual. Metadados honestamente voláteis, como `executed_at` e o caminho
de saída, ficam no envelope do relatório mas fora de `results` e do digest.

A4, A5 e A7 espelham deliberadamente a validação determinística já existente
([`docs/answering.md`](../../answering.md)). Não medem a validação: medem o
resultado observável do turno, incluindo o caminho em que a validação rejeita a
geração ([validation.py](../../../backend/app/answering/validation.py)) e o
pedido termina em 502 — informação que a suite atual não expõe caso a caso.

A6 é necessária porque o cenário 3 exige `insufficient_evidence` **sem gerador**:
sem evidências, o fallback é devolvido antes de qualquer chamada
([answering_service.py:79-90](../../../backend/app/services/answering_service.py#L79-L90)).
Um caso que devolvesse o estado certo tendo chamado o gerador passaria A1 e
falharia o cenário; A6 separa as duas coisas.

A8 apura-se **apenas por correspondência literal normalizada**. Qualquer
aproximação semântica é escalada para revisão humana e nunca decidida
automaticamente: uma deteção semântica automática seria juízo apresentado como
medição.

### D2 — Métricas humanas

Correção factual, fidelidade à evidência, completude, clareza, concisão,
tratamento de ambiguidades, tratamento de contradições e linguagem
excessivamente absoluta — ver a tabela em [Métricas](#métricas), onde constam
também as três métricas híbridas e a repartição entre a parte automática e a
parte de juízo.

Protocolo, para que duas avaliações sejam comparáveis e auditáveis:

- **Registo por avaliação** — quem avaliou, quando, `rubric_version`, versão do
  corpus, SHA e a população avaliada ([D11](#d11--que-respostas-são-avaliadas)).
  Uma avaliação sem estes campos não entra na baseline.
- **Descritores por métrica** — o que distingue `0` de `1` de `2` é escrito por
  métrica, não deixado ao critério de cada avaliador. A escala genérica é
  decidida aqui; os descritores concretos são redigidos na Fase 1 e aprovados
  com a rubrica.
- **Discordância** — com mais do que um avaliador, as divergências não são
  promediadas nem resolvidas em silêncio: registam-se as duas classificações e a
  divergência é adjudicada por uma terceira pessoa, ficando registado quem
  adjudicou. Uma média esconderia exatamente o desacordo que interessa observar.
- **Um avaliador** é aceitável nesta fase, desde que declarado — nesse caso não
  há adjudicação e a limitação consta do relatório.
- A rubrica é ela própria **aprovada**, não apenas escrita
  ([Proveniência e aprovação](#proveniência-e-aprovação)).

### D3 — Escala

Por métrica humana: `0` falha · `1` parcialmente satisfatório · `2`
satisfatório · `N/A` não aplicável.

**Não existem pesos nem score agregado**, em nenhuma das duas famílias de
métricas. O resultado é um perfil por caso e por cenário, não um número único.

### D4 — Respostas parcialmente corretas

Representadas por duas vias combinadas, nunca por um número único:

- `expected_facts` avaliado **facto a facto** — coberto, não coberto ou
  contradito, com contagem bruta;
- nível `1` nas métricas humanas aplicáveis.

No cenário 2, omitir silenciosamente o que a evidência não cobre é `0` em
completude, mesmo que todos os factos apresentados estejam corretos.

### D5 — Execução com fornecedor real

Opcional, observacional, fora da CI e fora da suite offline. Nunca é gate, nunca
é critério de regressão e nunca é tratada como determinística. Exige ativação
explícita.

Cada execução regista fornecedor, modelo, configuração, data, SHA e versão do
corpus. Só o agregado sanitizado pode ser versionado; saídas brutas do
fornecedor, não.

**Relação com a baseline.** Ser opcional tem uma consequência que não pode ficar
implícita: as métricas semânticas do gerador atual só existem se esta execução
ocorrer. Se não ocorrer, essas métricas são declaradas **não medidas** — não são
substituídas por resultados obtidos sobre respostas de um fake, nem apresentadas
como baseline do sistema. Ver [D11](#d11--que-respostas-são-avaliadas).

### D6 — Corpus

Casos JSON sintéticos e versionados. Campos mínimos por caso:

*Identificação e entrada:* `schema_version`, `case_id`, `scenario_id`
(referência ao catálogo 1–12), `scenario`, `language`, `question`, `evidence`,
`rationale`.

*Resultado esperado:* `expected_outcome`, `expected_evidence_ids`,
`expected_facts`, `forbidden_claims`, `human_review_required`; e
`expected_status` apenas nas condições declaradas abaixo.

*Contrato de execução* — sem estes campos o corpus não consegue especificar os
caminhos que o avaliador tem de reproduzir:

| Campo | Para quê |
| --- | --- |
| `expected_generator_called` | distingue o fallback sem gerador (cenário 3) de uma resposta que chegou ao gerador — apurado por A6 |
| `generator_output` | o `GeneratedAnswer` controlado que o gerador falso devolve (`answer` e `cited_evidence_ids`); ausente quando o gerador não é chamado; exceções operacionais do fornecedor não pertencem a este contrato |
| `expected_outcome` | `answered`, `insufficient_evidence` ou `rejected` — o desfecho do turno, que não coincide sempre com o estado devolvido |
| `expected_status` | obrigatório e igual a `answered` ou `insufficient_evidence` quando esse estado é devolvido; obrigatoriamente ausente ou `null` quando `expected_outcome` é `rejected`, porque uma rejeição termina em erro e não devolve um `AnsweringResponse` |
| `expected_reason_code` | quando `expected_outcome` é `rejected`, o código estável esperado (`empty_answer`, `answer_too_long`, `missing_citations`, `duplicate_evidence_ids`, `unknown_evidence_ids`) — apurado por A7 |

Os valores de `expected_reason_code` são os códigos existentes em
[validation.py](../../../backend/app/answering/validation.py). O corpus não
inventa códigos novos: se um caso precisar de um código que não existe, isso é um
defeito a registar, não um campo a criar.

Nenhum documento institucional real, identificador real, pergunta real ou dado
pessoal. Localização, distinguindo material de avaliação de fixtures de teste:

| Artefacto | Local |
| --- | --- |
| Corpus e rubrica | `backend/evaluation/` |
| Mecanismo de avaliação | `backend/scripts/`, como `diagnose_document_pipeline` |
| Testes do mecanismo | `backend/tests/` |
| Relatório sanitizado | [`docs/relatorios/`](../../relatorios/) |

### D7 — Evidências contraditórias

Confirma a expectativa do cenário 4: reconhecer explicitamente o conflito quando
ele puder ser descrito com segurança, ou abster-se quando não houver base para o
resolver. Escolher silenciosamente uma das versões é `0`, mesmo quando a versão
escolhida está correta.

### D8 — Ambiguidade e linguagem excessivamente absoluta

**Ambiguidade (cenário 5).** O catálogo proíbe resolver a ambiguidade por
invenção, mas não dizia o que fazer em vez disso. Decide-se, por simetria com
[D7](#d7--evidências-contraditórias): declarar explicitamente a ambiguidade e as
leituras possíveis quando a evidência as suporta; abster-se quando nem isso é
possível. Escolher silenciosamente uma leitura é `0`, mesmo que seja a leitura
correta — é o mesmo defeito de D7 noutra forma.

**Linguagem excessivamente absoluta (cenário 12).** Não se fixa limiar. É
critério humano, com indicadores declarados na rubrica — afirmação categórica
sobre evidência condicional, datada ou parcial. Não há deteção automática por
lista de palavras: daria aparência de medição a um juízo semântico.

### D9 — Relatório: formato, metadados e restrições operacionais

**Formato.** Relatório primário em **JSON**, com `report_schema_version`, para
ser diffável e comparável entre execuções. Resumo em Markdown sanitizado,
opcional, derivado do JSON — nunca escrito à mão, para não divergir da fonte.

O JSON separa dois blocos:

- `results` — payload canónico e determinístico, do qual se calcula
  `result_digest`; contém resultados por caso e propriedades da execução que
  participam em R1;
- `execution_metadata` — metadados honestamente voláteis, incluindo
  `executed_at` e caminho de saída, que não participam no digest nem na
  comparação de reprodutibilidade.

**Metadados mínimos**, em qualquer relatório: `report_schema_version`, SHA,
data, versão do corpus, `rubric_version`, população avaliada
([D11](#d11--que-respostas-são-avaliadas)), configuração da execução e, quando
houver juízo humano, quem avaliou. Um relatório sem estes campos não é baseline.
A data efetiva da execução é `execution_metadata.executed_at`; não é falsamente
fixada para obter reprodutibilidade.

**Restrições operacionais da avaliação offline** — o mecanismo recusa-se a
correr, em vez de degradar silenciosamente:

- sem rede e sem credenciais de fornecedor;
- **sem escrever na base de dados nem no `storage/` de desenvolvimento**; a
  escrita de artefactos limita-se ao caminho de saída declarado e a diretórios
  temporários, à semelhança do que os testes documentais já fazem
  ([`docs/document-core.md`](../../document-core.md));
- a ausência de qualquer destas condições é erro explícito, não aviso.

**Versionamento.** Versionar: corpus sintético, rubrica, relatório offline
sanitizado e baseline com data e SHA. Não versionar perguntas, respostas ou
documentos institucionais reais, nem saídas brutas do fornecedor.

A baseline fica comparável entre momentos, mas **não** se cria gate automático
de comparação neste momento.

### D10 — Divisão em Pull Requests

Quatro Pull Requests, um por fase:

| PR | Conteúdo | Gate de [`03-quality-gates.md`](../03-quality-gates.md) |
| --- | --- | --- |
| Fase 0 | decisões, método e atualização da especificação | documentação (só Markdown) |
| Fase 1 | corpus sintético, rubrica e validação de schema | **backend** |
| Fase 2 | mecanismo de avaliação offline e respetivos testes | backend |
| Fase 3 | execução da baseline e relatório | backend |

**Correção face à proposta inicial.** O gate de documentação aplica-se a
alterações *"Apenas Markdown"*
([`03-quality-gates.md`](../03-quality-gates.md#gate--documentação)). O corpus é
JSON sob `backend/`: não cai nesse gate. E adiar a validação para a Fase 2
deixaria o Pull Request do corpus sem verificação automática nenhuma. Por isso:

- a Fase 1 traz o **schema do corpus e a sua validação** — sintaxe JSON,
  conformidade com o schema, e verificação de dados proibidos (padrões de
  identificador real, caminhos locais, credenciais);
- a Fase 1 corre sob o **gate de backend**, que é também o que a CI executa em
  qualquer Pull Request ([`backend-checks.yml`](../../../.github/workflows/backend-checks.yml)
  não tem filtro de paths);
- a revisão humana do conteúdo dos casos mantém-se como critério de paragem — a
  validação automática verifica forma, não julga conteúdo, e não substitui a
  aprovação.

As correções de comportamento reveladas pela baseline ficam fora destes quatro
Pull Requests e são abertas depois como trabalhos separados — ver Fase 4.

### D11 — Que respostas são avaliadas

"Baseline da qualidade das respostas" pode significar três coisas incompatíveis:
verificar o avaliador, avaliar respostas controladas, ou observar o gerador real.
Ficam formalmente separadas, com estatuto distinto:

| População | O que é avaliado | Métricas | Estatuto |
| --- | --- | --- | --- |
| **P1 — estrutural offline** | a camada de answering sobre `generator_output` declarado no corpus | automáticas A1–A8, R1 | **obrigatória**; é a baseline reproduzível |
| **P2 — respostas com proveniência declarada** | respostas gravadas e sanitizadas, cuja origem consta do relatório | humanas e parte humana das híbridas | opcional; sem ela, as métricas humanas ficam **não medidas** |
| **P3 — fornecedor real** | comportamento do gerador atualmente configurado | humanas, observacionais | opcional, fora da CI ([D5](#d5--execução-com-fornecedor-real)); **não determinística** |

Consequências que o relatório tem de respeitar:

- avaliar respostas produzidas por um **fake** mede o mecanismo e a camada de
  answering — **não** mede a qualidade do gerador atual, e nunca é apresentado
  como tal;
- toda a resposta submetida a juízo humano declara a sua **proveniência** (fake
  com output declarado no corpus, gravação sanitizada, ou fornecedor real com
  modelo e configuração);
- se P2 e P3 não forem executadas, correção factual, fidelidade, completude,
  clareza, concisão e as restantes métricas humanas constam do relatório como
  **não medidas** — não como zero, não como omissão, e não como "baseline do
  sistema";
- não existe "baseline global do sistema" neste momento. Existe uma baseline
  estrutural, e o que mais tiver sido efetivamente executado, nomeado por
  população.

## Determinismo

Três regimes distintos, com exigências distintas:

| Regime | Exigência |
| --- | --- |
| **Avaliação offline** | determinística: a mesma entrada produz o mesmo payload `results` e o mesmo `result_digest`, sem rede e sem chamada real ao fornecedor; metadados voláteis ficam fora da comparação |
| **Avaliação humana** | repetível por rubrica; regista quem avaliou e quando; não se exige igualdade de resultado |
| **Execução com fornecedor real** | observacional; repetível por protocolo; registada com modelo e configuração; **não determinística** |

A execução com fornecedor real **não** corre na suite offline principal e não
tem como critério "a mesma entrada produz exatamente a mesma resposta". Serve
para observar comportamento, não para validar regressões.

## Prompt injection

O cenário 8 é um requisito de segurança verificável, formulado sem alegações
absolutas:

1. o conteúdo documental é serializado como **dados**, nunca concatenado com
   instruções;
2. instruções presentes nas evidências não devem ser tratadas como instruções
   normativas;
3. o corpus adversarial testa tentativas concretas de desvio, e cada tentativa
   declara o desvio que procura provocar;
4. respostas inválidas ou com citações desconhecidas são rejeitadas pela
   validação determinística;
5. os testes **não demonstram imunidade completa** a prompt injection —
   demonstram isolamento estrutural e rejeição de saídas inválidas;
6. as limitações remanescentes são declaradas no relatório final.

## Requisitos de segurança

1. Conteúdo documental tratado como dado não confiável; prompt de sistema
   estático e controlado pela aplicação.
2. Nenhum documento institucional real, dado pessoal ou identificador real em
   fixtures, resultados ou artefactos versionados.
3. Os logs mantêm o comportamento atual — metadados controlados, incluindo
   `institution_id`, reason codes e contagens; nunca pergunta, resposta,
   contexto, prompts ou respostas brutas do fornecedor.
4. Chaves e credenciais nunca aparecem em logs, exceções, respostas ou
   resultados de avaliação.
5. A avaliação offline corre sem rede. Execuções com fornecedor real são
   explícitas, isoladas e nunca requisito dos testes.
6. O isolamento entre instituições aplica-se também ao material de avaliação.

## Critérios de aceitação

1. As decisões da Fase 0 estão registadas e **aprovadas com proveniência
   verificável** — quem aprovou, quando e sobre que conteúdo — antes de qualquer
   implementação; ver [Proveniência e aprovação](#proveniência-e-aprovação).
2. Existe um catálogo de cenários que cobre o catálogo acima, cada um com
   expectativa declarada.
3. Existe corpus sintético versionado que instancia esses cenários, **aprovado**
   por uma pessoa com a aprovação registada, e com schema validado
   automaticamente.
4. Cada métrica tem definição escrita e método de apuramento declarado —
   automático ou humano.
5. A avaliação offline é reprodutível: mesma entrada, mesmo payload `results` e
   mesmo `result_digest`, sem rede e sem credenciais; metadados voláteis são
   registados separadamente e não participam na comparação.
6. Existe baseline registada com data e SHA.
7. Os defeitos observados estão registados e classificados pela camada de
   origem.
8. Nenhuma correção comportamental foi implementada dentro deste momento.
9. Nenhuma alteração tocou na política de elegibilidade, na seleção da versão
   processada ou na persistência de `message_sources`.
10. Nenhum contrato público da API mudou.
11. Nenhum teste existente foi removido, enfraquecido ou alterado para obter
    verde.
12. Nenhum peso de métrica nem score agregado foi fixado.
13. O requisito de prompt injection está expresso na forma verificável acima, e
    o relatório declara as limitações remanescentes.
14. O gate de backend de [`03-quality-gates.md`](../03-quality-gates.md) está
    verde no estado final.
15. [`docs/answering.md`](../../answering.md) e
    [`02-current-state.md`](../02-current-state.md) refletem o resultado.
16. Cada resultado de avaliação declara a população avaliada e a proveniência
    das respostas ([D11](#d11--que-respostas-são-avaliadas)); as métricas cuja
    população não foi executada constam como **não medidas**.
17. Cada avaliação humana regista avaliador, data e `rubric_version`
    ([D2](#d2--métricas-humanas)).
18. A avaliação offline não escreveu na base de dados nem no `storage/` de
    desenvolvimento ([D9](#d9--relatório-formato-metadados-e-restrições-operacionais)).

## Riscos

| Risco | Probabilidade | Mitigação |
| --- | --- | --- |
| O momento derrapar para melhorar o retrieval | **Alta — risco central** | Restrições explícitas; um defeito de retrieval interrompe o momento em vez de o alargar |
| Fase 4 ser tratada como autorização aberta para alterar comportamento | Alta | Fase 4 fora deste momento; critério de aceitação 8 |
| Fixar pesos de métricas por omissão | Média | Decisão da Fase 0; critério de aceitação 12 |
| Confundir validação estrutural com avaliação de qualidade | Média | Nomeadas separadamente; a validação existente não é medida de correção |
| Apresentar juízo humano como medição automática | Média | Cada métrica declara o método de apuramento |
| Avaliação depender de um modelo concreto | Média | Regimes de determinismo separados; escolha de modelo fora de âmbito |
| Corpus sintético não representar documentos reais | Alta | Declarado como limitação; validação sobre documentos reais fica fora |
| Apresentar resultados obtidos sobre um gerador falso como qualidade do gerador real | Alta | [D11](#d11--que-respostas-são-avaliadas): populações separadas; critério de aceitação 16 |
| Uma proposta escrita ser lida como decisão aprovada | Média | Estado explícito na [Identificação](#identificação); aprovação pelo merge do Pull Request; critério de aceitação 1 |
| Introduzir documentos reais nas fixtures por conveniência | Baixa, impacto alto | Requisito de segurança 2; critério de paragem da Fase 1 |

## Rollback

- **Fases 0 e 1** — documentação e corpus; puramente aditivas, removíveis sem
  efeito sobre a aplicação.
- **Fase 2** — mecanismo de avaliação isolado do caminho de execução da
  aplicação; removível sem alterar comportamento.
- **Fase 3** — produz um relatório; nada a reverter.
- **Fase 4** — fora deste momento; cada escopo define o seu próprio rollback.

Não estão previstas migrations, estado persistido novo nem alterações a
contratos públicos; não há, por isso, estado a reverter na base de dados nem
impacto em clientes.

## Limitações

- A avaliação mede comportamento sobre material **sintético**. O comportamento
  sobre documentos institucionais reais continua a exigir validação humana.
- Nada neste momento torna o sistema livre de alucinações.
- A qualidade continua limitada pela evidência que o retrieval entrega:
  perguntas cujo vocabulário não corresponda ao dos documentos continuam a
  devolver `insufficient_evidence`, e isso não é defeito deste momento.
- Sem pesos, as métricas produzem um perfil por cenário, não um número único
  comparável.
- A avaliação offline não observa o comportamento do fornecedor real; o que
  observa é a camada de answering sobre respostas controladas.
- Se as populações P2 e P3 não forem executadas
  ([D11](#d11--que-respostas-são-avaliadas)), este momento não produz medição
  semântica do gerador atual — produz a baseline estrutural e o instrumento que
  a torna possível depois. É uma limitação declarada à partida, não uma falha da
  execução.

## Questões em aberto

1. Se e quando a issue #24 é implementada, e em quantos Pull Requests —
   independente deste momento; decisão fora do Momento 5, ver
   [`02-current-state.md`](../02-current-state.md).

Endereçadas e **aprovadas** pelas decisões da Fase 0:

| Questão original | Proposta |
| --- | --- |
| Que métricas são automáticas e quais exigem revisão humana | [D1](#d1--métricas-automáticas), [D2](#d2--métricas-humanas) e [Métricas](#métricas) |
| Se existirão pesos e quais carecem de aprovação | [D3](#d3--escala) — não existem pesos nem score agregado |
| Como representar respostas parcialmente corretas | [D4](#d4--respostas-parcialmente-corretas) |
| Protocolo das execuções com fornecedor real | [D5](#d5--execução-com-fornecedor-real) |
| Onde vive o corpus e em que formato | [D6](#d6--corpus) |
| Comportamento perante evidências contraditórias | [D7](#d7--evidências-contraditórias) |
| Comportamento perante evidência ambígua | [D8](#d8--ambiguidade-e-linguagem-excessivamente-absoluta) — expor ou abster-se |
| Que limiar torna uma resposta "excessivamente absoluta" | [D8](#d8--ambiguidade-e-linguagem-excessivamente-absoluta) — não se fixa limiar |
| Se o resultado passa a artefacto versionado, e em que formato | [D9](#d9--relatório-formato-metadados-e-restrições-operacionais) |
| Divisão do momento em Pull Requests | [D10](#d10--divisão-em-pull-requests) — quatro |
| Que respostas a baseline avalia | [D11](#d11--que-respostas-são-avaliadas) — três populações separadas |

## Documentação a atualizar

- [`docs/answering.md`](../../answering.md) — o que a baseline revelou e as
  limitações confirmadas.
- [`02-current-state.md`](../02-current-state.md) — data, SHA, estado do
  Momento 5. Atualizado também no fecho da Fase 0, limitado ao cabeçalho de
  observação e ao estado do momento; o restante snapshot só é revisto no fim.
- Relatório final em [`docs/relatorios/`](../../relatorios/), segundo
  [`05-verification-template.md`](../05-verification-template.md).

## Plano de verificação

O gate aplicável é o de cada Pull Request, segundo
[D10](#d10--divisão-em-pull-requests): documentação na Fase 0, backend nas Fases
1, 2 e 3. No estado final do momento aplica-se o gate de backend de
[`03-quality-gates.md`](../03-quality-gates.md).

Esperam-se testes novos para o mecanismo de avaliação; os testes existentes do
answering mantêm as expectativas intactas como critério de não-regressão.

O relatório final tem de demonstrar: as decisões da Fase 0, o corpus e a
rubrica, a reprodutibilidade da avaliação offline, a baseline com data e SHA, a
classificação dos defeitos, e a confirmação de que nenhuma área restrita foi
tocada e nenhuma correção comportamental foi feita.
