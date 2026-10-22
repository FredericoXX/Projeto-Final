# Perfis, permissões e acesso institucional individual

Fonte canónica da matriz de permissões, da associação de identidade externa e
da consulta preparatória dos próprios pedidos académicos. Descreve o que está
**implementado** e o que está apenas **preparado**; as duas coisas estão
assinaladas em cada secção.

O objeto de investigação não muda: o assistente continua a ser avaliado como
modelo de decisão fundamentado em evidência, com separação entre diagnóstico e
decisão e as ações responder, clarificar, abster-se e encaminhar. Este
incremento prepara o terreno para que a evidência possa vir, no futuro, de duas
origens — documentos institucionais e serviços institucionais autorizados —
sem integrar ainda nenhuma política de decisão.

## 1. Matriz de permissões

**Implementado.** A matriz vive num único sítio,
[`backend/app/core/permissions.py`](../backend/app/core/permissions.py), e é
verificada no backend pela dependência `require_permission(...)`. O papel é
sempre relido da base de dados em cada pedido; o token nunca o transporta.
`GET /api/v1/auth/me` devolve, além do papel, a lista `permissions` efetiva, e
o frontend adapta a interface a essa lista em vez de replicar a matriz.

| Permissão | `admin` | `knowledge_manager` | `staff` | `student` | `user` |
| --- | :-: | :-: | :-: | :-: | :-: |
| `users.manage` — contas da própria instituição | ✓ | | | | |
| `institution.manage` — ler e configurar a própria instituição | ✓ | | | | |
| `external_identity.manage` — associar/desassociar identidade externa | ✓ | | | | |
| `conversations.system_messages` — mensagens `role="system"` nas próprias conversas | ✓ | | | | |
| `documents.manage` — documentos, metadados, versões, processamento, vigência | | ✓ | | | |
| `academic_requests.read_own` — consultar os próprios pedidos académicos | | | | ✓ | ✓ |

Comum a **todas** as contas autenticadas, fora da matriz: criar e usar as
próprias conversas, perguntar (`/answering/ask`, `/conversations/{id}/ask`),
pesquisar evidência (`/retrieval/search`) e pedir encaminhamento E1
(`/conversations/{id}/handoff`).

Não existe nenhuma permissão de leitura de conversas de terceiros. Leitura,
listagem, contagem e mutação de conversas, mensagens e fontes são sempre
filtradas por instituição **e** por posse, para qualquer papel.

Princípios mantidos:

- a instituição e a identidade de autorização resultam sempre da sessão
  validada, nunca do payload ou do caminho;
