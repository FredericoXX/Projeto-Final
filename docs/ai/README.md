# Orientação de desenvolvimento

Esta diretoria contém a estrutura documental que orienta os próximos momentos
de desenvolvimento do projeto. É **neutra em relação à ferramenta**: não
configura nenhum assistente, editor ou agente, e não depende de nenhum deles.

## Ordem de leitura

1. [`01-project-constitution.md`](01-project-constitution.md) — princípios
   duradouros. Muda raramente.
2. [`02-current-state.md`](02-current-state.md) — snapshot factual do que
   existe hoje, com data e SHA. Muda a cada momento.
3. [`03-quality-gates.md`](03-quality-gates.md) — o que tem de estar verde,
   por tipo de alteração.
4. [`moments/`](moments/) — a especificação do momento em curso.

Templates, usados ao abrir e ao encerrar um momento:
[`04-moment-template.md`](04-moment-template.md) e
[`05-verification-template.md`](05-verification-template.md).

## Precedência

1. [`01-project-constitution.md`](01-project-constitution.md) — um princípio
   duradouro não é contornado por conveniência de um momento;
2. [`03-quality-gates.md`](03-quality-gates.md);
3. a especificação do momento em curso;
4. [`02-current-state.md`](02-current-state.md) — observação, não regra.

Perante uma contradição real com a constituição, o trabalho pára e a
divergência é discutida — não se resolve dentro do momento.

## Momentos

Mapa oficial:

| Momento | Tema |
| --- | --- |
| 1 | Diagnóstico do pipeline documental |
| 2 | OCR de PDFs digitalizados e tratamento de tabelas |
| 3 | Reconstrução estruturada e chunking |
| 4 | Retrieval lexical e normalização |
| 5 | Qualidade das respostas fundamentadas e das fontes |
| 6 | UX e experiência operacional |

O estado de cada um está em [`02-current-state.md`](02-current-state.md); a
especificação do momento em curso está em [`moments/`](moments/).

A documentação técnica anterior a esta estrutura usa também a designação
"Fase 1/2/3" para agrupar trabalho do backend. É numeração histórica e não
corresponde a esta tabela.

## Relação com a documentação canónica

A documentação canónica é a **fonte de verdade**.

Regra de duplicação, aplicável a todos os ficheiros desta diretoria:

> Um documento de `docs/ai/` pode **resumir** o que é preciso para orientar o
> trabalho, sempre com ligação à fonte. Não pode **copiar** — nem literalmente,
> nem por reescrita extensa do mesmo conteúdo.
>
> Teste prático: se um parágrafo pode ser substituído por uma frase e uma
> ligação sem que o momento perca o que precisa, é duplicação e deve ser
> substituído.

Isto vale igualmente entre ficheiros desta diretoria: um momento resume de
[`02-current-state.md`](02-current-state.md) o que lhe é relevante, com
ligação, em vez de o repetir.

Em caso de divergência prevalece:

- a **documentação canónica**, para descrições de desenho, regras e contratos;
- o **código executável**, para afirmações sobre comportamento atual — se um
  documento e o código discordarem sobre o que o sistema faz, o código está
  certo.

| Assunto | Fonte canónica |
| --- | --- |
| Visão geral, arranque e bootstrap institucional | [`README.md`](../../README.md) |
| Instalação detalhada e resolução de problemas | [`docs/ManualConfiguracao.md`](../ManualConfiguracao.md) |
| Esquema, migrations, retrieval e regras de segurança | [`docs/database.md`](../database.md) |
| Núcleo documental, extração, OCR e chunking | [`docs/document-core.md`](../document-core.md) |
| Respostas fundamentadas e integração conversacional | [`docs/answering.md`](../answering.md) |
| Diagnóstico do pipeline documental | [`docs/diagnostics/README.md`](../diagnostics/README.md) |
| Interface web | [`frontend/README.md`](../../frontend/README.md) |
| Configuração e limites | [`.env.example`](../../.env.example) |
| Verificações automáticas | [`.github/workflows/`](../../.github/workflows/) |

## O que não pertence aqui

- configuração de ferramentas, assistentes ou agentes;
- especificações completas copiadas de issues — usa-se a ligação;
- decisões de arquitetura formais; se vierem a existir, terão lugar próprio.

## Manutenção

- [`01-project-constitution.md`](01-project-constitution.md) — só por decisão
  explícita. Um princípio novo exige proveniência: quem decidiu e quando.
- [`02-current-state.md`](02-current-state.md) — no fim de cada momento, com
  data e SHA novos. Só factos observados nesse SHA; nenhuma regra.
- [`03-quality-gates.md`](03-quality-gates.md) — sempre que os workflows em
  [`.github/workflows/`](../../.github/workflows/) mudarem.
- [`moments/`](moments/) — um ficheiro por momento, acrescentado, nunca
  reescrito retroativamente.
- Contagens de execução só entram nestes documentos com SHA e data da
  execução que as produziu.

Convenção desta diretoria: nomes de ficheiros e diretórios em **inglês**,
conteúdo em **português europeu**, e identificadores, comandos, endpoints,
nomes de classes/funções e tecnologias preservados em **inglês**.
