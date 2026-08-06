# Template — relatório de verificação

Preenchido no fim de um momento, de um escopo aprovado ou de uma alteração
significativa. O destino habitual é [`docs/relatorios/`](../relatorios/).

Regras da verificação:

- **descreve o que aconteceu, não o que deveria ter acontecido**;
- um passo não executado é declarado como não executado;
- um resultado não medido não é apresentado;
- contagens só entram com a indicação de onde e quando foram medidas;
- **não se alteram ficheiros durante a auditoria** — verificar é ler e
  executar, não corrigir. Um defeito encontrado é registado como achado; a
  correção é trabalho subsequente e explicitamente autorizado.

Os comandos não são repetidos aqui: o gate aplicável está em
[`03-quality-gates.md`](03-quality-gates.md). O relatório indica **qual** gate
se aplicou e **que resultados** produziu.

Prior art:
[`docs/relatorios/correcao-final-retrieval-lexical.md`](../relatorios/correcao-final-retrieval-lexical.md).

---

## Identificação

Título · branch · data · repositório · momento, escopo ou issue de origem ·
gate aplicado (ver [`03-quality-gates.md`](03-quality-gates.md)).

## Veredicto

Um de:

| Veredicto | Significado |
| --- | --- |
| **Aprovado** | o gate está verde e não há achados que exijam alteração |
| **Aprovado com correções** | o gate está verde; existem achados menores registados, a tratar em trabalho subsequente |
| **Reprovado** | existem achados que invalidam o trabalho como está; a correção precede a integração |
| **Bloqueado** | a verificação não pôde ser concluída — pré-condição em falta, ambiente indisponível ou âmbito por decidir |

O veredicto aparece com uma frase de justificação. "Bloqueado" indica também o
que desbloqueia.

## Estado inicial

| Item | Valor |
| --- | --- |
| `BASE_SHA` | |
| Branch criada a partir de | |
| Working tree antes de começar | |
| Migration em head | |
| Commits / push / Pull Request | |

## Baseline

Resultados medidos **antes** de qualquer alteração, para que a comparação final
seja real. Uma linha por verificação do gate aplicável, com o resultado exato —
contagens, duração e warnings incluídos. Warnings pré-existentes são
identificados como tal.

| Verificação | Resultado |
| --- | --- |
| | |

Para alterações exclusivamente documentais, aplica-se o gate de documentação e
esta secção reduz-se a isso.

## Problema reproduzido

Confirmação de que cada ponto do enunciado foi verificado **a partir do
código**, não assumido. Distinguir o que foi reproduzido por execução do que
foi confirmado por leitura.

## Alterações

O que mudou e porquê. Tabela de ficheiros — alterado ou novo — com a razão de
cada um. Decisões de calibração, limiares e pesos ficam declarados aqui, com a
indicação de serem escolhas conservadoras ou resultados de medição.

## Ficheiros deliberadamente não alterados

Áreas que se poderia esperar ver alteradas e não foram, com justificação. Evita
que a revisão leia omissão intencional como esquecimento.

## Testes focados

| Comando | Passed | Failed | Skipped | Warnings | Duração |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

## Validação completa

O gate aplicável, executado no estado final, com a baseline ao lado quando
existir. Indicar também se algum passo do workflow foi alterado.

| Verificação | Resultado |
| --- | --- |
| | |

## Achados

Registo dos problemas encontrados durante a verificação, **sem os corrigir**.

| # | Severidade | Achado | Evidência | Estado |
| --- | --- | --- | --- | --- |
| | | | | resolvido / permanece / aceite |

## Limitações remanescentes

O que continua por resolver e, explicitamente, o que esta alteração **não**
garante — para que a leitura não infira garantias inexistentes.

## Comandos não executados

Passos do enunciado que não foram executados, e porquê. Se nenhum, dizê-lo.

## Confirmações Git

| Ação | Estado |
| --- | --- |
| Commit | |
| Push | |
| Pull Request | |
| Merge / rebase / squash / tag | |
| Alteração direta da `main` | |
| `git reset --hard` / `clean` / `stash` / `restore` | |
| Migration nova ou alterada | |
| Base de desenvolvimento alterada | |
| Rede usada durante os testes | |
| Documentos institucionais reais usados | |
| Ficheiros alterados fora do âmbito declarado | |
