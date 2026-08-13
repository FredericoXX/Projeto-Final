# A2.2 — Especificação científica da política de decisão agêntica

**Observação:** 2026-08-13 · `main` em
`6ae9badefc81f90135feb726be10a750c80105d6` · repositório
`FredericoXX/Projeto-Final`

**Natureza:** caracterização, reconciliação científica, revisão da literatura e
modelação de domínio. **Não implementa** `DecisionPolicy` nem qualquer
mapeamento entre contratos. Nenhum ficheiro de produção foi tocado para produzir
este documento.

**Revisão após leitura crítica** (2026-08-13, antes do commit) — três correções
materiais, registadas aqui porque alteram conclusões e não apenas redação:

1. **`ESCALATE` era internamente contraditório.** A secção 7.6.1 reservava-o para
   a transferência técnica do caso, enquanto O6 recomendava o reencaminhamento
   informativo como forma de `ESCALATE`. Sob a primeira regra, `ESCALATE` nunca
   ocorreria e a ontologia colapsaria em três ações. **Resolvido**: `ESCALATE` é a
   **decisão** de dirigir o caso a uma pessoa; E1/E2 são níveis de maturidade da
   execução, não desfechos distintos (7.6.1, O6).
2. **Valores atribuídos ao juiz LLM de [L2] eram incorretos.** O intervalo de F1
   citado misturava duas tarefas de classificação distintas. **Removido**; ver a
   ressalva em 6.1.
3. **`RetrievalResult` não identifica um snapshot reprodutível.** Estava
   classificado como `FACT`; `score_semantics.version` identifica a configuração
   de scoring, não o corpus nem a execução. **Reclassificado** como lacuna
   (10.2, 11.4, 18).

**Convenção de estatuto.** Cada afirmação relevante é classificada:

| Marca | Significado |
| --- | --- |
| `FACT` | verificado no código, nos testes ou no GitHub neste SHA |
| `INFERENCE` | conclusão derivada de factos, identificada como raciocínio |
| `LITERATURE` | sustentado por fonte citada na secção 6 |
| `PROPOSAL` | proposta do autor, ainda não decidida |
| `DECISION REQUIRED` | não pode ser resolvido sem a orientadora, a Uni-CV ou experiência |

---

## 1. VEREDITO

```
A2.2: PRONTA PARA VALIDAÇÃO COM ORIENTADORA
```

A fase produziu o que se propôs produzir: as dimensões observáveis que devem
governar a decisão, os critérios candidatos de cada uma, uma matriz de decisão
com estado declarado linha a linha, os casos de fronteira, o esquema de anotação
futuro e o desenho de avaliação. Nenhuma regra normativa foi escrita em código.

**A2.3 está BLOQUEADA.** Sete decisões (O1–O7, secção 12) permanecem abertas, e
três delas — dados pessoais, escalação e resposta parcial — determinam o
comportamento observável do artefacto perante utilizadores reais. Implementar
`DecisionPolicy` antes dessa validação fixaria em código respostas que a
investigação ainda não deu.

---

## 2. Estado do repositório

`FACT` — verificado por `git` e `gh` em 2026-08-13.

```
branch de análise:  analysis/decision-policy-a2-2
BASE_SHA:           6ae9badefc81f90135feb726be10a750c80105d6
origin/main:        6ae9badefc81f90135feb726be10a750c80105d6
working tree:       limpa no início da análise
```

O estado de referência indicado no enunciado confirmou-se: `origin/main` está em
`6ae9bad`, que é o merge commit do **Pull Request #45**
(`feat: carregar provider OpenAI apenas quando resolvido`), integrado em
2026-08-13T01:24:56Z. `origin/main` **não** avançou para além desse ponto.

Pull Requests relevantes para esta análise, todos `MERGED`:

| PR | Tema | Merge |
| --- | --- | --- |
| #41 | fecho documental da issue #24 | `2b3c91e` |
| #42 | contratos provisórios de decisão (A2.1) | `e3f43f4` |
| #43 | contrato de resultado do retrieval (A3/A4.1) | `d6dd75b` |
| #44 | reconciliação documental e caracterização A6.0 | `73fe8ef` |
| #45 | carregamento tardio do provider (A6.1) | `6ae9bad` |

A **issue #24** está `CLOSED` / `COMPLETED` desde 2026-08-11T23:06:57Z.

### 2.1 Contratos de decisão — `backend/app/decision/contracts.py`

`FACT` — os quatro contratos existem exatamente com a forma esperada:

```
ScopeClass              IN_SCOPE · OUT_OF_SCOPE
RequestConstraint       PERSONAL_DATA_REQUIRED
AnswerabilityClass      FULLY_ANSWERABLE · PARTIALLY_ANSWERABLE · NOT_ANSWERABLE
DecisionOutcome         ANSWER · CLARIFY · ABSTAIN · ESCALATE
```

São `StrEnum` com valores serializados explícitos. O módulo importa apenas
`enum` — nenhuma dependência do domínio.

### 2.2 Ausência de consumidores

`FACT` — a pesquisa por `ScopeClass|RequestConstraint|AnswerabilityClass|DecisionOutcome`
em `backend/app` e `backend/tests` devolve ocorrências em exatamente **dois**
ficheiros:

| Ficheiro | Classificação |
| --- | --- |
| `backend/app/decision/contracts.py` | declaração |
| `backend/tests/test_decision_contracts.py` | teste de contrato |

**Zero consumidores funcionais.** Nenhum service, router, schema ou modelo
importa estes tipos. Apagar o módulo não alteraria o comportamento do sistema.
Conforme a secção 13 do enunciado, isto é deliberado e **não foi corrigido**.

A pesquisa por `escalat|escalona|handoff|ticket` em todo o backend devolve os
mesmos dois ficheiros. `FACT` — **não existe qualquer mecanismo de escalação
humana no artefacto**: nem serviço, nem modelo, nem endpoint, nem tabela.

### 2.3 Retrieval atual — `backend/app/retrieval/base.py`

`FACT`:

```
Retriever.search(db, query, context, top_k, official_only) -> RetrievalResult

RetrievalResult
├── evidence         tuple[Evidence, ...]   ordem do ranking
├── trace            RetrievalTrace         obrigatório
└── score_semantics  ScoreSemantics
```

`RetrievalTrace` (contrato neutro) contém apenas `candidates_evaluated` e
`result_count_before_limit`. O retriever lexical devolve a subclasse
`LexicalRetrievalTrace`, que acrescenta, entre outros,
`excluded_no_content_match`, `excluded_insufficient_coverage` e
`excluded_below_threshold`.

`FACT` — não existe `RetrievalOutcome`. O resultado **não** classifica a
suficiência da evidência.

### 2.4 Semântica do score

`FACT` — `ScoreSemantics` do retriever lexical declara:

```
kind                      ScoreKind.LEXICAL_RELEVANCE
version                   lexical_composite_v1
comparable_across_queries False
```

O `Evidence.score` é **relevância lexical composta e determinística** — somatório
ponderado de sinais de correspondência. A docstring de `ScoreKind` declara-o
explicitamente: *«Não é uma probabilidade, uma confiança, nem uma probabilidade
de a resposta estar correta.»*

A incomparabilidade entre consultas não é convenção, é consequência do
algoritmo: `coverage` é a fração dos termos **daquela** pergunta, e
`exact_phrase`, `ordered` e `proximity` valem 1.0 por construção numa pergunta de
um só termo.

> **Restrição normativa desta fase.** `INFERENCE` — é cientificamente inválido
> construir uma política de decisão que trate o score atual como *confidence*,
> compare scores entre consultas, ou derive um limiar global de answerability a
> partir dele. Qualquer futuro limiar tem de ser justificado sobre uma grandeza
> declaradamente calibrada, que hoje não existe.

### 2.5 Answering atual — `backend/app/services/answering_service.py`

`FACT` — o fluxo verificado no código:

```
evidência não vazia
  → select_evidence (orçamento de contexto)
  → generator.generate(...)
  → validate_generated_answer(...)        validação estrutural determinística
  → status = "answered", com as fontes citadas

evidência vazia
  → get_fallback_message(language)
  → status = "insufficient_evidence"
  → o gerador NUNCA é chamado
```

O comentário no código é explícito quanto ao que **não** acontece: o trace do
retrieval está disponível em `retrieval_result` e é *deliberadamente ignorado*,
porque «interpretar contagens ou motivos de exclusão seria decidir
answerability, que não pertence a esta etapa».

`FACT` — o caminho conversacional (`conversation_answering_service.ask`) delega
em `answering_service.ask` e propaga o `status` sem o reinterpretar.

### 2.6 Zero evidências: causas distintas, estado único

`FACT` — pelo menos quatro causas causalmente distintas terminam hoje no mesmo
`status="insufficient_evidence"`:

| Causa | Onde é observável hoje |
| --- | --- |
| nenhum chunk admissível (instituição, idioma, vigência, versão) | `RetrievalEligibility`; não distinguido no trace neutro |
| ausência de correspondência lexical | `excluded_no_content_match` |
| cobertura insuficiente de termos | `excluded_insufficient_coverage` |
| relevância abaixo do limiar configurado | `excluded_below_threshold` |

`INFERENCE` — as duas primeiras e as duas últimas são conceptualmente
diferentes: «o corpus não contém o documento» é uma propriedade do corpus,
enquanto «a pergunta não corresponde lexicalmente ao documento que existe» é uma
propriedade do mecanismo de recuperação. Confundi-las levaria a atribuir à
answerability uma falha de retrieval — precisamente o erro que a secção 11
deste relatório separa em métricas.

Conforme a secção 17 do enunciado, **não foi criado** `RetrievalOutcome`. A
questão de saber se esta distinção muda alguma decisão do assistente é tratada na
secção 7.4 e é uma das dependências de O2/O5.

---

## 3. Governação da investigação

Nem todas as fontes têm a mesma autoridade, e tratá-las como equivalentes é a
origem da maior parte das divergências da secção 4.

| Fonte | Autoridade | Pode fixar tecnologia? | Estado |
| --- | --- | --- | --- |
| **Proposta formal** (`Proposta Dissertação Carlos Frederico 2.docx`) | máxima quanto ao compromisso institucional: título, objetivos, âmbito, calendário | **Não** — deixa a abordagem tecnológica explicitamente em aberto | aprovada; assinada pela orientadora |
| **Documento v1** (`Assistente Virtual UniCV v1.docx`) | material de desenho do autor | Não | trabalho; não valida compromissos |
| **Estrutura da Dissertação** (`Estrutura da Dissertação.docx`) | plano de redação | Não | trabalho; contém pressupostos prematuros |
| **Constituição** (`docs/ai/01-project-constitution.md`) | máxima quanto a princípios duradouros do artefacto | Não (§«O que não é uma invariante») | canónica |
| **Estado atual** (`docs/ai/02-current-state.md`) | observacional | Não | canónico mas não normativo |
| **Código + testes na `main`** | máxima quanto ao comportamento presente | descreve, não fixa | `6ae9bad` |
| **Literatura científica** | sustenta ou refuta afirmações gerais | Não fixa política institucional | secção 6 |
| **Orientadora** | decide âmbito e formulação da investigação | Sim, por decisão explícita | pendente |
| **Evidência Uni-CV** | única fonte legítima para tipologia real, encaminhamentos e hierarquia documental | Sim, quanto a regras institucionais | **não recolhida** |

### 3.1 Documento formalmente excluído

`FACT` — `Plano de atividades - Dissertação.docx` foi aberto e identificado. O
seu conteúdo é:

```
Aplicação Móvel de Posicionamento Interior
Licenciatura em Engenharia Informática
Universidade de Cabo Verde — Praia, julho 2020
```

Trata-se do trabalho de licenciatura de 2020 do mesmo autor, sobre
posicionamento interior por Wi-Fi Fingerprinting. **Não é o plano deste
mestrado** e fica formalmente excluído das fontes desta investigação.

### 3.2 O que a proposta formal efetivamente compromete

`FACT` — leitura direta do documento. O título aprovado é:

> **Conceção e Avaliação de um Assistente Virtual Inteligente para Apoio ao
> Atendimento Académico em Instituições de Ensino Superior**

(Nota: o enunciado desta tarefa citou uma variante abreviada — «Assistente
Virtual Inteligente para Atendimento Académico em Instituições de Ensino
Superior». A forma acima é a que consta do documento aprovado e deve ser a
usada.)

Objetivos específicos aprovados:

```
OE1  revisão da literatura sobre abordagens inteligentes aplicadas ao
     atendimento académico no ensino superior
OE2  identificar os requisitos necessários para a conceção
OE3  propor e desenvolver um protótipo funcional
OE4  demonstrar e validar utilizando a Uni-CV como caso de aplicação
```

Três passagens da proposta formal são **diretamente relevantes** para a A2.2 e
merecem destaque, porque sustentam a camada de decisão sem impor tecnologia:

1. **Tipologia de pedidos, já na motivação:** «as dúvidas […] podem envolver
   diferentes tipos de pedidos, como **orientação geral**, **procedimentos
   administrativos**, **consulta de informação específica** ou **assuntos fora
   do âmbito institucional**».
2. **Encaminhamento humano como objeto de avaliação:** «Será analisada a
   capacidade do assistente em […] **reconhecer situações em que o pedido deve
   ser encaminhado para atendimento humano**».
3. **Métrica de encaminhamento:** «A avaliação técnica considerará métricas como
   […] a **adequação dos encaminhamentos realizados**».

`INFERENCE` — isto é decisivo para a reconciliação. A camada de decisão
(`ANSWER`/`CLARIFY`/`ABSTAIN`/`ESCALATE`) **não é um alargamento de âmbito**: é a
leitura direta de um compromisso já aprovado. A proposta formal compromete o
reconhecimento de pedidos que devem ir para humano e a medição da adequação
desse encaminhamento. O que a proposta **não** compromete é RAG, embeddings, base
vetorial, segundo LLM ou confidence score — que não aparecem no documento.

A proposta afirma explicitamente: «A abordagem tecnológica a adotar **será
definida com base na revisão da literatura e nos requisitos identificados**,
considerando critérios como precisão, rastreabilidade, transparência,
viabilidade técnica e necessidade de supervisão humana.»

---

## 4. Divergências

### 4.1 Proposta formal vs. documento v1

