# Instalação

**Não há instalação a fazer.** Basta clonar o repositório.

A autoridade operacional é o [`AGENTS.md`](../../AGENTS.md) na raiz: está
versionado, é lido por qualquer agente que trabalhe aqui, e contém o workflow
completo, os gates de aprovação humana, as restrições Git e as regras de
implementação.

Não existe nada a instalar por máquina, nada a sincronizar, nenhum ficheiro de
bloqueio a manter e nenhum validador a correr no CI. Um agente lê o `AGENTS.md`
e segue-o.

## Documentação auxiliar

Esta pasta detalha o que o `AGENTS.md` resume, e nunca o contradiz:

| Ficheiro | Conteúdo |
| --- | --- |
| [issue-tracker.md](issue-tracker.md) | Convenções do GitHub Issues em `FredericoXX/Projeto-Final` |
| [triage-labels.md](triage-labels.md) | As cinco etiquetas de triagem |
| [domain.md](domain.md) | Como consumir `CONTEXT.md` e os ADRs |

Se algum destes documentos divergir do `AGENTS.md`, vale o `AGENTS.md` e o
documento é corrigido.

## Configuração local

`.claude/` é configuração da máquina de cada pessoa — preferências do Claude
Code e o que cada um tenha configurado localmente. Está no `.gitignore` e não é
versionada. Nada em `.claude/` faz parte da configuração deste repositório, e
nenhum agente deve depender do que lá esteja.
