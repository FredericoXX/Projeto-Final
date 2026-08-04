# Issue tracker: GitHub

As issues e as especificações deste repositório vivem como issues do GitHub, em
`FredericoXX/Projeto-Final`. O GitHub Issues é a fonte oficial de verdade. Usar o
CLI `gh` ou a integração GitHub disponível, mantendo todas as operações no
repositório `FredericoXX/Projeto-Final`.

## Convenções

- **Criar uma issue**: `gh issue create --title "..." --body "..."`. Usar um heredoc para corpos multi-linha.
- **Ler uma issue**: `gh issue view <number> --comments`, filtrando comentários com `jq` e obtendo também as etiquetas.
- **Listar issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`, com os filtros `--label` e `--state` adequados.
- **Comentar**: `gh issue comment <number> --body "..."`
- **Aplicar / remover etiquetas**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Fechar**: `gh issue close <number> --comment "..."`

O repositório é inferido a partir de `git remote -v` — o `gh` faz isso automaticamente dentro de um clone.

## Pull requests como superfície de triagem

**PRs como superfície de pedidos: não.** _(Mudar para `sim` se este repositório tratar PRs externos como pedidos de funcionalidade; o `/triage` lê este flag.)_

Quando estiver a `sim`, os PRs seguem as mesmas etiquetas e estados das issues, usando os equivalentes `gh pr`:

- **Ler um PR**: `gh pr view <number> --comments` e `gh pr diff <number>` para o diff.
- **Listar PRs externos para triagem**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` e manter apenas `authorAssociation` de `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR` ou `NONE` (descartar `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comentar / etiquetar / fechar**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

O GitHub partilha um espaço de numeração entre issues e PRs, por isso um `#42` isolado pode ser qualquer um — resolver com `gh pr view 42` e recorrer a `gh issue view 42` como alternativa.

## Quando uma skill diz "publicar no issue tracker"

Criar uma issue do GitHub.

## Quando uma skill diz "obter o ticket relevante"

Correr `gh issue view <number> --comments`.

## Operações de wayfinding

Usadas pelo `/wayfinder`. O **mapa** é uma issue única com issues **filhas** como tickets.

- **Mapa**: uma issue com a etiqueta `wayfinder:map`, contendo o corpo Notas / Decisões-até-agora / Nevoeiro. `gh issue create --label wayfinder:map`.
- **Ticket filho**: uma issue ligada ao mapa como sub-issue do GitHub (`gh api` no endpoint de sub-issues). Onde as sub-issues não estiverem activas, acrescentar o filho a uma lista de tarefas no corpo do mapa e pôr `Part of #<map>` no topo do corpo do filho. Etiquetas: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Uma vez reclamado, o ticket é atribuído ao programador que o conduz.
- **Bloqueio**: **dependências nativas de issues** do GitHub — a representação canónica e visível na UI. Adicionar uma aresta com `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, onde `<blocker-db-id>` é o **id numérico de base de dados** do bloqueador (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _não_ o `#number` nem o `node_id`). O GitHub reporta `issue_dependencies_summary.blocked_by` (apenas bloqueadores abertos — o gate real). Onde as dependências não estiverem disponíveis, recorrer a uma linha `Blocked by: #<n>, #<n>` no topo do corpo do filho. Um ticket está desbloqueado quando todos os bloqueadores estiverem fechados.
- **Consulta da fronteira**: listar os filhos abertos do mapa (`gh issue list --state open`, limitado às sub-issues / lista de tarefas do mapa), descartar os que tenham bloqueador aberto (`issue_dependencies_summary.blocked_by > 0`, ou uma issue aberta na linha `Blocked by`) ou responsável atribuído; ganha o primeiro pela ordem do mapa.
- **Reclamar**: `gh issue edit <n> --add-assignee @me` — a primeira escrita da sessão.
- **Resolver**: `gh issue comment <n> --body "<answer>"`, depois `gh issue close <n>`, depois acrescentar um ponteiro de contexto (gist + link) às Decisões-até-agora do mapa.
