# Documentação de domínio

Como as skills de engenharia devem consumir a documentação de domínio deste repositório.

## Antes de explorar, ler isto

- **`CONTEXT.md`** na raiz do repositório, ou
- **`CONTEXT-MAP.md`** na raiz, se existir — aponta para um `CONTEXT.md` por contexto. Ler cada um que seja relevante para o tema.
- **`docs/adr/`** — ler os ADRs que tocam a área onde se vai trabalhar.

Se algum destes ficheiros não existir, **prosseguir em silêncio**. Não assinalar a ausência; não sugerir criá-los à partida. A skill `/domain-modeling` (alcançada via `/grill-with-docs` e `/improve-codebase-architecture`) cria-os de forma preguiçosa, quando termos ou decisões forem efectivamente resolvidos.

## Estrutura de ficheiros

Repositório single-context (o caso deste repositório):

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

Quando o resultado nomear um conceito de domínio (num título de issue, numa proposta de refactor, numa hipótese, num nome de teste), usar o termo tal como definido em `CONTEXT.md`. Não derivar para sinónimos que o glossário evita explicitamente.

Se o conceito necessário ainda não estiver no glossário, isso é um sinal — ou se está a inventar linguagem que o projecto não usa (reconsiderar), ou existe uma lacuna real (registá-la para o `/domain-modeling`).

## Assinalar conflitos com ADRs

Se o resultado contradisser um ADR existente, expor isso explicitamente em vez de o ignorar em silêncio:

> _Contradiz o ADR-0007 (…) — mas vale a pena reabrir porque…_
