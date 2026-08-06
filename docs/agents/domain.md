# Documentação de domínio

Como consumir a documentação de domínio deste repositório. As regras de quando
criar estes ficheiros estão no [`AGENTS.md`](../../AGENTS.md), secção
*Esclarecimento*.

## Antes de explorar, ler isto

- **`CONTEXT.md`** na raiz do repositório — o glossário;
- **`docs/adr/`** — os ADRs que tocam a área onde se vai trabalhar.

Se algum destes ficheiros não existir, **prosseguir em silêncio**. Não assinalar
a ausência e não sugerir criá-los à partida: são criados de forma preguiçosa, no
momento em que um termo ou uma decisão é efectivamente resolvido.

## Estrutura de ficheiros

Repositório de contexto único, que é o caso deste:

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-....md
│   └── 0002-....md
├── backend/
└── frontend/
```

## Usar o vocabulário do glossário

Quando o resultado nomear um conceito de domínio — num título de issue, numa
proposta de refactor, numa hipótese, num nome de teste — usar o termo tal como
definido em `CONTEXT.md`. Não derivar para sinónimos que o glossário evita
explicitamente.

Se o conceito necessário ainda não estiver no glossário, isso é um sinal: ou se
está a inventar linguagem que o projecto não usa, e vale a pena reconsiderar, ou
existe uma lacuna real e o termo deve ser registado.

`CONTEXT.md` é um glossário e nada mais. Não é uma spec, não é um bloco de notas,
e não guarda decisões de implementação.

## Assinalar conflitos com ADRs

Se o resultado contradisser um ADR existente, expor isso explicitamente em vez de
o ignorar em silêncio:

> _Contradiz o ADR-0007 (…) — mas vale a pena reabrir porque…_

## Quando criar um ADR

Só quando as três condições se verificarem ao mesmo tempo:

1. **difícil de reverter** — mudar de ideias mais tarde custa mesmo alguma coisa;
2. **surpreendente sem contexto** — quem ler daqui a uns meses vai perguntar
   "porque é que fizeram assim?";
3. **resultado de um compromisso real** — havia alternativas genuínas e escolheu-se
   uma por razões concretas.

Se faltar uma delas, não há ADR.