- a autorização é **reconfirmada no ponto sensível** de cada operação (ver
  [secção 1.1](#11-revalidação-perante-revogação-concorrente)), e não apenas no
  início do pedido;
- um recurso de outra instituição responde como inexistente (404);
- não há motor genérico de autorização nem hierarquia de papéis: nenhum papel
  herda de outro;
- curso, ano e situação académica são atributos de contexto, não papéis.

### 1.1 Revalidação perante revogação concorrente

`get_current_user` relê papel e estado no início de cada pedido, mas entre
essa leitura e a operação outra transação pode desativar a conta, alterar-lhe
o papel ou desativar a instituição. Para que o pedido em curso não complete
com uma autorização já revogada,
[`authorization_service.revalidate_actor`](../backend/app/services/authorization_service.py)
relê instituição e conta **sob lock**, na transação da operação e pela ordem
instituição → utilizador → recurso, e reverifica a permissão sobre o papel
relido. Uma conta ou instituição inativa responde 401; um papel sem a
permissão responde 403. Uma revogação que faça commit antes é vista; uma
posterior espera pelo fim da operação.

| Operações | Revalidação |
| --- | --- |
| documentos: criar, listar, ler, alterar, eliminar, versões, upload, conteúdo, download, reprocessar | `documents.manage`, locks partilhados |
| contas: criar, listar, ler, alterar | `users.manage`, lock exclusivo da instituição nas mutações |
| instituição: ler, listar; alterar | `institution.manage`; exclusivo na alteração |
| associação externa: ler, associar, remover | `external_identity.manage` |
| conversas próprias: criar, ler, listar, renomear, listar mensagens; pesquisa de evidência | conta ativa |
| mensagens, `/ask` e handoff na conversa | já existente: instituição → utilizador → conversa, sob `FOR UPDATE` |
| `/answering/ask` (sem conversa) | depois da geração e antes de entregar a resposta |
| consulta de pedidos académicos | antes da fonte, sem locks durante a fonte, e de novo depois dela; nas duas verificações, também a linha da associação fica sob `FOR SHARE` |
| disponibilidade da consulta (`/academic-requests/access`) | conta e instituição relidas sob lock; permissão avaliada sobre o papel relido; associação sob `FOR SHARE` até à resposta |

Os locks são `FOR SHARE` por omissão: bloqueiam a revogação concorrente sem
serializar operações da mesma conta entre si. Todos os fluxos bloqueiam pela
mesma ordem — instituição → utilizador → recurso —, incluindo as revogações
feitas pela aplicação (`update_user`), o que exclui deadlocks entre eles; nas
mutações, os locks são adquiridos antes da primeira escrita, na mesma
transação, e duram até ao commit. Nenhum fluxo mantém locks
durante uma chamada externa: o `/answering/ask` e a consulta académica
revalidam depois da chamada, e a consulta académica termina a transação antes
de chamar a fonte. O upload de um ficheiro mantém os locks partilhados enquanto
o ficheiro é escrito no armazenamento (limitado a `DOCUMENT_MAX_FILE_SIZE_MB`);
a extração e o OCR correm depois do commit, sem eles.

### Papéis

- **`admin`** — administrador técnico **institucional**: contas, permissões,
  associações de identidade externa e configuração da própria instituição. Não
  é um administrador global da plataforma (que continua a não existir; o
  bootstrap mantém-se protegido por `BOOTSTRAP_TOKEN`).
- **`knowledge_manager`** — gestão documental, com as regras existentes sobre
  fontes citadas e preservação do histórico (um documento citado só pode ser
  desativado; uma versão citada não é reprocessada). Não gere contas, não
  configura a instituição e não consulta conversas nem registos académicos de
  terceiros.
- **`staff`** — base documentada do futuro operador institucional. Nesta etapa
  tem apenas as próprias conversas. O acesso a casos atribuídos depende de um
  fluxo de atendimento que ainda não existe e **não** é simulado com acesso
  irrestrito a conversas. Não há fila nem painel de operador.
- **`student`** — aluno.
- **`user`** — utilizador institucional genérico.

Não existem, neste incremento, visitante público nem perfis de docente,
coordenador ou direção.

## 2. Mudança intencional do contrato de autorização do `admin`

Antes deste incremento, o `admin` institucional:

1. lia, listava, contava, renomeava, escrevia e encaminhava **qualquer**
   conversa da sua instituição;
2. geria o núcleo documental, que era exclusivo de administradores.

Depois:

1. o `admin` acede apenas às **próprias** conversas, como qualquer outra conta;
   uma conversa alheia responde 404 (leitura, mensagens, renomeação, `/ask`,
   `/handoff`);
2. a gestão documental deixou de ser uma permissão implícita de `admin` e
   pertence a `knowledge_manager`; um `admin` recebe 403 em `/documents`.

Compatibilidade:

- contas, conversas, mensagens e citações existentes são preservadas;
  nenhuma linha é alterada pela migration;
- nenhum `admin` é convertido automaticamente em `knowledge_manager`;
- uma instituição que precise de gerir documentos cria (ou promove) uma conta
  `knowledge_manager` — ver a secção seguinte;
- a regra "a instituição mantém pelo menos um admin ativo" não mudou;
- o caminho de interface `/admin/documents` foi mantido por compatibilidade,
  mas a área é guardada por `documents.manage`.

## 3. Criar um `knowledge_manager`

Um `admin` autenticado cria a conta pela API existente, com credenciais
definidas pelos mecanismos habituais (nunca versionadas):

```http
POST /api/v1/users
Authorization: Bearer <token do admin>

{ "full_name": "Gestor Documental", "email": "gestor@example.invalid",
  "password": "<palavra-passe>", "role": "knowledge_manager" }
```

Ou promove uma conta existente com `PATCH /api/v1/users/{id}` e
`{"role": "knowledge_manager"}`. O efeito é imediato no pedido seguinte, sem
novo login, porque o papel é relido da base de dados. O bootstrap
(`register-initial-admin`) e o seed de demonstração não mudaram: continuam a
criar apenas a instituição e o primeiro admin.

## 4. Associação de identidade externa

**Implementado (mecanismo administrativo); preparado (autenticação
institucional).**

A tabela `user_external_identities` associa uma conta local, a sua instituição
e um **identificador externo estável** do sistema académico (`external_subject`,
opaco para a aplicação). É a única prova aceite de que uma conta corresponde a
uma pessoa no sistema académico; a igualdade de email **não** é usada.

| Operação | Rota | Permissão |
| --- | --- | --- |
| Ler | `GET /api/v1/users/{user_id}/external-identity` | `external_identity.manage` |
| Associar | `PUT /api/v1/users/{user_id}/external-identity` com `{"external_subject": "..."}` | `external_identity.manage` |
| Remover | `DELETE /api/v1/users/{user_id}/external-identity` | `external_identity.manage` |

Regras:

- só um `admin` autenticado da **mesma** instituição associa ou remove; a conta
  de outra instituição responde 404;
- o utilizador associado não tem nenhuma operação sobre a associação; nenhum
  payload, parâmetro ou mensagem do chat a altera;
- uma conta tem no máximo uma associação; um identificador corresponde, dentro
  de uma instituição, a no máximo uma conta;
- repetir a mesma associação é idempotente; mudar o identificador exige remover
  primeiro a associação existente (409 caso contrário);
- só papéis com `academic_requests.read_own` (`student`, `user`) são
  associáveis (409 caso contrário). Uma alteração posterior de papel não apaga a
  associação, mas a consulta deixa de ser permitida enquanto o papel não tiver a
  permissão;
- `link_method` regista como a associação foi estabelecida. O único valor
  aceite é `administrative`; um valor para a futura autenticação institucional
  só será acrescentado, por migration, quando o protocolo existir.

**Não existe SSO.** O login continua a ser local (email e palavra-passe). Não
foram inventados endpoints, tokens, campos nem fluxos de autenticação de
nenhuma universidade.

## 5. Contrato neutro do fornecedor institucional

**Implementado como contrato; existe apenas o adaptador simulado.**

[`backend/app/institutional/contracts.py`](../backend/app/institutional/contracts.py)
define o contrato, separado da recuperação documental e da geração de
linguagem (nenhum importa o outro, e há teste que o fixa):

- `AuthorizedInstitutionalIdentity(institution_id, external_subject)` —
  construída **pelo backend**, a partir da sessão validada e da associação
  persistida. O adaptador nunca recebe texto livre, email ou um identificador
  escolhido pelo cliente;
- `AcademicRequestQuery(kind, request_id)` — consulta estruturada: `list` ou
  `detail`. O `request_id` vindo do cliente é validado
  (`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`) antes de chegar ao adaptador;
- `AcademicRequestRecord(request_id, request_type, official_status,
  updated_at, next_step)` — um pedido **existente** no sistema académico, não
  um caso criado pelo assistente. `official_status` é conservado tal como
  recebido; `next_step` só existe quando a fonte o fornece;
- `AcademicRequestsResult(outcome, records, source_updated_at)`;
- `InstitutionalDataProvider` — o protocolo que um adaptador real terá de
  implementar: `simulated`, `serves(institution_id)` e
  `query_academic_requests(identity, query)`.

Os dados são delimitados pelo **par instituição/identificador externo**: o
mesmo identificador em duas instituições designa duas pessoas distintas. Cada
adaptador declara as instituições que serve; para uma instituição não servida
a integração está, para ela, não configurada, e o backend não consulta a fonte.
Uma identidade de instituição não servida que chegue ao adaptador é recusada
(`access_denied`), nunca resolvida contra os dados de outra.

### Resultados distintos

| `InstitutionalAccessOutcome` | Significado | HTTP | `detail.code` |
| --- | --- | --- | --- |
| `success` | dados da identidade autorizada | 200 | — |
| `no_data` | sem pedidos (lista) / pedido inexistente para esta identidade (detalhe) | 200 lista · 404 detalhe | — · `resource_not_found` |
| `access_denied` | sem associação autorizada, recusa da fonte, ou papel/associação alterados durante a consulta | 403 | `institutional_access_denied` |
| `not_configured` | integração desativada, ou instituição não servida pelo adaptador | 503 | `institutional_integration_not_configured` |
| `unavailable` | falha técnica da fonte (inclui exceções e output inconsistente) | 502 | `institutional_integration_unavailable` |

Todos estes resultados transportam proveniência (secção 6): no corpo, em sucesso
e na lista vazia; em `detail.provenance`, nos restantes — incluindo o 404 do
detalhe. A desativação da conta durante a consulta responde 401, sem
proveniência: deixou de haver uma conta autorizada a quem a entregar.

Uma conta cujo papel não tem `academic_requests.read_own` recebe o 403
genérico (`forbidden`) da matriz antes de chegar ao serviço.

Um pedido de outro aluno — da mesma ou de outra instituição — e um pedido
inexistente são **indistinguíveis**: o adaptador filtra pela identidade
(instituição e identificador) antes de procurar o identificador do pedido, e a
resposta é a mesma, proveniência incluída, a menos dos instantes da consulta.

Uma falha técnica **não** é abstenção nem encaminhamento: os valores de
`InstitutionalAccessOutcome` são disjuntos de `DecisionOutcome`, e nenhum
resultado da integração cria mensagens ou decisões.

### Rotas

| Rota | Quem | O que faz |
| --- | --- | --- |
| `GET /api/v1/academic-requests/access` | qualquer conta autenticada | diz se a área está disponível (`available`, `not_permitted`, `not_configured`, `not_linked`) e se é simulada, **sem** contactar a fonte |
| `GET /api/v1/academic-requests` | `academic_requests.read_own` | lista os próprios pedidos |
| `GET /api/v1/academic-requests/{request_id}` | `academic_requests.read_own` | detalhe de um pedido próprio |

Só leitura, iniciada pelo utilizador. Não há criação, aprovação, alteração nem
cancelamento de pedidos, e não há notificações, polling, webhooks, emails, SMS
ou push. Limitação conhecida: o segmento `access` está reservado, pelo que um
pedido cujo identificador seja literalmente `access` não é consultável por
detalhe.

## 6. Proveniência

**Implementado em todos os resultados; não persistido.**

Cada resultado da consulta — sucesso, lista vazia, 404 do detalhe, acesso
recusado, integração não configurada e falha técnica — transporta
`provenance`:

- `origin: "institutional_api"` — distinta da origem documental
  (`EvidenceOrigin.DOCUMENT`, que é o que as citações persistidas em
  `message_sources` representam);
- `simulated` — `true` com o adaptador simulado ativo;
- `institution_id` — da sessão validada;
- `attempted_at` — momento em que o backend começou a tratar a consulta;
- `source_consulted` — `false` quando o backend recusou antes de chegar à
  fonte (integração desativada ou não servida, conta sem associação);
- `queried_at` — momento da consulta à fonte; `null` se não foi consultada;
- `source_updated_at` — atualização da fonte, quando disponível; `null` se a
  fonte não foi consultada;
- `access_result` — um dos cinco resultados;
- `fields_used` — os campos dos registos efetivamente usados (`next_step` só
  quando presente); vazio em qualquer resultado sem registos.

A proveniência nunca contém o identificador externo nem dados de outra conta.

Os dados recebidos são **dados não confiáveis** para efeitos de instruções a um
modelo: não mudam permissões nem o comportamento do backend, e nunca são
concatenados com instruções. Nesta fase nem chegam a um modelo.

Não entram em logs segredos, identificadores externos, dados académicos,
perguntas nem respostas. Perante uma exceção do adaptador, o log regista apenas
o tipo da exceção.

## 7. Modo simulado

**Implementado; desativado por omissão.**

`INSTITUTIONAL_DATA_PROVIDER` aceita `disabled` (omissão) ou `mock`. Com
`disabled`, a aplicação arranca sem API externa e sem credenciais, e nenhuma
conta vê dados simulados: a área responde `not_configured`. `mock` só é aceite
com `ENVIRONMENT=development` ou `test`; noutro ambiente a aplicação recusa
arrancar. O adaptador simulado só é importado quando é selecionado.

O adaptador simulado
([`backend/app/institutional/providers/mock.py`](../backend/app/institutional/providers/mock.py))
usa um snapshot **sintético e fixo** (versionado no código), sem rede, sem
ficheiros e sem LLM, delimitado por instituição. Serve apenas as instituições
cujo código é `DEMO-HEI` (a criada por `scripts/seed_demo_institution.py`) ou
`DEMO-HEI-B`; as restantes ficam com a integração não configurada.

| Instituição | `external_subject` | Resultado |
| --- | --- | --- |
| `DEMO-HEI` | `SYNTH-STUDENT-0001` | três pedidos, dois com próximo passo |
| `DEMO-HEI` | `SYNTH-STUDENT-0002` | um pedido |
| `DEMO-HEI` | `SYNTH-STUDENT-0003` | nenhum pedido (`no_data`) |
| `DEMO-HEI-B` | `SYNTH-STUDENT-0001` | **outro** aluno, com um pedido distinto |
| qualquer servida | `SYNTH-ACCESS-DENIED` | recusa da fonte (`access_denied`) |
| qualquer servida | `SYNTH-UNAVAILABLE` | falha técnica (`unavailable`) |
| qualquer servida | outro identificador | `no_data` |

O âmbito é resolvido pelo código da instituição, que um admin pode alterar.
Uma instituição que passe a usar um destes códigos recebe dados sintéticos,
assinalados como simulados — aceitável apenas porque o modo simulado está
restrito a `development` e `test`.

Na interface, o modo simulado é identificado por um aviso "Demonstração" em
cada página da área.

### Testar a demonstração

1. `.env`: `ENVIRONMENT=development` e `INSTITUTIONAL_DATA_PROVIDER=mock`;
   reiniciar a API.
2. Criar a instituição de demonstração `DEMO-HEI`
   (`python -m scripts.seed_demo_institution`) e o seu primeiro admin (ver
   [`README.md`](../README.md#inicialização-de-uma-instituição)). Outra
   instituição não é servida pelo adaptador simulado.
3. Como admin, criar um aluno sintético (`POST /api/v1/users` com
   `"role": "student"`) e associá-lo:
   `PUT /api/v1/users/{id}/external-identity` com
   `{"external_subject": "SYNTH-STUDENT-0001"}`.
4. Iniciar sessão no frontend com o aluno: a entrada "Os meus pedidos" aparece
   na navegação.
5. Repetir com `SYNTH-STUDENT-0003`, `SYNTH-ACCESS-DENIED` ou
   `SYNTH-UNAVAILABLE` para ver o estado vazio e os erros.

Com `INSTITUTIONAL_DATA_PROVIDER=disabled`, a entrada não aparece e a rota
explica que a consulta não está disponível.

## 8. Persistência e retenção — requisitos por definir

**Nada é persistido neste incremento.** As respostas do fornecedor não são
guardadas, não entram em `messages`, na base vetorial nem no corpus
documental; os ensaios usam o snapshot sintético fixo. A única informação nova
persistida é a associação de identidade (sem dados académicos).

Antes de auditar decisões reais com dados individuais, terão de ser definidos:

- **o mínimo a persistir** por decisão: provavelmente a referência à consulta
  (`queried_at`, `source_updated_at`, `access_result`, `fields_used`,
  identificadores dos registos) e não os valores, a menos que a auditoria os
  exija;
- **base legal e finalidade** do tratamento, e quem as aprova na instituição;
- **prazo de retenção** e mecanismo de eliminação, incluindo o efeito da
  remoção de uma associação ou da desativação de uma conta;
- **quem pode ler** esse registo (nenhum papel atual tem essa permissão);
- **pseudonimização** do `external_subject` em registos de auditoria e em
  exportações de avaliação;
- se a reprodutibilidade das avaliações continua a assentar exclusivamente em
  snapshots sintéticos.

## 9. Ligação futura ao diagnóstico e à política de decisão

**Não implementado.** A consulta é estruturada e determinística: não há
classificação por palavras-chave, e o chat continua a usar apenas documentos —
não promete nem afirma ter consultado o sistema académico.

Quando a política atual estiver integralmente disponível, o caminho previsto é:

1. o diagnóstico identifica que o pedido exige dados individuais
   (`RequestConstraint.PERSONAL_DATA_REQUIRED`);
2. se a conta tiver associação autorizada e a integração estiver ativa, o
   service `academic_request_service` (e não uma rota HTTP) obtém os registos
   com a mesma identidade e o mesmo contrato;
3. o resultado (`InstitutionalAccessOutcome` + proveniência) entra no
   diagnóstico como evidência de origem `institutional_api`, ao lado da
   evidência documental;
4. a ação (responder, clarificar, abster-se ou encaminhar) é decidida pela
   política, com os mesmos snapshots sintéticos usados nos compositores por
   regras e por LLM.

`PERSONAL_DATA_REQUIRED` **não** é mapeado para `ESCALATE`: a obtenção
autorizada de dados pode permitir satisfazer o pedido, e a ação depende da
política ainda a integrar.

O encaminhamento E1 mantém-se como estava, com as autorizações corrigidas: é
pedido pelo utilizador, apenas na própria conversa, e apresenta um contacto.
**Não** transfere o caso para um operador; a fila e o registo de resolução
(E2) pertencem a outro incremento.

## 10. Estado da especificação D0–D6 / R01–R12

O desenho revisto da tese refere sete dimensões D0–D6 e doze regras R01–R12.
**A especificação integral não foi encontrada neste repositório**, e por isso
**D0–D6/R01–R12 não estão executáveis**. O que o repositório contém:

- [`docs/relatorios/a2-2-decision-policy-specification.md`](relatorios/a2-2-decision-policy-specification.md)
  — especificação **histórica** A2.2, com seis dimensões D1–D6 e uma matriz
  M1–M9 com decisões normativas O1–O7 em aberto. Não define D0 nem regras
  R01–R12, e não foi adaptada como se fosse a política atual;
- [`backend/app/decision/contracts.py`](../backend/app/decision/contracts.py) —
  vocabulário provisório (A2.1), sem política.

Para o incremento de política falta, de forma precisa:

1. a definição de **D0** e a versão revista de D1–D6 (nome, valores, critério
   observável de cada valor e ordem de avaliação), indicando o que mudou face à
   A2.2;
2. o texto integral de **R01–R12**: condição, ação resultante, prioridade
   entre regras e regra por omissão;
3. os **limiares** numéricos, se existirem;
4. o estado de aprovação de cada elemento (proposta vs. decisão aprovada, por
   quem e quando);
5. como a evidência de origem `institutional_api` e os cinco resultados de
   acesso entram nas dimensões — em particular, que ação segue de `unavailable`
   e de `access_denied`;
6. a decisão sobre E2 (fila, atribuição, registo de resolução) que a política
   pressupõe para `ESCALATE`.

## 11. Limites desta implementação

- Não há adaptador real, SSO, nem chamadas externas; o modo simulado é a única
  fonte de dados individuais.
- A interface não tem gestão de contas nem de associações: são feitas pela API
  (por exemplo, pela documentação interativa).
- O adaptador simulado serve apenas as instituições sintéticas `DEMO-HEI` e
  `DEMO-HEI-B`; um adaptador real terá de ser configurado por instituição.
- Uma desativação da conta a meio da consulta responde 401, sem proveniência.
- `staff` não tem casos atribuídos; o operador institucional não existe.
- Nenhuma decisão do assistente usa a integração.

## 12. Correções após a auditoria de 2026-10-09

A auditoria
[`docs/audits/2026-10-09-institutional-preparation.md`](audits/2026-10-09-institutional-preparation.md)
deu o incremento como **parcialmente confirmado**, com três falhas. As três
foram reproduzidas antes de serem corrigidas e estão fechadas na mesma branch:

| Falha | Correção | Testes que a fixam |
| --- | --- | --- |
| **F1 (alta)** — operações completavam depois de uma revogação já gravada (documento criado por gestor despromovido, associação por admin despromovido, pedidos devolvidos e conversa renomeada por aluno desativado) | revalidação sob lock no ponto sensível (secção 1.1), estendida às restantes operações privilegiadas e às conversas próprias; na consulta académica, revalidação antes e depois da fonte, sem locks durante ela | `tests/test_concurrent_revocation.py`; casos de revogação e `test_no_database_lock_is_held_during_the_source_call` em `tests/test_academic_requests.py` |
| **F2 (média)** — o adaptador simulado ignorava a instituição | snapshot delimitado por instituição/identificador; `serves(institution_id)` no contrato | `test_the_same_external_subject_in_two_institutions_reads_distinct_records`, `test_an_institution_not_served_by_the_adapter_is_not_configured`, `test_mock_provider_*` |
| **F3 (média)** — os resultados sem sucesso não transportavam proveniência | proveniência em todos os resultados, com `attempted_at` e `source_consulted` | casos de proveniência em `tests/test_academic_requests.py` |

Para confirmar que os testes novos detetam as lacunas, foram executados contra
três mutantes temporários, não versionados: `revalidate_actor` sem
verificações, consulta académica sem a reverificação posterior à fonte, e
consulta que mantém os locks durante a chamada à fonte. Cada mutante faz falhar
pelo menos um dos testes novos.

**Segunda passagem (2026-10-22).** Uma revisão das mesmas três correções
contra o pedido de correção final acrescentou:

- **lock da associação na consulta académica.** A reverificação posterior à
  fonte relia a associação sem a bloquear. A remoção da associação só bloqueia
  a instituição e o admin, e podia fazer commit entre essa releitura e a
  entrega. `find_link_for_account(..., lock=True)` passa a manter a linha sob
  `FOR SHARE` até ao fim da transação, depois da instituição e da conta. O
  teste
  `test_account_institution_and_link_stay_locked_from_the_final_check_to_delivery`
  falha sem o lock: só a linha da associação ficava livre;
- **casos de revogação em falta:**
  - associação e remoção por admin despromovido e por admin desativado;
  - reprocessamento por gestor despromovido;
  - desativação da instituição durante a consulta académica;
  - revogações durante a fonte também no detalhe;
  - mensagens, `/ask` e handoff na conversa depois de uma desativação, nos
    caminhos que já estavam protegidos;
- **ausência de locks durante a geração** (`test_no_database_lock_is_held_during_generation`,
  com `FOR UPDATE NOWAIT` noutra sessão), no `/answering/ask` e no `/ask` da
  conversa;
- **ordem dos locks:**
  `test_every_flow_locks_institution_then_account_then_resources` regista,
  por transação, os locks de cada fluxo. Exige a ordem
  instituição → utilizador → recurso e, nas mutações, os dois locks de
  autorização antes da primeira escrita. Um mutante com a ordem invertida em
  `revalidate_actor` faz o teste falhar;
- **delimitação do mock:**
  - a indistinguibilidade do detalhe entre instituições;
  - o detalhe numa instituição não servida;
  - os cenários `success`, `no_data`, `access_denied` e `unavailable` em cada
    instituição servida;
- **proveniência da lista vazia.**

**Revisão final (2026-10-22).** A revisão independente da segunda passagem
encontrou uma última janela. `GET /academic-requests/access` decidia sobre o
papel do objeto da autenticação, sem reler a conta, e lia a associação sem a
bloquear. Uma conta desativada ou despromovida depois da autenticação ainda
recebia `available: true`. Não eram entregues pedidos, mas a resposta revelava
metadados de disponibilidade e associação com uma autorização obsoleta.

A correção:

- `get_access` passa a reler conta e instituição sob lock
  (`revalidate_actor`);
- a permissão é avaliada sobre o papel relido;
- a associação é lida com `lock=True`.

Reproduzido antes da correção:
`test_access_check_after_revocation_reflects_the_persisted_state` falhava nos
casos de conta desativada (esperado 401), instituição desativada (401) e papel
alterado (`not_permitted`), e
`test_access_check_keeps_account_institution_and_link_locked_until_delivery`
também falhava. O caso de associação removida (`not_linked`) já passava,
porque a associação era lida fresca; fica como guarda de regressão. O teste
estrutural da ordem dos locks passou a incluir este fluxo.

Expectativa alterada num teste existente, com a justificação escrita no próprio
teste:
`tests/test_users.py::test_concurrent_admin_deactivation_keeps_at_least_one_active_admin`.
O admin que perde a corrida passou a ser recusado com `AuthenticationError`, por
já ter sido desativado pelo vencedor, em vez de `ConflictError` («último admin
ativo»). A invariante protegida — exatamente um sucesso e nunca zero admins
ativos — não mudou.
