# AGENTS.md

Autoridade operacional única para agentes de código neste repositório. O que
está aqui vale; não há skills instaladas, nem lockfile, nem validador. Os
documentos em `docs/agents/` são auxiliares e não podem contradizer este
ficheiro.

## Repositório autorizado

Apenas `FredericoXX/Projeto-Final`.

Nenhum comando `gh` infere o repositório a partir do `git remote`. O repositório
é sempre passado explicitamente:

```powershell
gh issue view <NUMBER> `
  -R FredericoXX/Projeto-Final `
  --comments
```

Um agente pode estar num clone diferente, num worktree, ou fora da árvore do
repositório — a inferência silenciosa escreveria no sítio errado.

## Ambiente

- Windows;
- PowerShell (continuação de linha é a crase, não a barra invertida);
- Docker Desktop;
- backend FastAPI;
- frontend React/Vite;
- PostgreSQL;
- Python virtual environment em `backend/.venv`.

## Workflow obrigatório

```
esclarecimento das decisões
→ documentação de domínio quando necessária
→ elaboração da spec
→ aprovação humana
→ publicação da spec
→ proposta de tickets
→ aprovação humana
→ publicação dos tickets
→ uma branch por ticket
→ implementação sem commit
→ revisão independente
→ correções
→ validação completa
→ autorização humana para publicar
→ commit
→ push
→ PR
→ CI
→ merge manual
```

Commit, push e criação de PR podem ser executados por um agente **apenas depois
de um pedido humano explícito**, com o escopo confirmado, a revisão independente
concluída e a validação completa aprovada. Sem essa autorização, as alterações
permanecem unstaged. O merge é sempre executado pelo utilizador.

---

## A. Esclarecimento

Antes de escrever código ou spec, chegar a um entendimento partilhado.

- Colocar as decisões ao utilizador **uma de cada vez**, com a recomendação à
  frente. Várias perguntas ao mesmo tempo são impossíveis de responder bem.
- Um facto verificável no repositório **investiga-se, não se pergunta**. Se o
  código já responde, ler o código. As decisões é que são do utilizador.
- Percorrer a árvore de decisões resolvendo as dependências entre elas, uma a
  uma.
- **Nenhuma implementação começa antes de existir entendimento partilhado.** A
  vontade de começar a construir a meio da conversa é o sinal de que ainda
  faltam decisões.

### Documentação de domínio

- `CONTEXT.md` na raiz é um **glossário e nada mais** — sem detalhes de
  implementação, sem specs. Criar apenas quando houver vocabulário real a
  registar, no momento em que o primeiro termo fica resolvido.
- ADRs em `docs/adr/` apenas para decisões **difíceis de reverter**, cuja razão
  não seria óbvia para quem lesse mais tarde, e que resultaram de um
  compromisso real entre alternativas. Se faltar um destes três, não há ADR.
- Não duplicar specs dentro de `CONTEXT.md`.
- Se algum destes ficheiros não existir, prosseguir em silêncio. Detalhes em
  [docs/agents/domain.md](docs/agents/domain.md).

## B. Especificação

- A spec completa é **apresentada primeiro no chat**, por inteiro.
- A primeira apresentação **nunca cria uma issue**.
- Aceitar correções e reapresentar a versão revista quantas vezes forem
  precisas.
- Publicar apenas depois de `aprovado` ou confirmação inequívoca equivalente.
  **"ok", silêncio, um emoji ou uma instrução não relacionada não contam.**
