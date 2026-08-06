# Template — especificação de momento

Copiar para `moments/moment-NN.md` e preencher. Secções que não se apliquem são
declaradas como "não aplicável", não removidas — a ausência de uma secção é
indistinguível de esquecimento.

Manter conciso. Resumir com ligação, nunca copiar: ver a regra de duplicação em
[`README.md`](README.md#relação-com-a-documentação-canónica).

**Ao copiar, corrigir os prefixos das ligações.** Este ficheiro vive em
`docs/ai/`; a cópia vive em `docs/ai/moments/`, um nível abaixo. Por isso as
referências abaixo aparecem em texto simples — ao preencher, transformá-las em
ligações com o prefixo certo:

| Destino | A partir de `moments/` |
| --- | --- |
| Documentos de `docs/ai/` | `../01-project-constitution.md` |
| Documentos de `docs/` | `../../database.md` |
| Ficheiros da raiz do repositório | `../../../README.md` |

---

## Identificação

Momento NN — `<tema>` · estado · commit base · branch prevista · divisão em
Pull Requests (ou "não decidida").

## Problema

O que está errado, em falta ou por medir hoje. Observável, não hipotético:
sempre que possível, indicar como se manifesta.

## Objetivo

O resultado pretendido, numa ou duas frases. Se o momento produzir
conhecimento em vez de código (avaliação, medição, especificação), dizê-lo
explicitamente.

## Estado atual relevante

Só o que interessa a este momento: resumo curto com ligação à fonte. Uma frase
e uma ligação, não um parágrafo reescrito. O snapshot completo vive em
`02-current-state.md`.

## Invariantes tocadas

Que princípios de `01-project-constitution.md` este trabalho aproxima, testa ou
põe sob pressão. Se nenhum, dizê-lo.

## Âmbito

O que este momento faz. Lista curta e verificável.

## Fora do âmbito

O que este momento **não** faz, incluindo o que possa parecer adjacente e
tentador. Trabalho que exija tocar nestas áreas interrompe o momento e é
tratado separadamente — ver "Disciplina de âmbito" em
`01-project-constitution.md`.

## Restrições

Áreas do sistema que o momento não pode alterar, e o que fazer se a
necessidade surgir. Referir issues ou trabalho arquitetural relacionado por
ligação, nunca por cópia da especificação.

## Fases

Uma por bloco de trabalho, cada uma com objetivo, alterações previstas e
**critério de paragem** — a condição objetiva que permite parar num estado
consistente. Uma fase sem critério de paragem não é uma fase.

## Critérios de aceitação

Verificáveis, numerados, sem interpretação de intenção. Cada critério deve
poder ser confirmado por execução, leitura ou inspeção — não por opinião.
Evitar formulações abertas do tipo "corrigir os defeitos encontrados", que não
impõem limite de esforço.

## Riscos

Tabela: risco · probabilidade · mitigação. Identificar o risco central, se
existir um.

## Rollback

Como reverter, por fase. Se houver migrations, estado persistido ou contratos
públicos envolvidos, dizê-lo explicitamente; se não houver, dizê-lo também.

## Limitações

O que continuará por resolver depois deste momento. Declarado à partida, para
não ser lido como falha na revisão.

## Questões em aberto

Decisões que este momento **não** toma, com a indicação de quem ou o quê as
desbloqueia.

## Documentação a atualizar

Que documentos canónicos e que ficheiros de `docs/ai/` precisam de ser
atualizados no fim.

## Plano de verificação

Que gate de `03-quality-gates.md` se aplica, que testes novos são esperados, e
o que o relatório final tem de demonstrar — ver `05-verification-template.md`.
