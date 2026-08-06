# Issue tracker: GitHub

As issues e as especificações deste repositório vivem como issues do GitHub em
**`FredericoXX/Projeto-Final`**. O GitHub Issues é a fonte oficial de verdade.

Este documento detalha as convenções de comando. As regras de quando publicar e
quem aprova estão no [`AGENTS.md`](../../AGENTS.md), que prevalece em caso de
divergência.

## Repositório explícito

Todos os comandos indicam o repositório com `-R FredericoXX/Projeto-Final`. O
repositório **nunca** é inferido a partir de `git remote -v`: um agente pode
estar num clone diferente, num worktree, ou fora da árvore do repositório, e uma
inferência silenciosa escreveria no sítio errado.

Quando existir uma integração GitHub disponível no ambiente do agente, preferi-la
ao CLI — continua a valer a mesma regra do repositório explícito. O CLI `gh` é a
alternativa documentada aqui.

## Ambiente

Os exemplos são PowerShell, o shell deste projeto. A continuação de linha é a
crase (`` ` ``). **Não** usar heredoc de Bash: para corpos multi-linha, escrever
o corpo num ficheiro e passar `--body-file`.

## Convenções

**Listar issues**

```powershell
gh issue list -R FredericoXX/Projeto-Final
```

```powershell
gh issue list `
  -R FredericoXX/Projeto-Final `
  --state open `
  --label ready-for-agent `
  --json number,title,labels
```

**Ler uma issue**

```powershell
gh issue view <NUMBER> `
  -R FredericoXX/Projeto-Final `
  --comments
```

**Criar uma issue** — sempre com `--body-file`, nunca com um corpo multi-linha
embutido no comando:

```powershell
gh issue create `
  -R FredericoXX/Projeto-Final `
  --title "<TITLE>" `
  --body-file "<BODY_FILE>"
```

**Comentar**

```powershell
gh issue comment <NUMBER> `
  -R FredericoXX/Projeto-Final `
  --body-file "<BODY_FILE>"
```

**Aplicar ou remover etiquetas**

```powershell
gh issue edit <NUMBER> `
  -R FredericoXX/Projeto-Final `
  --add-label "ready-for-agent"
```

```powershell
gh issue edit <NUMBER> `
  -R FredericoXX/Projeto-Final `
  --remove-label "needs-triage"
```

**Fechar** — apenas quando o utilizador o pedir (ver "Quem fecha" abaixo):

```powershell
gh issue close <NUMBER> `
  -R FredericoXX/Projeto-Final `
  --comment "<COMMENT>"
```

## Aprovação antes da criação

Nem specs nem tickets são criados sem aprovação humana explícita.

- Uma spec só é publicada depois de o utilizador a ter visto e respondido
  `aprovado` ou equivalente inequívoco.
- Os tickets só são publicados depois de o utilizador ter aprovado a divisão
  proposta, e em ordem de dependência: os bloqueadores primeiro.

"Ok", silêncio, um emoji ou uma instrução não relacionada **não** são aprovação.

A etiqueta `ready-for-agent` é aplicada apenas depois da aprovação, nunca no
mesmo passo em que o conteúdo é apresentado.

## Quem fecha

Nenhum agente fecha uma issue automaticamente depois de implementar. Uma
implementação entregue fica à espera de revisão independente e, depois, da
publicação autorizada e do merge manual. **O utilizador decide quando uma issue
está concluída** e é ele que a fecha, diretamente ou pedindo-o explicitamente.

Do mesmo modo, nenhum agente fecha nem modifica a issue-mãe de uma spec ao
publicar os seus tickets.

## Publicar no issue tracker

Criar uma issue do GitHub em `FredericoXX/Projeto-Final`, com `--body-file`,
depois da aprovação humana.

## Obter o ticket relevante

```powershell
gh issue view <NUMBER> `
  -R FredericoXX/Projeto-Final `
  --comments
```

## Pull requests como superfície de triagem

**PRs como superfície de pedidos: não.**

Os PRs deste repositório são criados no fim do workflow pelo utilizador ou por
um agente com autorização humana explícita, nas condições do `AGENTS.md`, e não
entram na fila de triagem. O merge permanece reservado ao utilizador.