| Elemento | Proposta formal | v1 | Estatuto |
| --- | --- | --- | --- |
| Abordagem técnica | em aberto, a definir pela literatura | RAG fixado no objetivo geral | **divergência HIGH** |
| Validação por LLM | ausente | «validação **obrigatória** por modelo de linguagem» (OE2) | **divergência HIGH** |
| Confiança | ausente | «mecanismo de confiança **multifatorial**» (OE2, OE geral) | **divergência HIGH** |
| Escalação humana | comprometida como objeto de avaliação | comprometida e detalhada (QS3) | convergente |
| Esclarecimentos | ausente explicitamente | «solicitar esclarecimentos» (OE3) | v1 acrescenta |
| Objetivos específicos | 4 | 6 (OE1–OE6) | reformulação não aprovada |
| Questões secundárias | ausentes | QS1–QS5 | acrescento não aprovado |
| Avaliação | cenários + métricas + utilizadores | ablação C0/C1/C2 | v1 é mais ambicioso |

`INFERENCE` — o v1 converte em obrigação (`OE2`: «validação obrigatória»,
«mecanismo de confiança multifatorial») aquilo que a proposta formal deixou
como decisão a tomar. Adotá-lo tal como está fecharia, sem revisão da literatura,
exatamente as escolhas que a proposta mandou manter abertas.

`FACT` — nota de higiene bibliográfica: as referências [1] e [2] do v1 estão
formatadas como «Cornell University, Ithaca, NY, USA», que é a renderização de
preprints arXiv. Correspondem a Sharma (arXiv:2506.00054) e Gan et al.
(arXiv:2504.14891). Ambos são **preprints**, não publicações revistas por pares,
e devem ser identificados como tal (ver secção 6.0).

### 4.2 v1 vs. Estrutura da Dissertação

| Elemento | v1 | Estrutura | Estatuto |
| --- | --- | --- | --- |
| Questão principal | agêntico + RAG + validação + escalação | «arquitetura **Agentic RAG**, parametrizável e **multilingue**» | divergentes |
| Multilinguismo | não é eixo da RQ | **entra na própria RQ** e tem secção 2.4 + secção 4.8 | **divergência MEDIUM** |
| Escalação | eixo central (QS3) | mencionada, mas não é eixo da RQ | rebaixamento |
| Confiança | eixo central | não aparece na RQ | desaparecimento |

### 4.3 Estrutura vs. código na `main`

`FACT` — afirmações da Estrutura que pressupõem funcionalidade inexistente:

| Secção da Estrutura | Pressuposto | Estado real em `6ae9bad` |
| --- | --- | --- |
| 2.3, 4.7, 5.3, 5.4 | embeddings, base vetorial, pesquisa semântica, reclassificação | **não existem**; retrieval é lexical determinístico sobre PostgreSQL FTS. `pgvector` está instalado mas não é usado pela recuperação |
| 4.6, 5.2 | entidade «escalonamentos» no modelo de dados | **não existe** qualquer tabela, modelo ou serviço de escalação |
| 5.5 | «decidir entre responder, procurar documentos, solicitar esclarecimentos, reconhecer incerteza ou encaminhar» | **não implementado**; existe apenas o vocabulário sem consumidores |
| 5.6, 6.4 | recolha de feedback do utilizador | **não existe** |
| 2.4, 4.8 | multilinguismo como eixo próprio | **parcialmente real** — ver abaixo |

`FACT` — sobre multilinguismo, a afirmação equilibrada é: existe resolução de
idioma (`resolve_language`), `supported_languages` por instituição, configuração
FTS por idioma (`resolve_fts_config`, migration `e7b1c9d4a2f0`), filtragem de
evidência por compatibilidade de idioma e mensagens de fallback por idioma. Não
existe tradução, nem deteção automática de idioma da pergunta, nem corpus
paralelo.

`INFERENCE` — o multilinguismo implementado é infraestrutural e real, mas é
desproporcionado como eixo de uma questão de investigação e como capítulo
próprio da revisão da literatura. Não produz contributo científico distinguível.

### 4.4 Constituição vs. `main`

`FACT` — duas afirmações da Constituição são hoje factualmente falsas ou
obsoletas:

