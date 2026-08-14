# Respostas Fundamentadas e Integração Conversacional (Fase 3, Etapas 2–3)

## Natureza experimental

Esta etapa adiciona geração de respostas aumentada por evidências sobre a
baseline lexical existente. **Não é uma decisão arquitetural definitiva**:
a abordagem final depende da revisão da literatura e da avaliação
experimental. O sistema **não** deve ser apresentado como livre de
alucinações — a validação desta etapa é determinística e estrutural, não
semântica.

Continuam a **não** existir: embeddings, pesquisa semântica, pesquisa
híbrida, reranking por modelo, validação por segundo LLM, confidence score
final, memória/histórico no prompt, idempotência, persistência de prompts ou
respostas brutas do fornecedor e feedback. O
reranking que existe é lexical e determinístico, na etapa de retrieval (ver
[`docs/database.md`](database.md)).

Existe desde a A2.3a um **encaminhamento humano E1 solicitado pelo
utilizador**, descrito em [Encaminhamento humano (E1)](#encaminhamento-humano-e1).
É uma capacidade separada deste pipeline: não usa retrieval nem LLM, e não
altera o contrato de `/ask`.

## Fluxo

```
pergunta autenticada
→ resolução de instituição e idioma (regras existentes)
→ normalização da pergunta (text_normalization)
→ recuperação de evidências (contrato Retriever já existente)
→ política de evidência (zero evidências → fallback, sem gerador)
→ construção de contexto limitado (answering/context.py)
→ geração controlada (contrato AnswerGenerator)
→ validação determinística (answering/validation.py)
→ resposta com fontes citadas
```

A recuperação de evidências beneficia automaticamente do retrieval lexical
do `PostgresLexicalRetriever` através do contrato `Retriever` inalterado.
Esse retriever agrega as variantes da consulta (exact, reduced_and,
canonical_relaxed_and, reduced_or) dentro de um orçamento global por quotas,
decide **elegibilidade** antes de pontuar e só depois aplica o ranking
lexical determinístico (ver a secção de retrieval em
[`docs/database.md`](database.md)). O answering usa apenas a **ordem** do
ranking e o conteúdo das evidências, não o valor do `score`, pelo que a
semântica do score composto não altera a seleção de contexto nem a política
de evidência.

A **suficiência da evidência é decidida no retriever**, não no answering: o
answering não faz uma segunda avaliação, não altera prompts e não conhece a
política de cobertura. Quando o retrieval devolve zero evidências — porque
não houve correspondência, porque a cobertura foi insuficiente (ex.: um
único candidato que cobre 1 de 3 termos) ou porque todos os candidatos
ficaram abaixo do limiar —, o answering devolve `insufficient_evidence`, com
`sources` vazias, **sem chamar o gerador** e sem persistir qualquer
`message_source`. Nenhuma resposta fundamentada é produzida sobre uma
coincidência fraca.

Isto não elimina a limitação lexical de fundo: perguntas cujo vocabulário
não partilha termos suficientes com os documentos continuam em
`insufficient_evidence`.

## Endpoint independente

`POST /api/v1/answering/ask` — autenticado; qualquer utilizador ativo de
uma instituição ativa pode perguntar. O endpoint de retrieval
(`POST /api/v1/retrieval/search`) mantém-se inalterado.

Pedido: `query` (1–1000 caracteres), `language` (opcional, validado
contra os idiomas da instituição), `top_k` (opcional; default
`ANSWERING_DEFAULT_TOP_K`, máximo `ANSWERING_MAX_TOP_K`),
`official_only` (default `true`). `institution_id`/`user_id` no payload
são rejeitados com 422.

Respostas HTTP:

- `200` com `status: "answered"` — resposta gerada e validada, com
  `sources` (apenas as evidências citadas, pela ordem das citações);
- `200` com `status: "insufficient_evidence"` — sem evidências; mensagem
  de fallback determinística, `sources: []`, gerador nunca contactado;
- `422` — payload inválido, idioma não suportado, `top_k` acima do
  máximo, pergunta que normaliza para vazio;
- `503` (`service_unavailable`) — provider não configurado (sem
  `OPENAI_API_KEY`/`OPENAI_MODEL`) quando a geração é necessária;
- `502` (`upstream_error`) — falha operacional do provider ou resposta
  gerada que falhou a validação.

## Endpoint conversacional

`POST /api/v1/conversations/{conversation_id}/ask` reutiliza exatamente o
mesmo pipeline e aceita o mesmo `AnsweringRequest`, mas devolve `201` e
persiste um turno completo. Utilizadores comuns só podem perguntar nas suas
conversas; admins podem usar qualquer conversa da própria instituição. Uma
conversa inexistente, de outro tenant ou inacessível responde 404; `closed`
e `archived` respondem 409. Campos como `institution_id`, `user_id`, `role`,
`reply_to_message_id`, `sources` e `status` não pertencem ao payload e são
rejeitados com 422.

O resultado contém `status`, `conversation_id`, `user_message` e
`assistant_message`. A mensagem assistant aponta para a user através de
`reply_to_message_id`; apenas a assistant pode ter `sources`, ordenadas por
`citation_index`. Em `insufficient_evidence` também são persistidas as duas
mensagens (incluindo o fallback pt/en), mas nenhuma `MessageSource` é criada
e o gerador não é chamado.

O idioma explícito do pedido prevalece. Quando omitido, o endpoint
conversacional usa `conversation.language` e, se este for nulo, o idioma
default da instituição. O endpoint independente continua a usar diretamente
o default da instituição.

### Título automático e atividade recente

No **primeiro turno persistido** de uma conversa ainda sem título, o
backend gera o título a partir da pergunta original —
`app/core/conversation_title.py`, função pura, **local e sem qualquer
LLM**: normaliza whitespace, preserva acentos/maiúsculas/idioma, remove
pontuação final e limita a 80 caracteres com corte por palavra e `…`.
Não é um resumo semântico. "Primeiro turno" é decidido pela existência
de mensagens persistidas (não por `title is null`), pelo que uma
conversa com histórico nunca é retitulada; títulos manuais (na criação,
renomeados, ou já gerados) nunca são substituídos. O título é gravado na
**mesma transação curta** das mensagens e fontes, sob o lock da
conversa: falhas (502/503, revalidação, conversa fechada, commit) não
deixam título sem turno.

Cada turno persistido atualiza também `conversation.updated_at` com o
horário do turno, e a listagem ordena por `updated_at` desc (desempate
por `id` desc) — comportamento de aplicação de chat; turnos falhados não
alteram a posição. Renomear é `PATCH {"title": ...}`: permitido ao dono
(ou admin da instituição) mesmo em conversas `closed`/`archived`, que
continuam finais — qualquer payload que toque no `status` dessas
conversas é rejeitado por inteiro com 409, sem alterar o título. A
resposta de `/ask` não devolve o título: o frontend invalida a query de
detalhe da conversa e obtém-no do backend.

## Encaminhamento humano (E1)

`POST /api/v1/conversations/{conversation_id}/handoff` — **sem payload**. O
utilizador autenticado pede explicitamente que o atendimento continue com uma
pessoa; o backend valida o contexto, obtém o destino humano da própria
instituição e persiste uma mensagem `assistant` determinística.

Esta é a **capacidade de escalar**, não uma política que decida quando
escalar. A distinção é o âmbito da A2.3a e não deve ser lida como mais do que
é:

| Existe | Não existe |
| --- | --- |
| `DecisionOutcome.ESCALATE` como desfecho operacional real | `DecisionPolicy`, matriz de decisão, `policy_version` |
| origem `user_requested` | origem `system_decision` (escalação decidida pelo sistema) |
| um destino humano **default por instituição** | tipologia de serviços, encaminhamento por assunto, múltiplos destinos |
| mensagem auditável com snapshot do destino | ticket, fila, atribuição de operador, SLA, notificação interna, UI de operador |
| — | `AnswerabilityEvaluator`, `RequestSpecificity`, classificação da pergunta |

Não há inferência: o sistema **não** analisa a pergunta, não procura palavras
como "nota" ou "propina", e nunca decide sozinho encaminhar. A escalação
decidida pelo sistema (nível `system_decision`) depende da política de decisão,
que continua por validar — ver
[`docs/relatorios/a2-2-decision-policy-specification.md`](relatorios/a2-2-decision-policy-specification.md),
secções 7.6 e O6.

### Configuração institucional

Três campos anuláveis em `institutions`: `human_support_name`,
`human_support_email`, `human_support_url` (ver
[`docs/database.md`](database.md)). A configuração está **ou** totalmente
ausente, **ou** completa — nome com pelo menos uma via de contacto —, e a
invariante é aplicada no schema, no serviço e por `CheckConstraint`. Configurar
e ler continuam a exigir a autorização administrativa já existente; nenhuma
rota de instituição se tornou pública.

Os contactos são validados de forma determinística
(`app/core/contact.py`), sem dependência nova: o URL só pode ser `http`/`https`
— `javascript:`, `data:`, `file:` e `ftp:` são recusados —, e o email é
validado estruturalmente, não pela RFC 5322.

### Comportamento

```
utilizador
→ POST /conversations/{id}/handoff
→ autorização e isolamento das conversas (regras existentes)
→ lock instituição → utilizador → conversa (mesma ordem de /ask)
→ utilizador relido sob lock: ativo, e o papel usado é o persistido
→ conversa tem de estar active
→ destino humano da própria instituição
→ DecisionOutcome.ESCALATE
→ snapshot do destino
→ mensagem assistant determinística (pt/en, sem LLM)
→ commit único
```

Os três locks fecham janelas distintas e nenhum é decorativo: a **instituição**
torna o snapshot do destino coerente perante uma alteração administrativa
concorrente; o **utilizador** é relido porque `current_user` foi lido na
autenticação, num statement anterior — em READ COMMITTED, uma desativação ou
despromoção que faça commit entretanto não seria visível a esta transação, e o
papel usado a seguir é o **persistido**, para que um admin despromovido deixe
de alcançar conversas de outros utilizadores; a **conversa** garante que um
fecho concorrente não é ultrapassado. A ordem é exatamente a de
`ask_in_conversation`, para que os dois fluxos não possam entrar em deadlock.

O handoff **não chama o Retriever nem o AnswerGenerator**, não carrega o SDK
do fornecedor e não faz qualquer chamada externa. O endpoint nem sequer declara
essas dependências, e `human_handoff_service` não importa `app.retrieval` nem
`app.answering` — ambas as propriedades são fixadas por teste.

Respostas HTTP:

- `201` — encaminhamento registado: `outcome: "escalate"`, `conversation_id`,
  `destination` (`name`/`email`/`url`) e `assistant_message` persistida;
- `404` — conversa inexistente, de outro tenant ou inacessível, exatamente como
  no restante módulo conversacional;
- `409` — conversa `closed`/`archived`, **ou** instituição sem atendimento
  humano configurado (`Human support is not configured for this institution.`).
  Em qualquer dos casos nada é persistido e `conversation.updated_at` não muda;
- `401` — sem autenticação.

O corpo do pedido é ignorado por inteiro. `decision_outcome`, `handoff_trigger`,
`destination`, `institution_id` e `user_id` **nunca** vêm do cliente: o trigger
é determinado pelo endpoint usado, o destino pela instituição do utilizador
autenticado.

### Mensagem e auditabilidade

A mensagem é composta por `app/core/handoff_message.py` — função pura, texto
fixo por idioma (pt/en, inglês como fallback documentado), versionada em
`HANDOFF_MESSAGE_VERSION`. Segue o padrão de
`app/answering/fallback.py` e `app/core/conversation_title.py`: **sem LLM e sem
tradução automática**. A redação apenas direciona — nunca afirma que um caso
foi criado, que um operador recebeu o pedido ou que haverá resposta num prazo,
porque nada disso acontece em E1.

A mensagem persistida tem `role="assistant"`, `user_id=None`,
`reply_to_message_id=None` e `sources=[]` (nenhuma `MessageSource` é criada — o
encaminhamento não cita documentos). Não é fabricada nenhuma mensagem de
utilizador para representar o clique.

O `extra_metadata` guarda um **snapshot**, não uma referência viva:

```json
{
  "turn_type": "human_handoff",
  "decision_outcome": "escalate",
  "handoff_mode": "e1",
  "handoff_trigger": "user_requested",
  "message_version": "human_handoff_e1_v1",
  "handoff_destination": { "name": "...", "email": "...", "url": "..." }
}
```

Alterar depois a configuração da instituição **não** reescreve encaminhamentos
antigos: a leitura devolve o destino tal como foi apresentado na altura. É a
mesma disciplina de proveniência já aplicada a `MessageSource`, e está fixada
por teste. O metadata é apenas operacional: não contém a pergunta anterior,
conteúdo documental, prompts, tokens, credenciais nem dados pessoais.

**Sem idempotência.** Duas solicitações explícitas em momentos diferentes
produzem duas mensagens — são dois pedidos reais do utilizador, e o backend não
inventa uma chave de idempotência nem uma janela temporal arbitrária que
escondesse um deles. O frontend impede o duplo clique acidental através do
estado `pending` do botão.

### Interface

Em conversas **ativas**, a interface oferece "Falar com atendimento humano"
junto ao composer, como ação secundária; conversas `closed`/`archived` não
oferecem a ação. O botão fica desativado enquanto o pedido está pendente, e uma
falha mostra erro controlado sem fazer a ação desaparecer.

A ação é oferecida **mesmo quando a instituição não tem destino configurado**:
o pedido devolve 409 e a interface mostra o erro. A alternativa — esconder o
botão — exigiria que o utilizador comum pudesse ler a configuração da
instituição, que hoje é leitura de administrador; abrir essa superfície não
pertence a esta fase. A mensagem
apresentada é sempre a que o backend persistiu — nunca uma inserção apenas
local — e continua visível ao reabrir a conversa, porque vem do histórico. O
email é renderizado como `mailto:` e o URL como ligação externa com
`target="_blank"` e `rel="noopener noreferrer"`, ambos revalidados no cliente;
nada vindo do backend é interpretado como HTML.

Fora de âmbito nesta fase, e não implementado: E2 (transferência técnica do
caso), dashboard de operador, estados de resolução e integração com sistemas
institucionais.

## Arquitetura

- `app/answering/base.py` — contratos neutros: `AnsweringContext`,
  `ContextEvidence`, `GeneratedAnswer`, `AnswerGenerator` (Protocol) e as
  exceções tipadas (`AnswerGeneratorUnavailableError` → 503,
  `AnswerGenerationError` / `InvalidGeneratedAnswerError` → 502).
- `app/answering/context.py` — atribui IDs estáveis (E1, E2, ...) pela
  ordem do ranking, deduplica chunks e seleciona evidências completas até
  o JSON final atingir `ANSWERING_MAX_CONTEXT_CHARS` (exceção documentada:
  a melhor evidência entra sempre). Campos internos nunca são incluídos.
- `app/answering/prompts.py` — usa um system prompt completamente estático
  e normativo. Instituição, pergunta, idioma e evidências são valores de
  um único objeto criado com `json.dumps`; títulos, URLs e conteúdo não
  conseguem alterar sintaticamente a estrutura exterior.
- `app/answering/validation.py` — validação determinística: resposta não
  vazia, dentro de `ANSWERING_MAX_ANSWER_CHARS`, citações não vazias, sem
  duplicados e todas existentes no contexto. Violação → geração rejeitada
  (nunca se adivinha a fonte). Quando a validação rejeita a geração, o log
  recebe apenas `institution_id`, um reason code estável e uma contagem;
  nunca IDs nem texto devolvido pelo fornecedor.
- `app/answering/fallback.py` — mensagens fixas por idioma (pt/en);
  idioma sem mensagem própria usa inglês (documentado), nunca erro 500.
- `app/answering/providers/openai.py` — único módulo que conhece o SDK;
  converte qualquer falha em exceções internas seguras; nunca regista
  mensagem, traceback, chave, pergunta, contexto, headers ou resposta
  bruta do fornecedor. O cliente usa `max_retries=0` explicitamente.
- `app/answering/dependencies.py` — `get_answer_generator()` devolve o
  provider configurado sem acoplar rota/service à classe concreta,
  permitindo outro fornecedor, modelo local ou gerador determinístico.
- `app/services/answering_service.py` — orquestração fina; sem SQL, sem
  SDK, sem persistência.
- `app/services/conversation_answering_service.py` — coordena o turno
  persistente sem duplicar retrieval ou geração; separa a transação de
  leitura da transação curta de escrita.
- `app/services/message_source_service.py` — bloqueia e revalida as fontes,
  cria snapshots e lista citações dentro do tenant; não faz commit.
- `app/services/human_handoff_service.py` — encaminhamento humano E1, numa
  transação curta e sem qualquer chamada externa; não importa retrieval nem
  answering.
- `app/core/handoff_message.py` — mensagem determinística do encaminhamento,
  pura e versionada, sem LLM.
- `app/core/contact.py` — validação determinística de email/URL de contacto,
  usada pela configuração institucional.
- `app/models/message_source.py` — snapshots auditáveis dos metadados das
  fontes efetivamente citadas.

## Atomicidade, revalidação e histórico

A chamada externa ocorre antes de qualquer insert e sem locks de escrita.
Depois da geração, a transação de leitura é terminada. A instituição ativa, o
utilizador ativo e o papel atual, e depois a conversa são relidos com
`SELECT FOR UPDATE`; acesso e estado `active` são novamente confirmados. As
versões/documentos/chunks citados são então bloqueados em ordem determinística.
Os locks ficam retidos até ao commit, portanto uma desativação ou perda de
privilégio concorrente não pode atravessar a janela entre autorização e
persistência.

A **admissibilidade documental** desta revalidação — estado `processed`,
documento ativo, idioma do documento e do chunk, validade e `official_only` —
não é definida pelo service: é decidida por `CitationPersistenceEligibility`, de
`app.documents.retrievability`. Essa política partilha C1–C4 e C6–C11 com o
retrieval, mas **deliberadamente não exige C5** (ser a versão `processed` mais
recente): uma versão N usada para gerar a resposta continua a ser a fonte
correta se N+1 for processada antes da persistência. Registar N+1 seria
factualmente falso, e recusar por conflito descartaria uma resposta legítima por
causa de um carregamento concorrente que nada tem que ver com ela.

As restantes verificações continuam a ser responsabilidade do service, e **não**
fazem parte da política: a consistência dos identificadores (`identifiers_match`,
defesa em profundidade sobre a FK composta) e a integridade do snapshot. Um
SHA-256 é calculado internamente sobre o conteúdo devolvido pelo Retriever — e
fica ausente de JSON, schema e OpenAPI —, depois comparado com o valor bloqueado
e com um hash recalculado sobre `content`; também se verificam os metadados
recuperados (`metadata_unchanged`), o `normalized_content` e o trecho
correspondente de `extracted_text`. Uma alteração concorrente responde 409, com
mensagem genérica que nunca revela a condição concreta que falhou, e nada é
persistido.

Só depois são inseridas, nesta ordem, a mensagem user, a assistant e as
`message_sources`; existe um único commit. Qualquer erro de flush, constraint
ou commit faz rollback do conjunto inteiro. Falhas do provider (502),
configuração ausente quando necessária (503) e respostas/citações inválidas
também deixam zero mensagens.

Cada `MessageSource` guarda título, URL, oficialidade, idioma, validade,
índice do chunk e SHA-256 como snapshot. Alterar posteriormente o documento
não reescreve respostas antigas. O conteúdo não é duplicado: uma FK composta
impede apagar ou reassociar o chunk original, e um trigger PostgreSQL impede
qualquer `UPDATE` da linha citada. Uma versão já citada não pode ser
reprocessada; deve ser carregada uma nova versão. O script
`rebuild_document_chunks` também ignora versões citadas e reporta
`skipped_referenced`.

`GET /api/v1/conversations/{conversation_id}/messages` inclui
`reply_to_message_id` e `sources` em cada item, carregadas em lote e ordenadas,
sem alterar paginação nem a ordenação histórica por `created_at`/`id`.

## Política de evidência

- zero evidências → `insufficient_evidence` (fallback, sem gerador);
- uma ou mais evidências → geração permitida;
- resposta sem citações válidas → geração rejeitada (502);
- todas as fontes devolvidas foram citadas pelo gerador.

Sem confidence score numérico nesta etapa. O `score` das evidências é a
relevância lexical composta em `[0, 1]` (Momento 4), determinística e
ordenável, mas **não** é uma probabilidade nem uma medida universal de
confiança factual; o `ts_rank_cd` cru é apenas um dos seus sinais
auxiliares e não é exposto pelo answering.

O retriever devolve um `RetrievalResult` — evidência, trace e semântica do
score (ver [`docs/database.md`](database.md)). O answering usa **apenas**
`result.evidence`, e continua a decidir pela política acima: zero evidências
→ fallback. O trace e as suas contagens estão disponíveis e são
deliberadamente ignorados aqui — interpretá-los para decidir seria avaliar
se a evidência *chega* para responder, o que é outra etapa e não existe
nesta fase.

## Configuração

Ver `.env.example`:

- `ANSWER_GENERATOR_PROVIDER` (padrão: `openai`);
- `ANSWERING_DEFAULT_TOP_K` / `ANSWERING_MAX_TOP_K`;
- `ANSWERING_MAX_CONTEXT_CHARS` / `ANSWERING_MAX_ANSWER_CHARS`;
- `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`.

**A aplicação inicia sem `OPENAI_API_KEY`** — a ausência de configuração
só produz efeito (503) quando o endpoint de answering precisa de gerar.
Perguntas sem evidências continuam a devolver o fallback sem contactar o
provider. A chave nunca aparece em logs, exceções ou respostas. Os testes
correm sem rede e sem credenciais (o adapter é testado com um cliente
simulado; o gerador é substituído por dependency override).

## Separação entre instruções e dados

O system prompt contém apenas regras controladas pela aplicação. Todos os
dados institucionais são tratados como não confiáveis e enviados no payload
JSON da mensagem de utilizador. A serialização estruturada reduz ambiguidades
de fronteira e impede que conteúdo documental, delimitadores falsos ou JSON
embutido alterem sintaticamente a estrutura construída pela aplicação.

Esta medida não elimina prompt injection nem alucinações: o conteúdo continua
não confiável, o modelo continua sujeito a avaliação experimental e a
validação desta etapa permanece estrutural, não semântica.

Cada pergunta continua independente: mensagens anteriores nunca entram no
prompt. Não há idempotency key nem garantia de ordem de submissão para
perguntas concorrentes na mesma conversa; o histórico reflete a ordem dos
commits.

## Medição da qualidade

Existe uma baseline **estrutural offline** desta camada, registada em
[`docs/relatorios/moment-05-baseline-p1.json`](relatorios/moment-05-baseline-p1.json),
que é a sua fonte primária única. O método, os
cenários e as métricas estão especificados em
[`docs/ai/moments/moment-05.md`](ai/moments/moment-05.md) e não são repetidos
aqui.

Alcance, para que a leitura não infira mais do que foi medido:

- mede o comportamento observável do turno sobre um corpus **sintético** e
  respostas controladas de um gerador falso — **não** mede a qualidade do
  fornecedor atualmente configurado;
- as métricas apuradas são estruturais e determinísticas: estado devolvido,
  citações válidas, esperadas, duplicadas ou desconhecidas, limites de
  resposta, invocação do gerador, desfecho e ausência literal de afirmações
  proibidas;
- as métricas semânticas — correção factual, fidelidade à evidência,
  completude, clareza, concisão — dependem de avaliação humana e constam da
  baseline como **não medidas**, nunca como zero;
- nada nesta baseline torna o sistema livre de alucinações, e a validação
  desta etapa continua estrutural, não semântica.