- Depois da aprovação, criar a issue exclusivamente em
  `FredericoXX/Projeto-Final`, com `-R` explícito e `--body-file` para o corpo:

  ```powershell
  gh issue create `
    -R FredericoXX/Projeto-Final `
    --title "<TITLE>" `
    --body-file "<BODY_FILE>"
  ```

- Aplicar `ready-for-agent` **só depois** da aprovação, nunca no mesmo passo em
  que a spec é apresentada.
- Devolver número, título e ligação da issue criada.

A spec cobre: problema, objetivos, não-objetivos, histórias de utilizador,
requisitos funcionais e de qualidade, segurança e privacidade, decisões de
implementação, decisões de teste, compatibilidade, fora de âmbito, critérios de
aceitação e questões em aberto.

A spec **não** contém caminhos de ficheiros concretos que envelhecem depressa,
blocos grandes de código, segredos, identificadores reais, nem conteúdo
institucional real.

## C. Tickets

- Apresentar **primeiro** a divisão proposta, numerada, sem publicar nada.
- Fatias **verticais**: cada ticket atravessa todas as camadas necessárias e é
  verificável isoladamente. Não fatiar por camada.
- Cada ticket cabe numa sessão de implementação.
- Declarar os **blockers** de cada ticket — quais têm de estar concluídos antes.
- Perguntar explicitamente sobre a **granularidade**: demasiado grossa,
  demasiado fina, algum ticket a juntar ou a dividir, arestas de bloqueio
  corretas.
- Publicar apenas depois de aprovação humana, em ordem de dependência
  (bloqueadores primeiro), sempre com `-R FredericoXX/Projeto-Final`.
- **Não fechar nem modificar a spec principal.**

## D. Implementação

### Antes de tocar em ficheiros

- **Exatamente um ticket aprovado por branch.** Nunca misturar tickets.
- **Nunca trabalhar diretamente na `main`.** A branch nasce da `main`
  atualizada.
- Exigir working tree limpa:

  ```powershell
  git branch --show-current
  git status --short
  git rev-parse HEAD
  ```

  Se `git status --short` devolver alguma coisa: apresentar os ficheiros
  encontrados e parar. Não descartar, não guardar de lado, não implementar por
  cima de alterações desconhecidas.

- Ler o ticket, a spec, o `CONTEXT.md` e os ADRs da área.
- Explorar o código **antes** de editar, e apresentar uma análise curta: o que
  existe hoje, onde está a costura, o que muda e o que deliberadamente não muda.

### Durante

- TDD onde exista costura apropriada — teste a falhar primeiro.
- Preferir costuras existentes a costuras novas.
- Testes focados e verificação de tipos com frequência.
- Ficar dentro do âmbito do ticket. O que estiver fora é outro ticket: registar,
  não construir.

### Antes de entregar

Validação completa, e depois rever o próprio diff à procura de âmbito a mais,
restos de depuração, segredos, identificadores reais em fixtures e conteúdo
institucional real em testes.

### Entrega

Por omissão, deixar **todas as alterações unstaged** e apresentar: branch,
ticket, ficheiros alterados, comportamento implementado, testes, validações,
**riscos e limitações**, o que não foi executado, e o estado Git.

Depois parar e esperar pela revisão independente. Quando as correções e a
validação estiverem concluídas, o utilizador pode autorizar explicitamente o
agente a fazer staging, commit, push e criar o PR.

### Publicação autorizada

Depois da autorização humana explícita, o agente pode:

- fazer staging apenas dos ficheiros pertencentes ao escopo revisto;
- criar um commit com uma mensagem que descreva esse escopo;
- fazer push da branch atual para `origin`;
- criar o PR exclusivamente em `FredericoXX/Projeto-Final`, sempre com
  `-R FredericoXX/Projeto-Final`, base e head explícitos;
- devolver o hash do commit e a ligação do PR.

Antes do staging, o agente volta a apresentar `git status --short` e confirma
que não existem alterações alheias ao escopo aprovado. Qualquer falha de teste,
alteração inesperada ou divergência da branch suspende a publicação. Criar o PR
não autoriza merge, alteração de labels, encerramento de issues nem novas
alterações de código.

---

## Comandos Git proibidos a agentes

Nenhum agente executa, em circunstância alguma:

```
git merge
gh pr merge
git rebase
git reset --hard
git clean
git stash
git checkout -- .
git restore .
```

O merge continua reservado ao utilizador. Os restantes comandos podem reescrever
histórico ou destruir trabalho que ainda não foi revisto. `git add`, `git commit`,
`git push` e `gh pr create` só são permitidos nas condições da secção
*Publicação autorizada*.

## Outras proibições

Nenhum agente:

- fecha issues automaticamente depois de implementar — **o utilizador decide
  quando uma issue está concluída**;
- altera labels finais sem pedido explícito;
- cria ou modifica labels no GitHub sem autorização;
- mistura tickets na mesma branch;
- usa dados reais em fixtures, nem identificadores reais, nem conteúdo
  institucional real;
- chama a OpenAI real durante testes — os testes usam fakes;
- opera noutro repositório que não `FredericoXX/Projeto-Final`;
- infere o repositório GitHub a partir do `git remote`;
- reprocessa documentos institucionais reais;
- executa downgrade de Alembic contra a base de dados real.

## Validação completa

Raiz:

```powershell
docker compose config --quiet
git diff --check
git status --short
git diff --stat
git diff --name-status
```

Backend, a partir de `backend/`:

```powershell
python -m pip check
ruff check .
mypy app tests scripts
python -m pytest -q
alembic upgrade head
alembic current
alembic heads
alembic check
```

Frontend, a partir de `frontend/`, mesmo quando não foi alterado:

```powershell
npm ci
npm run lint
npm run typecheck
npm run test:run
npm run build
```

## Documentação auxiliar

- [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md) — convenções do
  GitHub Issues;
- [docs/agents/triage-labels.md](docs/agents/triage-labels.md) — vocabulário de
  etiquetas;
- [docs/agents/domain.md](docs/agents/domain.md) — como consumir `CONTEXT.md` e
  os ADRs;
- [docs/agents/installation.md](docs/agents/installation.md) — porque não há
  instalação a fazer.

## Configuração local

`.claude/` é configuração da máquina de cada pessoa e permanece no `.gitignore`.
Não é versionada e não faz parte da configuração deste repositório.
