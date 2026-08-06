# Quality gates

O que tem de estar verde para uma alteração ser considerada concluída. A fonte
operacional autoritativa são os workflows em
[`.github/workflows/`](../../.github/workflows/); este documento declara-os e
torna-os copiáveis. Quando divergirem, o workflow manda.

Aplica-se o gate correspondente ao **tipo de alteração**.

| Tipo de alteração | Gate |
| --- | --- |
| Apenas Markdown | [Documentação](#gate--documentação) |
| Código, testes ou scripts do backend | [Backend](#gate--backend) |
| `frontend/**` | [Frontend](#gate--frontend) |
| Migration ou modelo de dados | [Backend](#gate--backend) + [Migration](#gate--migration) |
| Transversal (backend + frontend, ou infraestrutura) | todos os aplicáveis + [Infraestrutura](#gate--infraestrutura) |

## Pré-condições (backend)

- PostgreSQL a correr: `docker compose up -d` a partir da raiz;
- virtual environment ativo em `backend/`;
- `.env` presente e coerente com [`.env.example`](../../.env.example);
- migrations aplicadas.

Instalação detalhada e resolução de problemas:
[`docs/ManualConfiguracao.md`](../ManualConfiguracao.md).

## Gate — backend

A partir da raiz:

```powershell
docker compose config --quiet
```

A partir de `backend/`, com o virtual environment ativo:

```powershell
python -m pip check
python -c "from app.main import app; print(app.title)"
ruff check .
mypy app tests scripts
python -m pytest -q
alembic upgrade head
alembic current
alembic heads
alembic check
```

Notas:

- `docker compose config --quiet` e o smoke test de importação constam do
  workflow do backend e por isso pertencem ao gate local.
- **`mypy app tests scripts`** é o âmbito correto, por ser o que a CI executa.
  Documentação anterior a esta estrutura menciona `mypy app tests`; não é a
  referência operacional e não foi alterada.
- `ruff format` **não** é gate obrigatório enquanto não fizer parte da CI. Pode
  ser usado como conveniência, nunca como critério de conclusão.
- Os testes usam uma base de dados dedicada e nunca escrevem na base de
  desenvolvimento nem no `storage/` de desenvolvimento.
- Os testes correm **sem rede e sem credenciais**.

## Gate — frontend

A partir de `frontend/`:

```bash
npm ci
npm run lint
npm run typecheck
npm run test:run
npm run build
```

Os testes usam MSW; não exigem backend nem chave de API.

## Gate — migration

Além do gate de backend, com a base de dados a correr:

```powershell
alembic upgrade head
alembic current
alembic heads
alembic check
```

E, por inspeção:

- `alembic heads` mostra uma única head;
- a migration é reversível, ou a irreversibilidade está declarada;
- não há backfill implícito de dados existentes sem decisão explícita;
- o efeito no esquema está descrito em [`docs/database.md`](../database.md).

## Gate — infraestrutura

A partir da raiz, quando o `docker-compose.yml` ou as variáveis `POSTGRES_*`
mudarem:

```powershell
docker compose config --quiet
```

Valida sintaxe e interpolação. A CI não inicia o Compose.

## Gate — documentação

Para alterações que só tocam em ficheiros Markdown:

```powershell
git diff --check
git status --short
git diff --stat
git diff --name-status
git diff --name-only
```

E, por inspeção:

- todos os ficheiros alterados pertencem ao âmbito declarado da tarefa;
- as ligações relativas resolvem a partir da localização do ficheiro;
- nenhum segredo, identificador institucional real, caminho local de máquina ou
  excerto documental real foi introduzido;
- nenhuma contagem de execução é apresentada sem SHA e data;
- afirmações sobre comportamento do sistema foram confirmadas contra o código,
  não inferidas de documentação anterior.

**Não é necessário executar as suites de backend ou frontend** para uma
alteração exclusivamente documental.

## O que a CI executa

[`backend-checks.yml`](../../.github/workflows/backend-checks.yml) — em cada
Pull Request e em push para `main`, **sem filtro de paths**: validação do
Docker Compose, instalação do runtime de OCR (Tesseract com dados pt/en),
Python 3.12, instalação de dependências, verificação de que a aplicação
importa, `ruff check .`, `mypy app tests scripts`, `alembic upgrade head`,
`alembic check` e `pytest -q`.

[`frontend-checks.yml`](../../.github/workflows/frontend-checks.yml) — apenas
quando `frontend/**` ou o próprio workflow mudam: Node.js 22, `npm ci`, lint,
typecheck, `test:run` e build.

Consequência prática: um Pull Request exclusivamente documental continua a
disparar as verificações do backend na CI, mesmo quando o gate local aplicável
é o de documentação.

Diferenças conhecidas entre local e CI: a CI usa um service container em vez do
Docker Compose, instala sempre o Tesseract, define as suas próprias variáveis
de ambiente, e não executa `python -m pip check`, `alembic current` nem
`alembic heads`.

## Definição de concluído

1. O gate aplicável está verde, executado no estado final da branch.
2. Nenhum teste existente foi removido, enfraquecido ou reescrito para esconder
   uma regressão. Acrescentar casos é permitido.
3. Nenhum segredo, documento institucional real ou dado pessoal entrou no
   repositório.
4. A documentação afetada foi atualizada, incluindo
   [`02-current-state.md`](02-current-state.md) quando o momento termina.
5. Os resultados são reportados como foram obtidos; um passo não executado é
   declarado como não executado.

## Proibições

- Commit direto na `main`.
- Commit, push ou Pull Request sem pedido explícito.
- Alterar expectativas de testes existentes para obter verde.
- Registar contagens de testes sem SHA e data da execução.
- Usar documentos institucionais reais, rede ou credenciais nos testes.
- Forçar a inclusão de relatórios de `docs/diagnostics/generated/` no Git.