- **§5 (neutralidade de fornecedor)**: afirma que o SDK do fornecedor é
  «importado quando a aplicação é carregada». A A6.1 (PR #45) alterou essa
  propriedade: o adapter é importado apenas dentro do ramo
  `provider == "openai"` da composition root.
- **§4 (auditabilidade)**: afirma que a distinção entre «recuperável agora» e
  «legitimamente citado então» está «atualmente em discussão na issue #24». A
  issue está `CLOSED`/`COMPLETED` e a distinção está formalizada no código
  (`RetrievalEligibility` vs. `CitationPersistenceEligibility`).

Ambas foram corrigidas nesta branch — ver secção 15.

### 4.5 `02-current-state.md` vs. `main`

`FACT` — o cabeçalho declara que a A6.1 está na branch
`feat/provider-lazy-import-a6-1`, baseada em `73fe8ef`, e que «ainda não está
integrada na `main`». O PR #45 foi integrado em 2026-08-13; a afirmação é falsa.
Corrigida nesta branch — ver secção 15.

---

## 5. A ontologia atual não é uma política

`FACT` — os quatro contratos A2.1 são **vocabulário**. A própria docstring do
módulo o declara e enumera as tentações que recusa:

```
PERSONAL_DATA_REQUIRED  NÃO está mapeado para ESCALATE
PARTIALLY_ANSWERABLE    NÃO está mapeado para ANSWER, CLARIFY nem ABSTAIN
NOT_ANSWERABLE          NÃO está mapeado para ABSTAIN
```

Três propriedades merecem registo, porque condicionam tudo o que se segue:

1. **A capacidade técnica não define o âmbito.** `ScopeClass` classifica o
   *tema*, não a possibilidade de resposta. «Qual é a minha nota?» é `IN_SCOPE`
   mesmo que o protótipo não deva obter a nota.
2. **`RequestConstraint` não tem `NONE`.** A ausência de restrições é
   `frozenset()`. Isto é correto: uma restrição é uma propriedade que ocorre zero
   ou mais vezes, e um membro `NONE` dentro do conjunto seria um erro de
   modelação. Está protegido por teste.
3. **`AMBIGUOUS` não pertence a `AnswerabilityClass`.** A subespecificação é uma
   propriedade do pedido, não da cobertura da evidência. A A2.0 deixou a dimensão
   por estabilizar — é a D3 desta análise.

**Três níveis que não devem colapsar** (`INFERENCE`, sustentado pelo código):

```
RetrievalResult      o que a recuperação encontrou        (mecanismo)
AnswerabilityClass   se o encontrado chega para responder (relação pedido↔evidência)
DecisionOutcome      o que o assistente faz               (ação)
```

Um resultado com evidência pode ser `NOT_ANSWERABLE`; zero evidências não
explica, por si só, porque é que o sistema não pode responder.

### 5.1 Falha técnica não é desfecho

`FACT` — a docstring de `DecisionOutcome` já exclui explicitamente falhas
técnicas. O código é coerente: indisponibilidade do gerador levanta
`AnswerGeneratorUnavailableError` (503), falha do fornecedor levanta
`AnswerGenerationError` (502), e output inválido levanta
`InvalidGeneratedAnswerError` (502). Nenhuma destas produz um `status` de
resposta.

`INFERENCE` — a fronteira é: `DecisionOutcome` representa uma **escolha** do
assistente perante o pedido e a evidência. Timeout, indisponibilidade, output
malformado e erro de base de dados são estados em que o sistema **não escolheu**.
Classificá-los como `ABSTAIN` destruiria a métrica de abstenção, porque
misturaria comportamento correto com avaria. Ver caso C10 (secção 9).

---

## 6. Revisão da literatura

### 6.0 Protocolo e limites

`FACT` — pesquisa realizada em 2026-08-13 com acesso à Internet. Foram
privilegiadas fontes revistas por pares (ACL Anthology, PMLR, IEEE, EMNLP/NAACL);
preprints são identificados como tal e usados apenas quando recentes e sem versão
revista conhecida. Todos os metadados abaixo foram verificados na fonte
(ACL Anthology, PMLR, arXiv, IEEE). **Nenhum DOI foi inventado.**

`FACT` — o Elicit **não estava disponível** nesta sessão; a descoberta e a
verificação foram feitas por pesquisa e leitura direta das fontes primárias, que
é o que a sua utilização exigiria de qualquer modo.

Limite declarado: esta é uma revisão **dirigida a decisões** da A2.2, não a
revisão sistemática que a proposta formal compromete em OE1 (calendarizada para
setembro–novembro de 2026). Não substitui essa revisão; alimenta-a.

### 6.1 Estudos analisados

---

**[L1] Madhusudhan, N., Madhusudhan, S. T., Yadav, V., & Hashemi, M. (2025).**
*Do LLMs Know When to NOT Answer? Investigating Abstention Abilities of Large
Language Models.* COLING 2025, pp. 9329–9345. ACL Anthology:
`2025.coling-main.627`.

- **Pergunta:** os LLMs sabem abster-se quando não têm resposta?
- **Método:** avaliação *black-box*; dataset Abstain-QA; três estratégias de
  prompting; matriz de confusão própria (*Answerable-Unanswerable Confusion
  Matrix*, AUCM).
- **Resultado relevante:** mesmo modelos fortes (GPT-4, Mixtral 8x22b) têm
  dificuldade em abster-se; *strict prompting* e *chain-of-thought* melhoram, sem
  resolver. A dificuldade é maior em perguntas de raciocínio e conceptuais.
- **Limitação:** avalia o modelo isolado, não um pipeline com recuperação; a
  abstenção medida é sobre conhecimento paramétrico, não sobre evidência
  documental.
- **Transferibilidade:** média. Sustenta que a abstenção **não pode ser delegada
  ao modelo gerador** por prompting; é fraca precisamente onde o nosso domínio é
  exigente.
- **Decisão A2.2 informada:** reforça a arquitetura em que a decisão é **externa
  e determinística**, e não uma propriedade emergente do prompt. Sustenta também
  a adoção de uma **matriz de confusão por desfecho** como instrumento de
  avaliação (secção 11).

---

**[L2] Peng, X., Choubey, P. K., Xiong, C., & Wu, C.-S. (2025).**
*Unanswerability Evaluation for Retrieval Augmented Generation.* ACL 2025
(Volume 1: Long Papers), pp. 8452–8472. DOI `10.18653/v1/2025.acl-long.415`.

- **Pergunta:** como avaliar se um sistema RAG rejeita adequadamente pedidos
  inrespondíveis sobre uma dada base de conhecimento?
- **Método:** framework UAEval4RAG; taxonomia de **seis categorias** de pedidos
  inrespondíveis; síntese automática de consultas para qualquer base; duas
  métricas; juiz LLM validado contra anotação humana.
- **Taxonomia (verificada na fonte):**

  | Categoria | Definição |
  | --- | --- |
  | *Underspecified* | falta informação essencial para uma resposta correta |
  | *False-presupposition* | assenta em pressupostos ou crenças incorretos |
  | *Nonsensical* | erros tipográficos, barreira linguística, formulação ininteligível |
  | *Modality-limited* | formatos de entrada/saída não suportados pelo sistema |
  | *Safety-concerned* | pode conduzir a linguagem ofensiva, dano ou ilegalidade |
  | *Out-of-Database* | pertinente ao domínio, mas sem resposta na base de conhecimento |

- **Resultado relevante — o mais importante desta revisão para a A2.2:** a
  métrica *acceptable ratio* é **específica por categoria**. Para pedidos
  *underspecified*, são aceitáveis a recusa, **o pedido de esclarecimento** ou uma
  resposta multiperspetiva; para *out-of-database*, a resposta aceitável é a
  recusa. Ou seja, a literatura já distingue formalmente o tratamento adequado da
  subespecificação do tratamento adequado da ausência de fundamento.
  Adicionalmente: «nenhuma configuração única tem desempenho ótimo simultâneo em
  pedidos respondíveis e inrespondíveis».
- **Limitação:** as consultas inrespondíveis são **sintéticas**, geradas a partir
  da base; e o árbitro é um LLM, validado contra anotação humana. O artigo reporta
  essa validação **separadamente para duas tarefas distintas** — a classificação
  em *answered* / *unanswered* / *ask-for-clarification*, e a classificação em
  *acceptable* / *unacceptable* — com concordância elevada mas **não perfeita**, e
  reporta ainda que a concordância **entre os próprios anotadores humanos** fica
  abaixo de 1 em ambas as tarefas.

  > `FACT` — **os valores numéricos exatos não foram fixados nesta análise.** Duas
  > extrações independentes da tabela de validação produziram números divergentes,
  > e o PDF não foi legível por extração automática. Uma versão anterior deste
  > relatório citou um intervalo único de F1 que **misturava as duas tarefas** e
  > era, por isso, incorreto — foi removido. **Antes de a dissertação citar
  > dígitos, a tabela tem de ser lida diretamente no artigo.** O argumento desta
  > secção não depende dos valores exatos: depende de a concordância ser
  > imperfeita, o que o artigo estabelece.
- **Transferibilidade:** alta. *Out-of-Database* é exatamente o caso de um corpus
  institucional fechado, e a distinção com *Underspecified* é o problema central
  de `CLARIFY` no nosso domínio.
- **Decisão A2.2 informada:** (a) sustenta `LITERATURE` a separação de
  **especificidade** e **answerability** em dimensões distintas (D3 vs. D4);
  (b) sustenta que o desfecho adequado depende da **categoria da inrespondibilidade**
  e não de um mapeamento único; (c) o F1 do juiz é evidência contra usar
  LLM-as-judge como árbitro único do *ground truth* (secção 11.4).

---

**[L3] Sorodoc, I. T., Ribeiro, L. F. R., Blloshmi, R., Davis, C., & de Gispert,
A. (2025).** *GaRAGe: A Benchmark with Grounding Annotations for RAG Evaluation.*
Findings of ACL 2025, pp. 17030–17049. DOI `10.18653/v1/2025.findings-acl.875`.

- **Pergunta:** conseguem os LLMs identificar apenas a evidência relevante e
  produzir uma resposta *deflectiva* quando a informação é insuficiente?
- **Método:** 2366 perguntas de complexidade e dinamismo variados; mais de 35 000
  passagens anotadas individualmente quanto a *grounding*, provenientes de
  conjuntos documentais **privados** e da Web; respostas longas curadas por
  humanos.
- **Resultado relevante:** *Relevance-Aware Factuality Score* de no máximo **60%**
  mesmo restringindo os modelos às passagens anotadas; taxa de verdadeiros
  positivos em deflexão de no máximo **31%** quando a informação é insuficiente;
  F1 de atribuição a fontes relevantes de no máximo **58,9%**. O desempenho piora
  em **perguntas sensíveis ao tempo** e sobre **fontes privadas esparsas**.
- **Limitação:** benchmark maioritariamente em inglês e de domínio aberto; a
  anotação de *grounding* é cara e não trivialmente replicável à escala.
- **Transferibilidade:** **muito alta**, e desconfortável. As duas condições em
  que o desempenho degrada — sensibilidade temporal e fontes privadas esparsas —
  são exatamente as do nosso caso: calendários, editais e prazos com vigência, e
  um corpus institucional pequeno e fechado.
- **Decisão A2.2 informada:** (a) evidência forte de que **deixar a deflexão ao
  gerador não é seguro** (31% de TPR); a decisão tem de ser externa;
  (b) sustenta `LITERATURE` a **vigência** como critério de admissibilidade da
  evidência com peso próprio, e não como detalhe de metadados;
  (c) justifica separar métricas de qualidade da decisão das de qualidade da
  resposta (secção 11.3).

---

**[L4] Zhang, T., Qin, P., Deng, Y., Huang, C., Lei, W., Liu, J., Jin, D.,
Liang, H., & Chua, T.-S. (2024).** *CLAMBER: A Benchmark of Identifying and
Clarifying Ambiguous Information Needs in Large Language Models.* ACL 2024
(Volume 1: Long Papers). ACL Anthology: `2024.acl-long.578`.

- **Pergunta:** conseguem os LLMs identificar e clarificar necessidades de
  informação ambíguas?
- **Método:** benchmark de 12 000 instâncias com taxonomia de ambiguidade;
  avaliação de LLMs comerciais e abertos, com CoT e *few-shot*.
- **Resultado relevante:** utilidade prática limitada — os LLMs falham em
  identificar ambiguidade e em gerar perguntas de esclarecimento de qualidade,
  mesmo com CoT e *few-shot*; a causa apontada é falta de resolução de conflito e
  uso incorreto do conhecimento interno.
- **Limitação:** domínio aberto; ambiguidade de conhecimento geral, não
  ambiguidade procedimental institucional.
- **Transferibilidade:** média-alta para a *deteção*, baixa para a *geração* da
  pergunta de esclarecimento no nosso domínio.
- **Decisão A2.2 informada:** a deteção de subespecificação é difícil e não deve
  ser presumida resolvida. Reforça que D3 precisa de **critérios observáveis
  escritos** e de validação inter-avaliador (secção 10), e não de um
  classificador assumido como fiável.

---

**[L5] Xu, R., Qi, Z., Guo, Z., Wang, C., Wang, H., Zhang, Y., & Xu, W. (2024).**
*Knowledge Conflicts for LLMs: A Survey.* EMNLP 2024. ACL Anthology:
`2024.emnlp-main.486`.

- **Pergunta:** que tipos de conflito de conhecimento afetam os LLMs e como são
  tratados?
- **Método:** revisão sistemática; taxonomia em três famílias.
- **Resultado relevante:** três conflitos distintos — **context-memory**
  (contexto vs. conhecimento paramétrico), **inter-context** (entre peças de
  contexto) e **intra-memory** (dentro do conhecimento aprendido).
- **Limitação:** survey; não fornece critério operacional para decidir *quando* um
  conflito é material num domínio fechado.
- **Transferibilidade:** alta para a nomenclatura, baixa para a operacionalização.
- **Decisão A2.2 informada:** o conflito relevante para a D5 é o **inter-context**
  — duas fontes institucionais incompatíveis. Os outros dois são reais no nosso
  sistema mas pertencem à qualidade da geração, não à decisão. Isto delimita a
  D5 e evita que ela absorva o problema geral da alucinação.

---

**[L6] Kirichenko, P., Ibrahim, M., Chaudhuri, K., & Bell, S. J. (2025).**
*AbstentionBench: Reasoning LLMs Fail on Unanswerable Questions.* NeurIPS 2025.
arXiv:2506.09038.

- **Pergunta:** como se comportam os LLMs de fronteira perante perguntas que
  exigem abstenção?
- **Método:** benchmark holístico sobre **20 datasets**, avaliando **20 LLMs de
  fronteira**; cenários de resposta desconhecida, **subespecificação**, premissas
  falsas, interpretações subjetivas e **informação desatualizada**.
- **Resultado relevante:** a abstenção é um problema por resolver e **escalar os
  modelos ajuda pouco**; o *fine-tuning* para raciocínio **degrada a abstenção em
  24% em média**, com modelos a alucinar contexto em falta e a dar respostas
  definitivas mesmo quando a cadeia de raciocínio exprime incerteza. Um bom
  system prompt melhora na prática mas não resolve.
- **Limitação:** avaliação sobre modelos, não sobre pipelines com recuperação.
- **Transferibilidade:** alta enquanto **evidência contrária** a delegar a decisão
  ao gerador — inclusive contra a hipótese, popular, de que um modelo mais
  capaz resolveria o problema.
- **Decisão A2.2 informada:** contraindica fortemente a arquitetura em que o
  próprio gerador decide abster-se, e portanto contraindica a leitura simples do
  OE2 do v1 («validação obrigatória por modelo de linguagem») como solução
  suficiente. A taxonomia de cenários (subespecificação, premissa falsa,
  desatualização) é convergente com [L2] e sustenta D3 e D5.

---

**[L7] Cui, J., Chiang, W.-L., Stoica, I., & Hsieh, C.-J. (2025).**
*OR-Bench: An Over-Refusal Benchmark for Large Language Models.* ICML 2025, PMLR
vol. 267, pp. 11515–11542.

**[L8] Röttger, P., Kirk, H., Vidgen, B., Attanasio, G., Bianchi, F., & Hovy, D.
(2024).** *XSTest: A Test Suite for Identifying Exaggerated Safety Behaviours in
Large Language Models.* NAACL 2024 (Volume 1: Long Papers), pp. 5377–5400. ACL
Anthology: `2024.naacl-long.301`.

- **Pergunta (ambos):** com que frequência os modelos recusam pedidos inócuos?
- **Método:** XSTest — 250 prompts seguros em dez tipos, contrastados com 200
  inseguros; OR-Bench — 80 000 prompts de sobre-recusa em 10 categorias, ~1000
  difíceis e 600 tóxicos de controlo, sobre 32 modelos de 8 famílias.
- **Resultado relevante:** a segurança acrescida tem como efeito secundário
  sistemático a **sobre-recusa**, em que o modelo rejeita pedidos inócuos e se
  torna menos útil. Um modelo bem calibrado num benchmark pode sobre-recusar
  noutro.
- **Limitação:** ambos tratam recusa **por segurança**, não recusa por falta de
  fundamento documental. A transposição é analógica, não direta.
- **Transferibilidade:** conceptual. O mecanismo — critério conservador aplicado
  sem discriminação produz inutilidade medível — é o mesmo.
- **Decisão A2.2 informada:** justifica que a avaliação da policy **tem
  obrigatoriamente de medir o erro nos dois sentidos**. Uma policy que abstém ou
  escala sempre teria abstenção perfeita e utilidade nula. Fundamenta as métricas
  *over-answer* e *over-escalation* (secções 11.1 e 11.2) como par indissociável.

---

**[L9] Baan, J., Aziz, W., Plank, B., & Fernández, R. (2026).** *Clarify, Abstain
or Answer? Strategising in Conversation with Belief-Augmented Generation.*
arXiv:2605.25831. **PREPRINT** — sem versão revista por pares conhecida.

- **Pergunta:** como deve um modelo escolher entre responder, clarificar e
  abster-se, com base no seu estado de crença?
- **Método:** *Belief-Augmented Generation* — a distribuição sobre texto é tratada
  como representação probabilística da incerteza; a estratégia é escolhida a
  partir de respostas amostradas. Avaliação em seis modelos.
- **Resultado relevante:** os LLMs não modificados **raramente clarificam ou se
  abstêm**, ignorando a incerteza sobre a entrada e sobre os factos; o método
  melhora a exatidão e a fidelidade das decisões ao estado de crença; e —
  explicitamente — **«disentangling when to clarify from when to abstain» continua
  difícil**.
- **Limitação:** preprint; sem recuperação documental; a incerteza é paramétrica,
  não sobre evidência institucional.
- **Transferibilidade:** conceptual e limitada, mas o espaço de ações é o mesmo
  que o nosso, menos `ESCALATE`.
- **Decisão A2.2 informada:** é a confirmação mais direta de que a fronteira
  `CLARIFY` / `ABSTAIN` é um **problema em aberto reconhecido na literatura**, e
  não uma questão de engenharia já resolvida. Isto valoriza D3 como contributo
  potencial, e simultaneamente obriga a critérios escritos e testados por
  concordância inter-avaliador.

---

**[L10] Kostopoulos, G., Gkamas, V., Rigou, M., & Kotsiantis, S. (2025).**
*Agentic AI in Education: State of the Art and Future Directions.* IEEE Access,
vol. 13, pp. 177467–177491.

- **Resultado relevante:** revisão do estado da arte de IA agêntica em educação,
  caracterizando sistemas agênticos como entidades orientadas a objetivos com
  intervenção humana reduzida, e enfatizando autonomia limitada, rastreabilidade
  e supervisão humana como requisitos do domínio educativo.
- **Limitação:** revisão panorâmica; foco em tutoria e aprendizagem adaptativa,
  não em atendimento académico administrativo.
- **Transferibilidade:** média. Sustenta o enquadramento, não a policy.
- **Decisão A2.2 informada:** sustenta a definição operacional restrita de
  «agêntico» (secção 12, O1) e a recusa explícita de multi-agente e planeamento
  autónomo.

---

**[L11] Lee, D., Kim, S., et al. (2023).** *Asking Clarification Questions to
Handle Ambiguity in Open-Domain QA.* Findings of EMNLP 2023. ACL Anthology:
`2023.findings-emnlp.772`.

- **Resultado relevante:** o dataset CAmbigNQ (5653 perguntas ambíguas com
  passagens, respostas possíveis e pergunta de esclarecimento) e a decomposição do
  problema em **três tarefas separadas**: (1) deteção de ambiguidade,
  (2) geração da pergunta de esclarecimento, (3) QA após esclarecimento.
- **Transferibilidade:** alta quanto à **decomposição**.
- **Decisão A2.2 informada:** confirma `LITERATURE` que *detetar* que se deve
  clarificar é uma tarefa separável de *formular* a clarificação. A A2.2 modela
  apenas a primeira; a segunda é geração e pertence a outra camada. Isto mantém
  `CLARIFY` como desfecho sem obrigar a resolver a geração da pergunta agora.

---

### 6.2 Evidência contrária — síntese

Conforme a secção 44 do enunciado, a revisão foi conduzida a procurar o que
enfraquece as decisões desejadas, não a confirmá-las:

| Achado contrário | Fonte | Consequência para a A2.2 |
| --- | --- | --- |
| Abstenção não melhora com escala; *reasoning fine-tuning* piora-a em 24% | [L6] | não esperar que um modelo melhor resolva a decisão |
| Deflexão correta em ≤31% dos casos com informação insuficiente | [L3] | a decisão **não pode** ficar no gerador |
| Grounding factual ≤60% e atribuição ≤58,9% mesmo com passagens anotadas | [L3] | decidir `ANSWER` corretamente **não garante** boa resposta (secção 11.3) |
| Sobre-recusa é efeito sistemático de critérios conservadores | [L7], [L8] | medir obrigatoriamente os dois sentidos do erro |
| LLM-as-judge tem concordância elevada mas **imperfeita** com humanos; a concordância inter-humana também é < 1 | [L2] | não usar juiz LLM como fonte única de *ground truth*; valores exatos por confirmar (6.1) |
| LLMs falham a identificar e clarificar ambiguidade mesmo com CoT | [L4] | D3 exige critérios escritos e teste de concordância |
| Separar «quando clarificar» de «quando abster» continua difícil | [L9] | O4 é uma decisão real, não uma formalidade |
| Nenhuma configuração RAG é ótima em respondíveis e inrespondíveis simultaneamente | [L2] | existe um *trade-off* a caracterizar, não um ótimo a atingir |

### 6.3 O que a literatura **não** pode decidir

`INFERENCE` — a literatura sustenta que pedidos inrespondíveis devem ser
explicitamente reconhecidos, que a subespecificação merece tratamento distinto e
que a decisão deve ser externa ao gerador. **Não pode decidir**: que serviço da
Uni-CV recebe cada tipo de pedido; que categorias institucionais devem ser
escaladas; que hierarquia documental resolve conflitos; o que é «âmbito
institucional» nesta universidade. Essas decisões estão marcadas
`NEEDS_INSTITUTION` na secção 8.

---

## 7. Dimensões candidatas

`PROPOSAL` em todas as definições desta secção, salvo onde marcado de outro modo.
Primeiro as dimensões, depois a matriz — nunca o contrário.

### 7.1 D1 — Scope (`ScopeClass`) — **implementada como vocabulário**

> O **tema** do pedido pertence ao domínio institucional que este assistente foi
> configurado para apoiar?

- **Valores:** `IN_SCOPE`, `OUT_OF_SCOPE`.
- **Unidade de observação:** o tema do pedido, não a sua satisfazibilidade.
- **Relatividade:** o âmbito é **relativo à configuração de cada instituição**,
  não a uma noção universal de «assunto académico». `FACT` — já está assim
  documentado no contrato.

**Exemplos** (`IN_SCOPE`): prazos de matrícula; regulamento de avaliação;
funcionamento dos serviços académicos; como requerer um certificado; calendário
letivo; propinas; «qual é a minha nota?» (tema académico).

**Não-exemplos** (`OUT_OF_SCOPE`): previsão meteorológica; ajuda com um exercício
de programação; opinião política; questões de saúde pessoal.

**Confusões a evitar** — `OUT_OF_SCOPE` **não** significa:

| Situação | Dimensão correta |
| --- | --- |
| não existe documento que o suporte | D4 (`NOT_ANSWERABLE`) |
| exige dados individuais | D2 (`PERSONAL_DATA_REQUIRED`) |
| o pedido está ambíguo | D3 |
| a evidência recuperada é insuficiente | D4 |

**Evidência necessária:** `NEEDS_INSTITUTION` — a fronteira do âmbito da Uni-CV
não está documentada. Casos de fronteira reais (alojamento estudantil,
associação de estudantes, bolsas geridas por entidade externa, estágios) não são
decidíveis sem a instituição.

**Estado:** `PROVISIONAL` — a dimensão é sólida e está implementada; os seus
limites concretos dependem da configuração institucional.

---

### 7.2 D2 — Request constraints (`RequestConstraint`) — **implementada como vocabulário**

> Que propriedade **do pedido** impede que ele seja satisfeito apenas com
> documentação institucional geral?

- **Cardinalidade:** conjunto (zero ou mais). Ausência = `frozenset()`. `FACT`.
- **Valor atual:** `PERSONAL_DATA_REQUIRED`.

**Definição de `PERSONAL_DATA_REQUIRED`:** o pedido só pode ser satisfeito
substantivamente mediante acesso a informação específica de uma pessoa, que não
faz parte da documentação institucional geral.

**Discriminante** (`FACT`, já no contrato): **não** é a presença de um
possessivo.

| Pedido | Constraint? | Porquê |
| --- | --- | --- |
| «Qual é a minha nota a Álgebra?» | **Sim** | o valor pedido vive num registo individual |
| «Como posso consultar as minhas notas?» | **Não** | o procedimento está documentado |
| «Quantas cadeiras me faltam?» | **Sim** | exige o percurso individual |
| «Quantas cadeiras tem o curso de Engenharia Informática?» | **Não** | está no plano de estudos |

#### Candidatos a novos valores

Conforme a secção 25 do enunciado, um valor novo só existe se **mudar uma
decisão**, for **observável** e for **anotável de forma consistente**. Aplicando
o triplo teste:

**(a) `ADMINISTRATIVE_ACTION_REQUIRED`** — o pedido não pede informação, pede que
algo seja **feito** (inscrever, anular, alterar, pagar, submeter).

| Teste | Resultado |
| --- | --- |
| Muda uma decisão? | **Sim.** «Inscreva-me em Álgebra» não é respondível por documento algum, mas existe serviço humano competente — a distinção `ABSTAIN` vs. `ESCALATE` depende disto |
| Observável? | **Sim.** É a força ilocutória do pedido: imperativo/pedido de execução vs. pergunta |
| Anotável consistentemente? | **Provavelmente.** Fronteira difícil: «como me inscrevo?» (informação) vs. «inscreva-me» (ação) |

`FACT` — o v1 já coloca isto explicitamente fora do âmbito funcional: «Estão fora
do âmbito o acesso direto a notas, pagamentos ou inscrições, a **execução
automática de processos administrativos**». **Estado:** `PROVISIONAL` — recomendado,
sujeito a O2/O6.

**(b) `AUTHORITATIVE_DECISION_REQUIRED`** — o pedido solicita uma decisão ou
interpretação vinculativa sobre um caso concreto («posso ser dispensado da
propina?», «a minha justificação de falta é válida?»). O regulamento descreve a
regra geral; a aplicação ao caso é um ato de autoridade.

| Teste | Resultado |
| --- | --- |
| Muda uma decisão? | **Sim.** Responder com a regra geral pode ser lido como deferimento |
| Observável? | Parcialmente |
| Anotável consistentemente? | **Duvidoso** — sobrepõe-se a `PERSONAL_DATA_REQUIRED` e a D4 |

**Estado:** `NEEDS_SUPERVISOR` + `NEEDS_INSTITUTION`. **Recomendação: não
adicionar agora.** É real, mas o risco de anotação inconsistente é alto e
sobrepõe-se a dimensões existentes. Registado como candidato para reavaliação
depois da tipologia real de pedidos.

**(c) Rejeitados explicitamente:** `MODALITY_LIMITED` de [L2] (não aplicável —
não há entradas/saídas multimodais); `SAFETY_CONCERNED` de [L2] (real, mas é uma
preocupação transversal de segurança, não uma propriedade que distinga desfechos
neste domínio); `OUT_OF_DATABASE` de [L2] (é answerability, D4, não uma
propriedade do pedido — colocá-lo aqui confundiria dois níveis).

**Estado da dimensão:** `PROVISIONAL`.

---

### 7.3 D3 — Request specificity — **não implementada; nome não fixado**

> O pedido contém informação suficiente para determinar **o que** o utilizador
> quer saber?

`LITERATURE` — a separação desta dimensão face à answerability é sustentada por
[L2] (*underspecified* é categoria própria, com conjunto de respostas aceitáveis
distinto), [L6] (subespecificação como cenário próprio), [L4] e [L11]
(ambiguidade como tarefa separada de deteção).

- **Valores candidatos:** `SPECIFIED`, `UNDERSPECIFIED`.
- `PROPOSAL` — o nome `RequestSpecificity` é adequado, mas **não deve ser fixado
  nesta fase** (O4).

**Exemplos de `UNDERSPECIFIED`:** «Quando posso fazer isso?» (sem antecedente);
«Quais são os prazos?» (que prazos? de que processo?); «Preciso de que
documentos?» (para quê?).

**Não-exemplos:** «Qual é o prazo de matrícula para o 1.º ano em 2026/27?»
(específico); «Qual é o prazo?» numa conversa em que a mensagem anterior tratava
de matrícula (resolúvel por contexto conversacional — ver limitação abaixo);
«Qual é a política de faltas?» (geral, mas determinado — a resposta é o
documento).

**Confusão central a evitar:** *geral* ≠ *subespecificado*. Uma pergunta ampla com
resposta documental bem definida é `SPECIFIED`.

#### 7.3.1 Critério de resolubilidade — o núcleo de `CLARIFY`

`PROPOSAL` — o critério que torna D3 decisória, e que responde diretamente à
secção 28 do enunciado:

> **Teste de resolubilidade por esclarecimento.** Existe uma resposta plausível
> do utilizador `R`, sobre informação que **o utilizador possui**, tal que o
> pedido acrescido de `R` passe a ser pelo menos `PARTIALLY_ANSWERABLE` **a
> partir do mesmo corpus**?

- Se **sim** → `CLARIFY` é apropriado: a lacuna está no pedido.
- Se **não** → `CLARIFY` é inapropriado, mesmo que o pedido seja vago: a lacuna
  está no corpus ou no mandato, e perguntar apenas custa um turno ao utilizador e
  adia o desfecho real.

`LITERATURE` — este critério é a operacionalização da distinção que [L2] faz
entre *Underspecified* (esclarecimento aceitável) e *Out-of-Database* (recusa
aceitável), e responde ao problema que [L9] declara em aberto.

`INFERENCE` — corolário importante: **`CLARIFY` nunca é justificado por falha de
retrieval**. Se o documento não existe, nenhuma reformulação do utilizador o faz
existir. Pedir esclarecimento nessa situação é sobre-clarificação — o análogo,
neste domínio, da sobre-recusa de [L7]/[L8].

**Limitação declarada** — `FACT`: o `answering_service` atual **não usa memória
conversacional**; a pergunta é tratada isoladamente e o histórico não entra no
prompt nem no retrieval. Logo, «Qual é o prazo?» após uma mensagem sobre
matrícula é hoje indistinguível de subespecificação genuína. Isto é uma
**dependência real de D3**: anotar especificidade sobre turnos isolados e
avaliá-la sobre uma conversa mediria coisas diferentes.

**Estado:** `NEEDS_SUPERVISOR` (O4). É a dimensão com maior potencial de
contributo e a de anotação mais difícil.

---

### 7.4 D4 — Answerability (`AnswerabilityClass`) — **implementada como vocabulário**

> Até que ponto a evidência disponível suporta as partes substantivas do pedido?

**Unidade de análise proposta** (`PROPOSAL`): o pedido decompõe-se em **itens
pedidos** — as proposições distintas cuja satisfação o utilizador espera. «Qual é
o prazo de matrícula e quanto custa a propina?» tem dois itens.

`LITERATURE` — a decomposição segue o princípio de anotação por unidade de
[L3], que anota *grounding* passagem a passagem em vez de julgar a resposta como
um todo.

**Definições candidatas, sem números arbitrários:**

| Classe | Critério |
| --- | --- |
| `FULLY_ANSWERABLE` | **todos** os itens pedidos estão suportados por evidência admissível |
| `PARTIALLY_ANSWERABLE` | **pelo menos um** item suportado e **pelo menos um** não suportado |
| `NOT_ANSWERABLE` | **nenhum** item suportado |

`INFERENCE` — esta formulação evita limiares arbitrários: a graduação vem da
decomposição do pedido, que é anotável, e não de uma percentagem inventada sobre
scores que a secção 2.4 já mostrou não serem comparáveis.

**Um item está «suportado» quando** (`PROPOSAL`, cada condição justificada):

| Condição | Justificação |
| --- | --- |
| **Cobertura** — existe evidência que responde ao item, não apenas relacionada com o tema | é a definição de fundamentação |
| **Admissibilidade** — a evidência satisfaz `RetrievalEligibility` | `FACT`: já formalizado no código (issue #24) |
| **Vigência** — a fonte está válida na `reference_date` | `LITERATURE` [L3]: desempenho degrada em perguntas sensíveis ao tempo; `FACT`: `valid_from`/`valid_until` já existem em `Evidence` |
| **Ausência de conflito material** | ver D5 |
| **Suficiência** — a evidência permite uma resposta completa ao item, não apenas indícios | evita `ANSWER` sobre fragmentos |

**Não-exemplos de suporte:** documento que menciona «matrícula» mas não indica o
prazo; documento de outro ano letivo já expirado; excerto que remete para um
anexo não recuperado.

**Propriedade crítica** (`FACT`, já no contrato): esta classe descreve uma
relação **pedido ↔ evidência**. Um conjunto de evidências não vazio pode ser
`NOT_ANSWERABLE`; um conjunto vazio não distingue as causas da secção 2.6.

**Estado:** `PROVISIONAL` — os critérios são defensáveis; a sua estabilidade de
anotação exige o teste da secção 10.

---

### 7.5 D5 — Evidence conflict — **não implementada; deliberadamente em aberto**

> Existem fontes admissíveis com instruções materialmente incompatíveis para o
> mesmo item pedido?

`LITERATURE` [L5] — o conflito relevante é **inter-context**. Os conflitos
*context-memory* e *intra-memory* existem no sistema mas pertencem à qualidade da
geração, não à decisão.

**O que constitui conflito** (`PROPOSAL`): duas ou mais evidências admissíveis
que, para **o mesmo item pedido** e **sob as mesmas condições de aplicação**,
sustentam respostas mutuamente incompatíveis.

**O que não constitui conflito:**

| Situação | Porquê não |
| --- | --- |
| formulações diferentes do mesmo conteúdo | diferença textual não é incompatibilidade |
| regras diferentes para populações diferentes | condições de aplicação distintas; não colidem |
| documento geral + documento específico coerente | especialização, não conflito |
| granularidade diferente | complementaridade |

#### Famílias de conflito e resolubilidade documental

`PROPOSAL` — três famílias, com resolubilidade decrescente:

| Família | Resolúvel por regra documental? | Metadados disponíveis hoje |
| --- | --- | --- |
| **F1 — vigência**: uma fonte expirada, outra vigente | **Sim**, se a vigência estiver correta | `FACT`: `valid_from`, `valid_until` existem em `Evidence` |
| **F2 — versão**: duas versões do mesmo documento | **Sim** | `FACT`: `document_version_id` existe; `RetrievalEligibility` já exige a versão `processed` mais recente (C5) |
| **F3 — autoridade**: duas fontes vigentes, distintas e incompatíveis | **Só com hierarquia documental** | `FACT`: existe `official_source` (booleano); **não existe** qualquer campo de autoridade, emissor ou precedência normativa |

`INFERENCE` — F1 e F2 são, em grande medida, **já tratadas a montante** pela
política de admissibilidade da issue #24: uma fonte expirada ou uma versão
antiga tende a não chegar ao resultado. O conflito que sobra para a camada de
decisão é sobretudo **F3**, e para F3 o artefacto **não tem informação
suficiente**: `official_source` é binário e não ordena duas fontes ambas
oficiais.

> `NEEDS_INSTITUTION` — **não inventar hierarquia institucional.** Saber se um
> despacho revoga um regulamento, ou se um edital prevalece sobre o calendário
> geral, é matéria de direito interno da Uni-CV e não pode ser derivada nem da
> literatura nem do código.

**Estado:** `NEEDS_INSTITUTION` + `NEEDS_SUPERVISOR` (O5).

---

### 7.6 D6 — Human handoff — **não implementada em nenhuma forma**

> Quando é científica e institucionalmente adequado continuar o caso com uma
> pessoa?

**Discriminante proposto** (`PROPOSAL`) — o mais simples que separa as duas ações
sem apelar a juízos de dificuldade:

> **Existe um serviço ou pessoa, na instituição, com competência e meios para
> fazer avançar *este* caso?**
>
> - **Sim** → `ESCALATE` — o caso **continua**.
> - **Não** → `ABSTAIN` — o sistema **termina** sem resposta substantiva.

`INFERENCE` — este critério é institucional, não epistémico. Não pergunta se o
sistema sabe; pergunta se alguém pode continuar. É por isso que
`NOT_ANSWERABLE → ABSTAIN` não pode ser automático: um pedido sem fundamento
documental para o qual existe balcão competente é candidato a `ESCALATE`, não a
`ABSTAIN`.

#### 7.6.1 O que distingue `ESCALATE` de `ANSWER`

`FACT` — não existe qualquer mecanismo de escalação no artefacto (secção 2.2).

`INFERENCE` — a palavra «encaminhar» confunde duas coisas, e a fronteira **não
pode ser traçada pela maturidade da implementação**. Se `ESCALATE` só existisse
quando houvesse criação técnica de caso, então — não existindo esse mecanismo —
`ESCALATE` nunca ocorreria, a ontologia colapsaria em três ações, e a matriz de
confusão 4×4 e as métricas de escalação ficariam sem objeto. Isso tornaria
inavaliável precisamente o que a proposta formal se compromete a avaliar.

`PROPOSAL` — **a fronteira é o que o sistema decide sobre o pedido, não o
mecanismo de entrega:**

| Desfecho | Critério | Exemplo |
| --- | --- | --- |
| **`ANSWER`** | a necessidade de informação **fica satisfeita** por evidência documental — mesmo que o conteúdo da resposta nomeie um serviço | «Onde ficam os Serviços Académicos?» → resposta fundamentada com a localização |
| **`ESCALATE`** | o sistema determina que o pedido **não pode ser satisfeito automaticamente** e designa um destino humano competente, entregando o contexto necessário | «Qual é a minha nota?» → o pedido não é satisfeito; é dirigido ao serviço competente |

`INFERENCE` — o discriminante é: *o utilizador sai com a sua pergunta respondida
(`ANSWER`) ou com o seu caso direcionado (`ESCALATE`)?* Indicar um serviço como
**conteúdo** de uma resposta a uma pergunta documental é `ANSWER`; **decidir** que
o caso tem de ser tratado por uma pessoa é `ESCALATE`, independentemente de o
handoff ser automatizado.

`FACT` — isto é fiel à proposta formal, que compromete «**reconhecer** situações
em que o pedido deve ser encaminhado para atendimento humano». O compromisso
aprovado é sobre o **reconhecimento**, que é a decisão — não sobre a integração
técnica.

**Dois níveis de maturidade *dentro* de `ESCALATE`** — implementação, não
ontologia:

| Nível | O que o sistema faz | Requisitos | Estado |
| --- | --- | --- | --- |
| **E1 — decisão de encaminhamento estruturada** | regista o desfecho `ESCALATE`, o destino designado e o contexto a entregar; apresenta-o ao utilizador | tipologia de destinos institucionais | **implementável** após O6 |
| **E2 — transferência técnica do caso** | cria um caso que uma pessoa recebe e continua | canal, SLA, integração, proteção de dados | **inexistente**; exige decisão institucional |

`INFERENCE` — E1 e E2 produzem o **mesmo** `DecisionOutcome`. A diferença é o que
acontece a jusante da decisão, e é por isso que E1 é avaliável (a decisão está
registada e pode ser comparada com o rótulo esperado) sem que E2 exista.

**Estado:** `NEEDS_INSTITUTION` + `NEEDS_SUPERVISOR` (O6). É a dimensão com maior
dependência externa.

---

### 7.7 D7 — Outcome (`DecisionOutcome`) — **implementada como vocabulário**

Avaliação das quatro propriedades exigidas pela secção 37 do enunciado:

**1. São mutuamente distinguíveis?** `INFERENCE` — **sim, condicionalmente**. Há
dois pontos de colapso, ambos resolúveis por regra escrita:

| Par | Risco de colapso | Regra desambiguadora proposta |
| --- | --- | --- |
| `ANSWER` / `ESCALATE` | resposta que nomeia um serviço | secção 7.6.1: necessidade satisfeita (`ANSWER`) vs. caso direcionado (`ESCALATE`) |
| `CLARIFY` / `ABSTAIN` | lacuna vaga | secção 7.3.1: teste de resolubilidade |
| `ABSTAIN` / `ESCALATE` | baixo | secção 7.6: existe serviço competente? |

**2. São suficientes?** `INFERENCE` — sim, com uma ressalva. A resposta parcial
(D4 = `PARTIALLY_ANSWERABLE`) não tem desfecho próprio. Há duas modelações:

- **(i)** acrescentar um quinto desfecho (p. ex. `ANSWER_WITH_GAP`);
- **(ii)** manter `ANSWER` e exigir uma **propriedade obrigatória de lacuna
  declarada** na resposta.

`PROPOSAL` — recomenda-se **(ii)**. Um espaço de ações pequeno é mais anotável, e
a diferença entre responder tudo e responder parte com declaração explícita é uma
propriedade da resposta, não uma ação diferente. Isto é matéria de O3. **O enum
não foi alterado nesta fase.**

**3. São anotáveis?** `INFERENCE` — sim, dadas as regras acima. Sem elas, não.

**4. São coerentes com a questão de investigação?** `INFERENCE` — sim. Mapeiam
diretamente sobre a tipologia da proposta formal:

| Tipologia da proposta formal | Desfecho |
| --- | --- |
| orientação geral | `ANSWER` |
| procedimentos administrativos | `ANSWER` (procedimento) ou `ESCALATE` (execução) |
| consulta de informação específica | `ESCALATE` ou `ABSTAIN` (D2) |
| assuntos fora do âmbito institucional | `ABSTAIN` |

**Estado:** `SUPPORTED` quanto ao espaço de ações; `NEEDS_SUPERVISOR` quanto a O3.

---

### 7.8 `DecisionReason` — estrutura, não enumeração paralela

`PROPOSAL` — das duas opções da secção 38 do enunciado, recomenda-se **B**: uma
estrutura que **referencia as dimensões efetivamente observadas**, e não uma
enumeração paralela (`NO_EVIDENCE`, `PERSONAL_DATA`, `AMBIGUOUS`, …).

`INFERENCE` — justificação: uma enumeração paralela duplicaria a semântica das
dimensões e criaria duas fontes de verdade que divergiriam à primeira alteração —
exatamente o problema que a issue #24 resolveu para a admissibilidade da
evidência. Com a opção B, a razão é **derivável** dos valores observados e a
auditoria pode reconstruir o percurso, não apenas ler um rótulo.

**Não implementado.** A estrutura só pode ser fixada depois de as dimensões
estarem fixadas.

---

## 8. Matriz de decisão candidata

`PROPOSAL` — nenhuma linha marcada `NEEDS_*` é política final. A matriz cobre
**classes semanticamente distintas e fronteiras**, não o produto cartesiano.

Legenda: `—` = não aplicável / não avaliado nesse ramo; `∅` = conjunto vazio.

| # | Scope | Constraints | Specificity | Answerability | Conflict | Outcome candidato | Justificação | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M1 | `IN_SCOPE` | ∅ | `SPECIFIED` | `FULLY` | não | `ANSWER` | caso nominal: fundamento existe e é suficiente | `SUPPORTED` |
| M2 | `IN_SCOPE` | ∅ | `SPECIFIED` | `NOT` | — | `ABSTAIN` **ou** `ESCALATE` | depende de existir serviço competente (D6) | `NEEDS_INSTITUTION` |
| M3 | `IN_SCOPE` | ∅ | `SPECIFIED` | `PARTIALLY` | não | `ANSWER` com lacuna declarada | responder a parte suportada e declarar a não suportada | `NEEDS_SUPERVISOR` (O3) |
| M4 | `IN_SCOPE` | ∅ | `UNDERSPECIFIED` | — | — | `CLARIFY` **se** passar o teste de resolubilidade | a lacuna está no pedido e o utilizador pode preenchê-la | `NEEDS_SUPERVISOR` (O4) |
| M5 | `IN_SCOPE` | ∅ | `UNDERSPECIFIED` | `NOT` para toda a desambiguação plausível | — | `ABSTAIN` / `ESCALATE` | falha o teste de resolubilidade: clarificar não resolve | `PROVISIONAL` |
| M6 | `IN_SCOPE` | `PERSONAL_DATA_REQUIRED` | `SPECIFIED` | — | — | `ESCALATE` **ou** `ABSTAIN` | o sistema não deve aceder a dados individuais; o caso pode continuar com humano | `NEEDS_SUPERVISOR` (O2) |
| M7 | `IN_SCOPE` | ∅ (procedimento documentado) | `SPECIFIED` | `FULLY` | não | `ANSWER` | pergunta **sobre o procedimento** de aceder a dados pessoais — não exige o dado | `SUPPORTED` |
| M8 | `IN_SCOPE` | `ADMINISTRATIVE_ACTION_REQUIRED` | `SPECIFIED` | — | — | `ESCALATE` | pede execução; existe serviço competente; fora do mandato do sistema | `NEEDS_SUPERVISOR` (O6) |
| M9 | `OUT_OF_SCOPE` | — | — | — | — | `ABSTAIN` | fora do domínio configurado; não há serviço institucional a continuar o caso | `PROVISIONAL` |
| M10 | `IN_SCOPE` | ∅ | `SPECIFIED` | `FULLY` | **F1/F2** (vigência/versão) | `ANSWER` pela fonte vigente | conflito resolúvel por regra documental já formalizada | `PROVISIONAL` |
| M11 | `IN_SCOPE` | ∅ | `SPECIFIED` | `FULLY` | **F3** (autoridade) | `ABSTAIN` **ou** `ESCALATE` | sem hierarquia documental, escolher uma fonte seria arbitrário | `NEEDS_INSTITUTION` (O5) |
| M12 | `IN_SCOPE` | ∅ | `SPECIFIED` | `NOT` (fonte expirada era a única) | — | `ABSTAIN` com menção de desatualização | responder por fonte expirada induz em erro | `NEEDS_SUPERVISOR` |

**Linhas deliberadamente ausentes:** combinações em que `OUT_OF_SCOPE` se cruza
com answerability ou conflito. `INFERENCE` — se o tema está fora do âmbito, as
dimensões seguintes não são avaliadas; a precedência conceptual estabelecida pela
A2.0 torna-as irrelevantes. Registe-se, porém, que **a ordem de avaliação não
está definida** e não é fixada aqui.

**Contagem de estados**, sobre as 12 linhas: `SUPPORTED` 2 (M1, M7) ·
`PROVISIONAL` 3 (M5, M9, M10) · `NEEDS_SUPERVISOR` 5 (M3, M4, M6, M8, M12) ·
`NEEDS_INSTITUTION` 2 (M2, M11), a que acresce M8 parcialmente, por depender dos
destinos de escalação. **Nenhuma** linha é política final.

---

## 9. Casos de fronteira C1–C10

Cada caso indica **exatamente qual dimensão produz o resultado**.

**C1 — respondível.** «Qual é o prazo para matrícula?», documento atual e claro.
D1=`IN_SCOPE`, D2=∅, D3=`SPECIFIED`, D4=`FULLY`, D5=não → **`ANSWER`** (M1).
*Dimensão determinante:* D4. **Estado:** `SUPPORTED`.

**C2 — sem evidência.** Pergunta institucional sem documento que a suporte.
D1=`IN_SCOPE`, D4=`NOT` → **`ABSTAIN` ou `ESCALATE`** (M2).
*Dimensão determinante:* **D6**, não D4. `INFERENCE` — este é o ponto onde
`NOT_ANSWERABLE → ABSTAIN` falha como regra automática: se existe serviço
competente, terminar o fluxo desperdiça a única via útil para o utilizador.
`FACT` — hoje o sistema produz sempre `insufficient_evidence`, isto é, um
`ABSTAIN` implícito, e nunca a alternativa. **Estado:** `NEEDS_INSTITUTION`.

**C3 — parcialmente suportado.** Pedido com dois itens, um documentado.
D4=`PARTIALLY` → **`ANSWER` com lacuna declarada** (M3).
*Dimensão determinante:* D4 + a regra de O3. As quatro alternativas da secção 31
do enunciado avaliam-se assim (`INFERENCE`):

| Alternativa | Avaliação |
| --- | --- |
| **A** — responder à parte suportada e declarar a não suportada | **recomendada**; preserva utilidade e honestidade; alinhada com o princípio constitucional §3 |
| **B** — `CLARIFY` | só se a parte em falta for resolúvel pelo utilizador (secção 7.3.1); caso contrário é sobre-clarificação |
| **C** — `ABSTAIN` | justificável apenas quando a parte suportada, isolada, **induz em erro** — p. ex. dar o prazo sem dizer que há um requisito prévio |
| **D** — `ESCALATE` | quando a parte em falta exige intervenção humana |

`INFERENCE` — não existe regra global. A escolha depende de uma propriedade
adicional: **a parte suportada, isolada, é enganosa?** Isto é anotável e é a
questão a levar como O3. **Estado:** `NEEDS_SUPERVISOR`.

**C4 — ambíguo.** «Quando posso fazer isso?» sem antecedente.
D3=`UNDERSPECIFIED` → **`CLARIFY`** se resolúvel (M4).
*Dimensão determinante:* D3. `FACT` — hoje esta pergunta produziria
`insufficient_evidence` (sem correspondência lexical), o que é o desfecho errado
pela razão errada: o problema não é falta de documento, é falta de pedido.
**Estado:** `NEEDS_SUPERVISOR` (O4).

**C5 — dados pessoais.** «Qual é a minha nota?»
D1=`IN_SCOPE` (tema académico), D2=`PERSONAL_DATA_REQUIRED` → **`ESCALATE` ou
`ABSTAIN`** (M6).
*Dimensão determinante:* D2, com o desfecho decidido por D6.
`INFERENCE` — há uma terceira via que O2 deve considerar explicitamente:
responder com a **orientação procedimental** («as notas são consultadas em X»)
sem satisfazer o dado pessoal. Isto é um `ANSWER` fundamentado que não viola a
restrição, e é provavelmente o comportamento mais útil. **Estado:**
`NEEDS_SUPERVISOR`.

**C6 — procedimento sobre dados pessoais.** «Como consulto as minhas notas?»
D2=**∅** → **`ANSWER`** (M7).
*Dimensão determinante:* D2, pela ausência da restrição. `FACT` — o contrato já
documenta esta distinção. É o par C5/C6 que demonstra por que razão o
possessivo não é o discriminante. **Estado:** `SUPPORTED`.

**C7 — fora de âmbito.** Pedido sem relação com atendimento académico.
D1=`OUT_OF_SCOPE` → **`ABSTAIN`** (M9).
*Dimensão determinante:* D1, e nenhuma outra é avaliada. **Estado:**
`PROVISIONAL` — a fronteira concreta depende da Uni-CV.

**C8 — evidência contraditória.** Duas fontes aparentemente vigentes com
instruções incompatíveis.
D5=F3 → **`ABSTAIN` ou `ESCALATE`** (M11).
*Dimensão determinante:* D5. `FACT` — o artefacto não tem metadados de autoridade
para resolver F3. `INFERENCE` — escolher silenciosamente uma das fontes seria a
pior opção disponível: produz uma resposta confiante e potencialmente errada,
sem sinal de que houve conflito. **Estado:** `NEEDS_INSTITUTION`.

**C9 — fonte expirada.** Documento lexicalmente relevante mas fora de vigência.
D4=`NOT` (a evidência não é admissível) → **`ABSTAIN`** com menção de
desatualização (M12).
*Dimensão determinante:* D4, via critério de vigência. `FACT` — a admissibilidade
por vigência **já é aplicada** pelo `RetrievalEligibility`, pelo que a fonte
expirada tende a não chegar à decisão. `LITERATURE` [L3] — é precisamente a
classe de perguntas sensíveis ao tempo onde os modelos mais falham, o que
justifica tratá-la explicitamente e não confiar na geração. **Estado:**
`PROVISIONAL`.

**C10 — falha técnica.** Fornecedor indisponível.
→ **NÃO é um `DecisionOutcome`.** `FACT` — confirmado no código: produz
`AnswerGeneratorUnavailableError` (503) ou `AnswerGenerationError` (502), nunca um
`status` de resposta. `INFERENCE` — classificar isto como `ABSTAIN` contaminaria
a métrica de abstenção com taxa de avaria, tornando ambas ininterpretáveis: uma
subida da abstenção deixaria de distinguir «o sistema tornou-se mais prudente» de
«o fornecedor esteve em baixo». **Estado:** `SUPPORTED` — a exclusão é firme e já
está correta no código.

---

## 10. Guia de anotação candidato

`PROPOSAL` — desenhado, **não criado**. Nenhum ficheiro de corpus foi produzido.

### 10.1 Critério de qualidade

> Se dois avaliadores competentes, com estas definições à frente, não chegarem ao
> mesmo rótulo, a definição **não está suficientemente operacional** e a dimensão
> não está pronta para o *ground truth*.

### 10.2 Ordem de anotação proposta

`PROPOSAL` — a ordem reduz trabalho e evita contaminação entre dimensões:

```
1. D1 scope           → se OUT_OF_SCOPE, parar
2. D2 constraints     → conjunto, possivelmente vazio
3. D3 specificity     → inclui o teste de resolubilidade
4. D4 answerability   → só depois de fixada a evidência observada
5. D5 conflict        → só se houver ≥2 evidências admissíveis
6. expected_outcome   → derivado, com justificação escrita
```

`INFERENCE` — D4 exige que a evidência esteja **fixada**: anotar answerability
sobre um retrieval que pode mudar produziria rótulos não reprodutíveis. Isto
implica anotar contra um **snapshot** identificado do corpus e da execução de
recuperação.

`FACT` — **esse identificador não existe hoje.** `RetrievalResult` transporta
exatamente `evidence`, `trace` e `score_semantics`; e `score_semantics.version`
identifica a **configuração de scoring** — «a configuração que produziu os
valores», nas palavras do próprio contrato — e **não** a versão do corpus nem a
execução concreta da pesquisa. Dois retrievals sobre corpora diferentes podem
partilhar a mesma `version`.

`PROPOSAL` — o `snapshot_id` da secção 10.3 é, portanto, uma **lacuna a
preencher** antes de qualquer anotação de D4, e não uma capacidade existente a
reutilizar. Registado como pré-requisito do *ground truth* (secção 18).

### 10.3 Campos candidatos

`PROPOSAL` — **não fixar antes de O1–O7**:

| Campo | Tipo | Notas |
| --- | --- | --- |
| `question_id` | identificador | |
| `question_text` | texto | sintético ou anonimizado; **nunca** dados pessoais reais |
| `language` | código | |
| `scope` | D1 | |
| `constraints` | conjunto D2 | vazio é válido |
| `specificity` | D3 | dependente de O4 |
| `clarification_resolvable` | booleano | operacionaliza a secção 7.3.1 |
| `answerability` | D4 | relativo ao snapshot |
| `asked_items` | lista | decomposição que fundamenta D4 |
| `evidence_conflict` | D5 + família F1/F2/F3 | |
| `expected_outcome` | D7 | |
| `expected_evidence` | lista de ids | contra o snapshot |
| `human_handoff_expected` | booleano + destino | dependente de O6 |
| `partial_answer_misleading` | booleano | necessário para C3/O3 |
| `notes` | texto | obrigatório em fronteiras |
| `snapshot_id` | identificador | corpus + execução de recuperação; **não existe hoje** — ver 10.2 |

### 10.4 Validação inter-avaliador

`PROPOSAL` — método, sem inventar disponibilidade de pessoas:

1. **Definições escritas primeiro**, com exemplos e não-exemplos por dimensão
   (o material das secções 7 e 9 é o rascunho).
2. **Dois avaliadores independentes** sobre uma amostra do corpus. `FACT` — o
   número de avaliadores efetivamente disponíveis **não está determinado**; se
   apenas um estiver disponível, a alternativa honesta é dupla anotação diferida
   pelo mesmo avaliador, declarada como tal e reconhecida como limitação de
   validade.
3. **Concordância medida** com estatística apropriada a rótulos nominais
   (Cohen's κ por dimensão). Reportar por dimensão, não agregada: `INFERENCE` —
   espera-se κ alto em D1/D2 e baixo em D3/D5, e uma média esconderia exatamente
   a informação útil.
4. **Resolução de desacordos** por discussão, com a regra desambiguadora
   resultante **escrita de volta no guia** — o desacordo é sinal de definição
   incompleta, não de avaliador distraído.
5. **Registo dos casos de fronteira** como anexo do guia.

`LITERATURE` [L4] — que os LLMs falhem a identificar ambiguidade não implica que
humanos concordem facilmente; a medição de concordância é indispensável em D3.

---

## 11. Avaliação futura

`PROPOSAL` — desenho, **sem executar experiência**.

### 11.0 Princípio de separação

`INFERENCE` — três qualidades distintas, hoje frequentemente confundidas:

```
qualidade do retrieval   encontrou a evidência que existia?
qualidade da decisão     decidiu bem perante a evidência observada?
qualidade da resposta    a resposta gerada é boa, dado que decidiu ANSWER?
```

`LITERATURE` [L3] — a necessidade desta separação é empírica, não estética: com
as passagens relevantes **já anotadas e fornecidas**, o grounding factual não
passa de 60%. Ou seja, uma decisão `ANSWER` correta convive rotineiramente com
uma resposta má.

**Consequência metodológica** (`PROPOSAL`): a policy é avaliada **condicionada à
evidência observada**, sobre um snapshot fixo de retrieval. Erros de recuperação
são medidos separadamente e não são imputados à policy.

### 11.1 Over-answer

> O sistema respondeu substantivamente quando deveria ter clarificado, abstido ou
> escalado.

`INFERENCE` — é a métrica mais importante do projeto, porque é a que mede
diretamente o princípio constitucional §3 («nunca produzir uma resposta plausível
sem suporte»). Deve ser reportada **desagregada pelo desfecho correto**:
responder quando se devia clarificar não tem a mesma gravidade que responder
quando se devia abster.

### 11.2 Over-escalation

> O sistema escalou quando poderia ter respondido de forma fundamentada.

`LITERATURE` [L7], [L8] — a sobre-recusa é o efeito secundário sistemático de
critérios conservadores, e é medível. `INFERENCE` — uma policy que escala tudo
tem *over-answer* nulo e é inútil; reportar 11.1 sem 11.2 permitiria declarar
sucesso com um artefacto sem valor. As duas métricas **só têm significado como
par**.

### 11.3 Conjunto proposto

`PROPOSAL` — apenas métricas que respondem às questões secundárias:

| Métrica | Responde a | Justificação |
| --- | --- | --- |
| matriz de confusão 4×4 sobre `DecisionOutcome` | QS sobre decisão | `LITERATURE` [L1]: a AUCM é o instrumento equivalente |
| precisão/recall por desfecho | idem | agregados escondem o desequilíbrio de classes |
| *over-answer rate* (desagregada) | QS sobre respostas fundamentadas | secção 11.1 |
| *over-escalation* / *under-escalation* | QS sobre encaminhamento | secção 11.2; **compromisso formal da proposta** («adequação dos encaminhamentos») |
| *clarification appropriateness* | QS sobre ambiguidade | operacionalizada pelo teste de resolubilidade |
| concordância inter-avaliador por dimensão | validade do *ground truth* | precede todas as outras |

`PROPOSAL` — **excluir** nesta fase: accuracy agregada (enganadora com classes
desequilibradas) e macro-F1 como métrica principal (esconde a assimetria de custo
entre erros).

### 11.4 Ameaças à validade

| Ameaça | Mitigação proposta |
| --- | --- |
| corpus sintético não representa pedidos reais | recolher tipologia real na Uni-CV (secção 13) |
| o autor anota e desenha a policy | segundo avaliador; definições escritas antes de anotar |
| *ground truth* por juiz LLM | `LITERATURE` [L2]: concordância com humanos elevada mas imperfeita — não usar como fonte única |
| snapshot de retrieval envelhece | fixar e versionar corpus + execução; `FACT`: **essa identidade não existe hoje** (ver 10.2) — é pré-requisito, não capacidade disponível |
| rótulos anotados sobre turnos isolados vs. sistema conversacional | `FACT`: não há memória conversacional; declarar como limite de D3 |
| amostra pequena | declarar intervalos; não reportar percentagens sem denominador |
| `NOT_ANSWERABLE` sobre-representado num corpus pequeno | estratificar a amostra por desfecho esperado |

### 11.5 Corpus documental vs. *ground truth*

`INFERENCE` — respondendo à secção 96 do enunciado: são objetos diferentes com
dependências diferentes.

| | Depende da ontologia? | Pode começar já? |
| --- | --- | --- |
| **corpus documental** Uni-CV (regulamentos, calendários, editais) | **Não** | **Sim** — depende apenas de autorização institucional |
| **ground truth** da policy (perguntas rotuladas) | **Sim** | **Não** — rotular antes de O1–O7 produz rótulos a deitar fora; falta ainda a identidade de snapshot (10.2) |

---

## 12. Pacote para a orientadora — sete decisões

Formato decisório. Detalhe completo na versão curta que acompanha este relatório.

---

### O1 — Definição operacional de «agêntico»

**Formulação candidata em avaliação:**

> Neste trabalho, **agêntico** designa um sistema que seleciona entre ações
> distintas — responder, pedir esclarecimento, abster-se e encaminhar — com base
> no estado do pedido, da evidência disponível e das restrições aplicáveis,
> registando de forma auditável a decisão e o respetivo fundamento. Não designa
> autonomia para executar processos administrativos, aceder a dados académicos
> individuais nem operar sem supervisão.

**Avaliação:**

| Critério | Veredito |
| --- | --- |
| Suportada pela literatura? | **Sim.** `LITERATURE` [L10] enfatiza autonomia limitada e supervisão humana; [L9] usa o mesmo espaço de ações menos `ESCALATE`; [L1], [L3], [L6] sustentam que a seleção de ação tem de ser externa ao gerador |
| Coerente com a proposta formal? | **Sim.** A proposta compromete «reconhecer situações em que o pedido deve ser encaminhado» e medir «a adequação dos encaminhamentos» |
| Implementável no prazo? | **Sim**, na forma determinística, com `ESCALATE` ao nível E1 (7.6.1). A transferência técnica do caso (E2) **não é** implementável sem decisão institucional |
| Precisa de alteração? | **Uma**: fixar que `ESCALATE` é a **decisão** de dirigir o caso a uma pessoa, e não a existência de um mecanismo técnico de transferência |

`PROPOSAL` — **manter a ontologia de quatro ações como núcleo do contributo**, com
a ressalva acima. `INFERENCE` — não introduzir multi-agente, planeamento
autónomo, autonomia de ferramentas ou ciclos de auto-reflexão apenas para
justificar a palavra: nada disso está no artefacto e nada disso é exigido pela
proposta.

**Consequência de não decidir:** o Capítulo 2 não pode ser escrito, porque não se
sabe o que a revisão tem de cobrir.

---

### O2 — Dados pessoais

**Questão:** quando um pedido é academicamente `IN_SCOPE` mas exige dados
individuais, o sistema deve `ABSTAIN`, `ESCALATE`, ou fornecer orientação
procedimental sem satisfazer o dado?

**Porque importa:** é a classe de pedidos mais previsível num assistente
académico e a que toca proteção de dados.

| Alternativa | Consequência |
| --- | --- |
| **A** — `ABSTAIN` | seguro e inútil; o utilizador fica sem via |
| **B** — `ESCALATE` | útil; exige conhecer o destino institucional, mas **não** exige mecanismo técnico de transferência (nível E1, 7.6.1) |
| **C** — `ANSWER` com orientação procedimental, sem satisfazer o dado | útil e implementável hoje; não viola a restrição; **é o comportamento de C6** |

`PROPOSAL` — **C quando o pedido tem um item procedimental respondível; B quando
o que é pedido é o próprio dado individual**. `INFERENCE` — C e B não são
exclusivas nem intermutáveis: «como consulto as minhas notas?» é satisfeito por C;
«qual é a minha nota?» **não é satisfeito** por orientação procedimental, e cai em
B pelo critério de 7.6.1 — a necessidade de informação não fica satisfeita, o
caso é dirigido.

**Bloqueia A2.3?** **Sim.**

---

### O3 — Resposta parcial

**Questão:** pode o sistema responder à parte suportada de um pedido? Em que
condições?

| Alternativa | Consequência |
| --- | --- |
| **A** — sim, com lacuna declarada obrigatória | preserva utilidade; risco: parte isolada enganosa |
| **B** — não; `PARTIALLY` trata-se como `NOT` | conservador; perde utilidade em pedidos compostos, que são comuns |
| **C** — depende de a parte suportada ser enganosa isoladamente | mais correto; exige uma propriedade anotável adicional |

`PROPOSAL` — **C**, com **A** como comportamento por omissão. `INFERENCE` — a
propriedade «a parte suportada, isolada, induz em erro?» é anotável e é o único
critério que distingue as alternativas de forma não arbitrária. Recomenda-se
modelar como propriedade da resposta, **não** como quinto desfecho (secção 7.7).

**Bloqueia A2.3?** **Sim.**

---

### O4 — Ambiguidade e `CLARIFY`

**Questão:** formalizar `RequestSpecificity` como dimensão? Que situações
justificam `CLARIFY`?

| Alternativa | Consequência |
| --- | --- |
| **A** — dimensão própria + teste de resolubilidade | `LITERATURE` [L2], [L6], [L4], [L11]; maior potencial de contributo; anotação difícil |
| **B** — não formalizar; tratar ambiguidade dentro de answerability | mais simples; **contradiz** [L2], que lhes atribui respostas aceitáveis diferentes; e o contrato já recusou `AMBIGUOUS` em `AnswerabilityClass` |
| **C** — adiar `CLARIFY` para trabalho futuro | reduz âmbito; enfraquece o carácter agêntico, já que sobram três ações |

`PROPOSAL` — **A**, com o teste de resolubilidade da secção 7.3.1 como critério
escrito. `INFERENCE` — é onde a dissertação tem maior probabilidade de contributo
original, precisamente porque [L9] declara a fronteira `CLARIFY`/`ABSTAIN` em
aberto. Também é o maior risco de execução: exige concordância inter-avaliador
demonstrável e esbarra na ausência de memória conversacional.

**Bloqueia A2.3?** **Sim.**

---

### O5 — Evidência contraditória

**Questão:** perante fontes admissíveis incompatíveis — `ABSTAIN`, `ESCALATE`, ou
resolver por autoridade/vigência?

| Alternativa | Consequência |
| --- | --- |
| **A** — resolver por vigência/versão quando possível | `FACT`: metadados já existem; cobre F1 e F2 |
| **B** — `ABSTAIN`/`ESCALATE` quando irresolúvel (F3) | honesto; exige detetar conflito, o que não é trivial |
| **C** — construir hierarquia documental Uni-CV | mais completo; `NEEDS_INSTITUTION`; alarga âmbito |

`PROPOSAL` — **A + B**. **Não** empreender C nesta dissertação: exige
levantamento jurídico-institucional que não cabe no calendário e que a proposta
formal não compromete. `INFERENCE` — assumir que a deteção de conflito é
resolvida seria otimista; se a deteção não for fiável, a alternativa honesta é
declarar D5 como limitação e não como funcionalidade.

**Bloqueia A2.3?** **Parcialmente** — A é implementável; B depende de deteção.

---

### O6 — Escalação humana

**Questão:** que famílias de pedidos devem continuar com um operador? O que deve
ser entregue ao operador?

`FACT` — não existe qualquer mecanismo de escalação no artefacto.
`FACT` — a proposta formal compromete-se a avaliar «a adequação dos
encaminhamentos realizados».

As alternativas são sobre **até onde vai o handoff**, não sobre se `ESCALATE`
existe. Conforme 7.6.1, `ESCALATE` é a decisão; E1/E2 são níveis de maturidade da
sua execução.

| Alternativa | Consequência |
| --- | --- |
| **A** — `ESCALATE` ao nível **E1**: decisão de encaminhamento estruturada, com destino designado e contexto, apresentada ao utilizador | implementável após conhecer os destinos; cumpre «reconhecer situações»; avaliável pela «adequação dos encaminhamentos»; **não** cria caso técnico |
| **B** — `ESCALATE` ao nível **E2**: transferência de caso com registo e receção por operador | mais completo; exige canal, SLA, RGPD e integração |
| **C** — E2 com integração real nos sistemas da Uni-CV | fora de alcance no calendário |

`PROPOSAL` — **A (E1) como âmbito da dissertação, B (E2) como trabalho futuro
declarado.** `INFERENCE` — A satisfaz literalmente o compromisso da proposta
formal («reconhecer situações em que o pedido deve ser encaminhado») e é
avaliável sem integração institucional, porque a decisão fica registada e
comparável com o rótulo esperado. B sem destinatários reais produziria uma
funcionalidade não testável.

`INFERENCE` — consequência para a avaliação: com A, `ESCALATE` **é um desfecho
real e medível**, e as métricas de *over-* e *under-escalation* (secção 11.2)
mantêm objeto. É esta a razão pela qual A não deve ser lida como «deixar a
escalação fora do âmbito».

**`NEEDS_INSTITUTION`:** mesmo escolhendo A, é preciso saber **que serviços
existem e o que tratam** — sem isso não há destino a designar, e a decisão de
encaminhamento não é verificável.

**Bloqueia A2.3?** **Sim.**

---

### O7 — Formulação canónica da investigação

**Questão:** que título, RQ, OE e QS passam a ser canónicos?

| Elemento | Proposta formal | v1 | Estrutura | Formulação recomendada | Precisa orientadora? |
| --- | --- | --- | --- | --- | --- |
| **Título** | Conceção e Avaliação de um Assistente Virtual Inteligente para Apoio ao Atendimento Académico em IES | (sem título próprio) | Agentic RAG, parametrizável e multilingue | **manter o formal** | Não (já aprovado) |
| **Problema** | informação dispersa; tipos de pedido distintos | + validação documental e confiança | + multilinguismo | formal + tipologia de pedidos | Sim |
| **RQ** | implícita nos objetivos | agêntico + RAG + validação + escalação | Agentic RAG + multilingue | **candidata abaixo** | **Sim** |
| **QS** | ausentes | QS1–QS5 | 4 subquestões | derivar das dimensões D1–D6 | **Sim** |
| **Objetivo geral** | desenvolver assistente para apoio ao atendimento | + RAG + confiança + escalação | + Agentic RAG multilingue | **manter o formal** | Não |
| **OE** | 4 | 6 | ~8 | manter os 4 formais; usar os do v1 como decomposição | **Sim** |
| **Âmbito** | IES, Uni-CV como caso | + fora: notas, pagamentos, inscrições, execução | não substituir serviços | **explicitar exclusões do v1** | Sim |
| **Agêntico** | não usa o termo | orquestrador de fluxo controlado | «não é agente autónomo complexo» | **definição O1** | **Sim** |
| **Human handoff** | «reconhecer situações [...] encaminhar» + métrica | QS3 | requisito funcional | **eixo central** | Sim |
| **RAG** | **ausente**; tecnologia em aberto | fixado em OE2 | fixado na RQ | **manter em aberto até OE1** | **Sim** |
| **Confidence** | ausente | multifatorial obrigatório | ausente na RQ | **não implementar** (secção 14) | Sim |
| **Segundo LLM** | ausente | obrigatório (OE2) | ausente | **hipótese, não requisito** | Sim |
| **Multilinguismo** | ausente | configurável | **eixo da RQ** + capítulo | **infraestrutura, não eixo** | Sim |

**RQ candidata** (a validar, **não** canónica):

> Como conceber e avaliar um assistente agêntico de apoio ao atendimento
> académico em instituições de ensino superior, capaz de produzir respostas
> fundamentadas e rastreáveis a partir da documentação institucional e de
> encaminhar para intervenção humana os pedidos que não deve responder
> automaticamente?

**Avaliação da RQ candidata:**

| Critério | Veredito |
| --- | --- |
| vs. proposta formal | **compatível** — reformula os OE aprovados sem acrescentar tecnologia |
| vs. artefacto atual | **compatível** — respostas fundamentadas e rastreáveis existem; encaminhamento não, e é o *gap* que a dissertação preenche |
| vs. DSR | **adequada** — pergunta de conceção e avaliação de artefacto |
| vs. literatura | **sustentada** — [L2], [L3], [L6], [L9] estabelecem a relevância e a dificuldade |
| vs. tempo disponível | **exequível**, se `ESCALATE` ficar na forma A de O6 |
| neutralidade tecnológica | **preserva-a** — não nomeia RAG, embeddings nem confidence |

`INFERENCE` — a RQ candidata é **superior** à do v1 e à da Estrutura por uma razão
metodológica: não pressupõe a solução. As outras duas incorporam a resposta
tecnológica na pergunta, o que torna a revisão da literatura (OE1) decorativa —
não pode concluir nada que contrarie o que a pergunta já assume.

#### Divergência de calendário — a assinalar

`FACT` — o calendário da proposta formal:

| Tarefa | Calendarização |
| --- | --- |
| 3 — experimentação com utilizadores finais | **agosto de 2026** |
| 4 — revisão da literatura e análise de abordagens | setembro a novembro de 2026 |
| 5 — avaliação com métricas (Uni-CV) | dezembro de 2026 |

`INFERENCE` — há uma tensão real de sequenciação. A experimentação com
utilizadores está calendarizada **antes** da revisão da literatura, e a A2.2
mostra que a ontologia de decisão — necessária para interpretar o que a
experimentação observa — depende dessa revisão. Experimentar antes de fixar as
categorias de análise produz dados difíceis de interpretar *a posteriori*.

`PROPOSAL` — matéria a levar à orientadora junto com O7: ou a experimentação de
agosto é assumida como **exploratória** e não avaliativa (o que é legítimo e
frequente em DSR), ou a revisão dirigida a decisões é antecipada. Esta A2.2 é,
de facto, uma antecipação parcial da tarefa 4.

**Bloqueia A2.3?** **Sim** — O7 determina o que A2.3 está a implementar.

---

## 13. Dependências institucionais (Uni-CV)

`FACT` — nenhum destes dados existe no repositório, e não podem ser inventados.

| Dado necessário | Decisão que desbloqueia |
| --- | --- |
| tipologia real de pedidos recebidos | D1 (fronteira do âmbito), amostragem do corpus |
| que pedidos exigem obrigatoriamente operador | O2, O6, D6 |
| que pedidos são respondíveis documentalmente | calibração de *over-escalation* |
| destinos de encaminhamento (serviços, competências) | O6, `human_handoff_expected` |
| hierarquia e autoria de documentos institucionais | O5 / F3 |
| convenções de vigência (editais, calendários) | D4, C9 |
| casos frequentes de ambiguidade real | D3, O4 |

### 13.1 Autorização institucional

`FACT` — a pesquisa por termos de autorização, consentimento, ética, RGPD/GDPR na
documentação do repositório devolve apenas referências a **autorização técnica**
(autenticação, `institution_id`, JWT) e à regra constitucional de que documentos
reais e dados pessoais **nunca** entram em testes ou artefactos versionados.

**Não existe registo documentado** de autorização institucional para: usar
documentos reais da Uni-CV; recolher tipologia de pedidos; envolver estudantes;
envolver operadores.

`INFERENCE` — isto **não bloqueia** a A2.2 conceptual, que não usa dados reais.
**Bloqueia** a recolha de corpus real, a experimentação com utilizadores
(calendarizada para agosto de 2026) e a validação com operadores. Fica registado
como **dependência externa** com estado desconhecido, a esclarecer com a
orientadora.

---

## 14. Hipóteses arquiteturais não adotadas

### 14.1 Confidence score multifatorial

`FACT` — o v1 propõe «mecanismo de confiança calibrável» combinando relevância
semântica, cobertura documental, qualidade e frescura das fontes e resultado da
validação por LLM.

**Não implementado nesta fase.** Comparação crítica:

| | Score de confiança | Policy sobre sinais explícitos |
| --- | --- | --- |
| Auditabilidade | um número não explica a decisão | cada dimensão é inspecionável |
| Calibração | exige plano e dados de calibração | não aplicável |
| Anotação | requer rótulos graduados | rótulos nominais |
| Falha | silenciosa; um limiar mal escolhido é invisível | localizada numa dimensão |
| Composição | pesos arbitrários sem dados | regras justificadas individualmente |

`INFERENCE` — a incomparabilidade do score atual (secção 2.4) torna qualquer
agregação multifatorial construída sobre ele cientificamente indefensável hoje.
`PROPOSAL` — se vier a ser proposto no futuro, **exigir plano de calibração
explícito**: dados, método, métrica de calibração e demonstração de que o número
significa o que afirma significar.

### 14.2 Segundo LLM validador

`FACT` — o v1 torna-o obrigatório (OE2: «validação obrigatória por modelo de
linguagem»).

**Não implementado.** Classificado como **hipótese arquitetural** dependente de:
literatura, ganho medido, custo, latência e variabilidade.

`LITERATURE` — a evidência disponível é desfavorável a tratá-lo como garantia:
[L6] mostra que modelos de raciocínio **pioram** a abstenção em 24%; [L3] mostra
deflexão correta em ≤31%; [L2] mostra que mesmo um juiz LLM cuidadosamente
construído e validado **não atinge concordância perfeita** com anotadores
humanos. `INFERENCE` — usar um LLM para validar a decisão de outro LLM herda
as fraquezas de ambos e adiciona latência, custo e não-determinismo, contra uma
validação estrutural determinística que já existe e é reprodutível.

### 14.3 Retrieval lexical vs. denso vs. híbrido

`FACT` — a proposta formal deixou a tecnologia em aberto.

**Nada decidido nesta fase**, conforme a secção 67 do enunciado. `PROPOSAL` — o
desenho experimental futuro necessário:

```
corpus institucional real e fixo
+ conjunto de perguntas com relevância anotada
+ mesma política de admissibilidade em todos os braços
+ métricas de recuperação (recall@k, MRR) separadas das de decisão
+ o mesmo snapshot alimenta a policy em todos os braços
```

`INFERENCE` — a condição «mesma política de admissibilidade» é essencial: sem ela,
compara-se admissibilidade e não recuperação. `FACT` — o artefacto já a satisfaz,
porque `RetrievalEligibility` é independente da estratégia.

### 14.4 Limitações de retrieval observadas — não corrigidas

`FACT`, registado como **FOLLOW-UP**, conforme a secção 68 do enunciado:

- as quatro causas de zero evidências (secção 2.6) colapsam num único estado
  público;
- o trace neutro não distingue «nenhum candidato admissível existia» de «existiam
  candidatos e nenhum sobreviveu à correspondência lexical» — a distinção existe
  no `LexicalRetrievalTrace` mas não no contrato neutro;
- não há memória conversacional, o que limita D3 (secção 7.3).

**Nenhuma destas foi corrigida.**

---

## 15. Correções documentais aplicadas

Âmbito restrito a factos observavelmente falsos, conforme a secção 77 do
enunciado. **Nenhum princípio de investigação foi reescrito.**

| # | Ficheiro | Afirmação falsa | Correção |
| --- | --- | --- | --- |
| **D1** | `docs/ai/02-current-state.md` | A6.1 numa branch, «ainda não está integrada na `main`» | atualizado para o snapshot `6ae9bad`, com o PR #45 identificado como integrado |
| **D2** | `docs/ai/01-project-constitution.md` §5 | «o SDK […] é uma dependência de runtime da aplicação, importada quando a aplicação é carregada» | substituída por formulação **duradoura** (princípio + remissão), sem nova descrição temporal |
| **D3** | `docs/ai/01-project-constitution.md` §4 | a distinção «recuperável agora» / «legitimamente citado então» está «atualmente em discussão na issue #24» | removida a afirmação temporal obsoleta; preservado o princípio de auditabilidade |

`INFERENCE` — sobre D2, a instrução da secção 75 do enunciado foi seguida
literalmente: **não** se substituiu uma descrição temporal antiga por outra que
voltará a envelhecer. A Constituição passa a enunciar o princípio (o acoplamento
ao fornecedor deve manter-se localizado e o carregamento não deve ser imposto a
quem não o usa) e remete o estado corrente para `02-current-state.md`.

---

## 16. Enquadramento DSR

`INFERENCE` — a A2.2 contribui para:

| Fase DSR (Peffers et al., 2007) | Contribuição da A2.2 |
| --- | --- |
| DSR1 — identificação do problema | consolida a tipologia de pedidos da proposta formal |
| **DSR2 — objetivos da solução** | **contribuição principal** — define o que significa decidir corretamente, em termos observáveis e avaliáveis |
| **DSR3 — conceção e desenvolvimento** | **contribuição parcial** — dimensões, matriz candidata e requisitos de auditabilidade; **sem** implementação |
| DSR4 — demonstração | não contribui |
| DSR5 — avaliação | **não é esta fase**; prepara o desenho (secção 11) |
| DSR6 — comunicação | prepara os capítulos 1, 3 e 4 |

`INFERENCE` — a A2.2 **não é DSR5**. Não avalia o artefacto; define os critérios
pelos quais ele virá a ser avaliado. Confundir as duas coisas seria apresentar
uma especificação como se fosse evidência empírica.

### 16.1 Mapa OE ↔ QS ↔ evidência

`PROPOSAL` — sobre os **quatro OE aprovados** na proposta formal. Sem
percentagens arbitrárias.

| OE (formal) | QS candidata | Artefacto/evidência necessária | Estado atual | Gap |
| --- | --- | --- | --- | --- |
| OE1 — revisão da literatura | QS1: que critérios sustentam cada ação? | revisão sistemática | **PARTIAL** — secção 6 é dirigida a decisões, não sistemática; calendário formal aponta set–nov 2026 | revisão sistemática por realizar |
| OE2 — requisitos | QS2: que propriedades observáveis justificam cada desfecho? | dimensões + guia de anotação | **PARTIAL** — dimensões definidas; O1–O7 abertas | validação da orientadora + Uni-CV |
| OE3 — protótipo funcional | QS3: como produzir respostas fundamentadas e rastreáveis? | pipeline documental + answering + citações | **SATISFIED** para respostas fundamentadas; **NOT STARTED** para a camada de decisão | `DecisionPolicy` |
| OE4 — demonstrar e validar com a Uni-CV | QS4: o encaminhamento é adequado? QS5: o artefacto é útil? | corpus real, ground truth, participantes | **BLOCKED** | autorização institucional (13.1) + ontologia estável |

`FACT` — as justificações de estado: OE3 está `SATISFIED` na parte de respostas
fundamentadas porque existe pipeline completo com validação estrutural,
persistência de citações e baseline reprodutível; está `NOT STARTED` na camada de
decisão porque os contratos não têm consumidores. OE4 está `BLOCKED` por
dependência externa, não por trabalho técnico em falta.

---

## 17. Impacto na dissertação

`PROPOSAL` — o que cada decisão altera, por capítulo:

| Capítulo | Impacto |
| --- | --- |
| **1 — Introdução** | O7 fixa título, problema, RQ, QS, OE e âmbito. O1 fixa a definição de «agêntico» em 1.5. A tipologia de pedidos da proposta formal entra em 1.2 |
| **2 — Fundamentação** | O1 determina a cobertura. Deve incluir *abstention*/*answerability*/*unanswerability* (hoje ausentes da Estrutura) e *over-refusal* como evidência contrária. Multilinguismo (2.4) deve ser rebaixado a subsecção. RAG (2.3) deve ser apresentado como **abordagem avaliada**, não como arquitetura assumida |
| **3 — Metodologia** | A2.2 mapeia-se em DSR2/DSR3. A secção 11 alimenta 3.6 (estratégia de avaliação). 3.7 (ética) depende de 13.1 |
| **4 — Conceção** | secções 7 e 8 são o material de 4.7. 4.6 não deve prometer entidade «escalonamentos» antes de O6. 4.8 (internacionalização) deve ser reduzida |
| **5 — Implementação** | 5.5 («lógica agentic») só pode ser escrita depois de A2.3. 5.3/5.4 devem descrever **retrieval lexical**, não embeddings, enquanto for esse o estado |
| **6 — Avaliação** | secção 11 é o desenho de 6.1–6.3. As métricas *over-answer* e *over-escalation* são novas face à Estrutura. 6.7 herda 11.4 |
| **7 — Conclusões** | o contributo declarável depende de O1 e O4: se a ontologia de decisão for o núcleo, é ela o contributo, não «um chatbot RAG» |

`INFERENCE` — partes já escrevíveis **sem risco**, porque não dependem de O1–O7:
metodologia DSR (3.1–3.3), processo de desenvolvimento já realizado, arquitetura
existente, política de elegibilidade documental (issue #24), proveniência e
auditabilidade das citações, e neutralidade de fornecedor (A6.0/A6.1). **Nenhum
capítulo foi escrito nesta tarefa.**

---

## 18. Impacto no código futuro

`PROPOSAL` — sem escrever código, e sem autorizar nada.

**Contratos que podem precisar de estabilização:**

- `RequestConstraint` — possível `ADMINISTRATIVE_ACTION_REQUIRED` (O6);
- `RequestSpecificity` — dimensão nova (O4);
- `DecisionReason` — estrutura referenciando dimensões, não enumeração (7.8);
- `DecisionOutcome` — **sem alteração prevista**; a resposta parcial modela-se
  como propriedade (O3), e `ESCALATE` cobre E1 e E2 sem valores novos (7.6.1);
- **identidade do snapshot de recuperação** — `FACT`: `RetrievalResult` não a
  transporta, e `score_semantics.version` identifica scoring, não corpus nem
  execução. É **pré-requisito do *ground truth*** (10.2) e do registo de
  auditoria abaixo, e não decorre de nenhuma das decisões O1–O7 — pode por isso
  ser tratada independentemente delas.

**Consumidores futuros:** um avaliador de decisão entre o retrieval e o
answering. `INFERENCE` — a posição correta é **entre** as duas etapas: precisa do
`RetrievalResult` e precede a geração. O `answering_service` atual já tem o ponto
de inserção natural — a verificação de evidência vazia — mas transformá-lo em
policy é A2.3, não A2.2.

**Persistência futura** — resposta à secção 53 do enunciado. O mínimo necessário
para explicar, mais tarde, por que razão o assistente respondeu, clarificou, se
absteve ou escalou:

```
identificação do pedido        (já existe: Message)
valores observados por dimensão (D1..D5)
DecisionOutcome
referência à evidência observada (ids + snapshot)
policy version
reference_date
```

`INFERENCE` — a `policy version` é indispensável e é o análogo de
`score_semantics.version`: sem ela, uma decisão registada não é interpretável
depois de as regras mudarem. **Nenhuma migration foi criada.** `FACT` — a
restrição constitucional §2 mantém-se: isto é **persistência**, não *logging*; os
logs continuam sem conteúdo documental nem perguntas.

**API futura:** um `status` novo, ou um campo de decisão na resposta, é uma
alteração de contrato público — exige decisão própria e não é consequência
automática de A2.3.

**Testes futuros:** casos C1–C10 como testes de caracterização da policy; testes
de contrato para as dimensões novas, no padrão do `test_decision_contracts.py`.

---

## 19. Próximo passo

`PROPOSAL` — **uma** recomendação principal, entre as quatro da secção 94 do
enunciado:

> ### A — Validar a A2.2 com a orientadora antes de qualquer implementação

**Justificação.** O critério para **D** (iniciar A2.3) é que todas as decisões
normativas necessárias estejam validadas. O1–O7 estão abertas, e três delas
(O2, O3, O6) determinam comportamento observável perante utilizadores reais.
A implementação é tecnicamente simples — precisamente por isso a tentação de
avançar é maior, e por isso a regra da secção 95 do enunciado se aplica.

**B** (recolher evidência institucional em paralelo) é **compatível e
recomendado como ação concorrente**, com uma precedência: a autorização
institucional (13.1) tem estado desconhecido e é ela que condiciona tudo o resto.

**C** (iniciar corpus real) — apenas na parte **documental**. O *ground truth* da
policy depende da ontologia estar aprovada (11.5).

**D** — **bloqueado**.

---

## 20. Critério de conclusão

Resposta às catorze perguntas da secção 109 do enunciado.

| # | Pergunta | Resposta | Onde |
| --- | --- | --- | --- |
| 1 | O que significa `IN_SCOPE`? | o **tema** pertence ao domínio institucional configurado; independente da capacidade técnica | 7.1 |
| 2 | O que é uma constraint? | propriedade do **pedido** que impede a satisfação por documentação geral; conjunto, possivelmente vazio | 7.2 |
| 3 | Quando um pedido é ambíguo? | quando não determina o que o utilizador quer saber **e** existe resposta do utilizador que o resolveria | 7.3, 7.3.1 |
| 4 | Quando é fully/partially/not answerable? | por decomposição em itens pedidos: todos / alguns / nenhum suportados por evidência admissível, vigente e suficiente | 7.4 |
| 5 | Como tratar evidência contraditória? | F1/F2 por regra documental; F3 sem hierarquia → `ABSTAIN`/`ESCALATE` | 7.5, O5 |
| 6 | Quando `CLARIFY` é apropriado? | quando passa o teste de resolubilidade — nunca por falha de retrieval | 7.3.1 |
| 7 | Quando `ABSTAIN` é apropriado? | quando não há resposta fundamentada **e** não há serviço humano que faça avançar o caso | 7.6 |
| 8 | Quando `ESCALATE` é apropriado? | quando o pedido não é satisfazível automaticamente **e** existe serviço competente para continuar o caso; é a decisão, não o mecanismo (E1/E2) | 7.6, 7.6.1 |
| 9 | Que decisões dependem da literatura? | separação D3/D4; decisão externa ao gerador; medição bidirecional do erro | 6, O4 |
| 10 | Que decisões dependem da Uni-CV? | fronteira do âmbito; destinos de escalação; hierarquia documental; tipologia real | 13 |
| 11 | Que decisões precisam da orientadora? | O1–O7 | 12 |
| 12 | Que ontologia no futuro ground truth? | D1, D2, D3, D4, D5 + `expected_outcome` + resolubilidade + lacuna enganosa | 10.3 |
| 13 | Como responde às QS/OE? | mapa OE↔QS↔evidência | 16.1 |
| 14 | O que impede implementar `DecisionPolicy`? | O1–O7 abertas; sem ontologia validada, o código fixaria respostas não dadas | 1, 19 |

---

## 21. Referências

Verificadas na fonte em 2026-08-13. Preprints identificados como tal.

1. **Madhusudhan, N., Madhusudhan, S. T., Yadav, V., & Hashemi, M.** (2025). *Do
   LLMs Know When to NOT Answer? Investigating Abstention Abilities of Large
   Language Models.* In *Proceedings of the 31st International Conference on
   Computational Linguistics (COLING 2025)*, pp. 9329–9345. Abu Dhabi, UAE. ACL
   Anthology: `2025.coling-main.627`.
2. **Peng, X., Choubey, P. K., Xiong, C., & Wu, C.-S.** (2025). *Unanswerability
   Evaluation for Retrieval Augmented Generation.* In *Proceedings of the 63rd
   Annual Meeting of the ACL (Volume 1: Long Papers)*, pp. 8452–8472. DOI:
   `10.18653/v1/2025.acl-long.415`.
3. **Sorodoc, I. T., Ribeiro, L. F. R., Blloshmi, R., Davis, C., & de Gispert,
   A.** (2025). *GaRAGe: A Benchmark with Grounding Annotations for RAG
   Evaluation.* In *Findings of the ACL: ACL 2025*, pp. 17030–17049. DOI:
   `10.18653/v1/2025.findings-acl.875`.
4. **Zhang, T., Qin, P., Deng, Y., Huang, C., Lei, W., Liu, J., Jin, D., Liang,
   H., & Chua, T.-S.** (2024). *CLAMBER: A Benchmark of Identifying and
   Clarifying Ambiguous Information Needs in Large Language Models.* In
   *Proceedings of the 62nd Annual Meeting of the ACL (Volume 1: Long Papers)*.
   Bangkok, Thailand. ACL Anthology: `2024.acl-long.578`.
5. **Xu, R., Qi, Z., Guo, Z., Wang, C., Wang, H., Zhang, Y., & Xu, W.** (2024).
   *Knowledge Conflicts for LLMs: A Survey.* In *Proceedings of EMNLP 2024*. ACL
   Anthology: `2024.emnlp-main.486`.
6. **Kirichenko, P., Ibrahim, M., Chaudhuri, K., & Bell, S. J.** (2025).
   *AbstentionBench: Reasoning LLMs Fail on Unanswerable Questions.* NeurIPS
   2025. arXiv:2506.09038.
7. **Cui, J., Chiang, W.-L., Stoica, I., & Hsieh, C.-J.** (2025). *OR-Bench: An
   Over-Refusal Benchmark for Large Language Models.* In *Proceedings of the 42nd
   International Conference on Machine Learning (ICML)*, PMLR vol. 267,
   pp. 11515–11542.
8. **Röttger, P., Kirk, H., Vidgen, B., Attanasio, G., Bianchi, F., & Hovy, D.**
   (2024). *XSTest: A Test Suite for Identifying Exaggerated Safety Behaviours in
   Large Language Models.* In *Proceedings of NAACL-HLT 2024 (Volume 1: Long
   Papers)*, pp. 5377–5400. Mexico City, Mexico. ACL Anthology:
   `2024.naacl-long.301`.
9. **Kostopoulos, G., Gkamas, V., Rigou, M., & Kotsiantis, S.** (2025). *Agentic
   AI in Education: State of the Art and Future Directions.* *IEEE Access*,
   vol. 13, pp. 177467–177491.
10. **Baan, J., Aziz, W., Plank, B., & Fernández, R.** (2026). *Clarify, Abstain
    or Answer? Strategising in Conversation with Belief-Augmented Generation.*
    arXiv:2605.25831. **[PREPRINT]**
11. **Lee, D., Kim, S., et al.** (2023). *Asking Clarification Questions to
    Handle Ambiguity in Open-Domain QA.* In *Findings of the ACL: EMNLP 2023*.
    ACL Anthology: `2023.findings-emnlp.772`.
12. **Hevner, A. R., March, S. T., Park, J., & Ram, S.** (2004). *Design Science
    in Information Systems Research.* *MIS Quarterly*, 28(1), 75–105.
13. **Peffers, K., Tuunanen, T., Rothenberger, M. A., & Chatterjee, S.** (2007).
    *A Design Science Research Methodology for Information Systems Research.*
    *Journal of Management Information Systems*, 24(3), 45–77.

**Citados no documento v1 e verificados como preprints** (a identificar como tal
na dissertação): Sharma, C. (2025), *Retrieval-Augmented Generation: A
Comprehensive Survey of Architectures, Enhancements, and Robustness Frontiers*,
arXiv:2506.00054; Gan, A., Yu, H., Zhang, K., et al. (2025), *Retrieval Augmented
Generation Evaluation in the Era of Large Language Models: A Comprehensive
Survey*, arXiv:2504.14891.

---

## 22. Fontes desta análise

**GitHub:** `FredericoXX/Projeto-Final`, `main` em `6ae9bad`; PRs #41–#45; issue
#24. Código e testes lidos diretamente.

**Documentos de investigação**, lidos em modo apenas-leitura a partir do sistema
de ficheiros do autor (fora do repositório; nenhum foi copiado nem modificado):
`Proposta Dissertação Carlos Frederico 2.docx`,
`Assistente Virtual UniCV v1.docx`, `Estrutura da Dissertação.docx`, e
`Plano de atividades - Dissertação.docx` (aberto, identificado como o trabalho de
licenciatura de 2020 e **formalmente excluído** — secção 3.1).

**Literatura científica:** secção 21.

**Não consultado:** os documentos `reformulacao-documentos-investigacao.md` e
`auditoria-projeto-final.md` referidos no enunciado **não foram encontrados** no
repositório nem no sistema de ficheiros. As afirmações que deles dependeriam
foram derivadas diretamente dos `.docx` e do código.
