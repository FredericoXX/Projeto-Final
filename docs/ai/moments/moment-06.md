# Momento 6 — Caracterização do protótipo antes da evolução dos contratos

## Identificação

| Campo | Valor |
| --- | --- |
| Momento | 6 — Caracterização do protótipo antes da evolução dos contratos |
| Estado | **Concluído** — integrado na `main` pelo merge humano do Pull Request #35 |
| Commit base | `6e2d09cfd3348fbc9fbe842a53953a767ecd3be4` |
| Branch | `test/prototype-characterisation` |
| Commit da implementação | `c885ddf24f4f0ef27f451942d3b7ca52ab8000f1` |
| Merge na `main` | `a87cd8b14c464953a5fb3114b62e3588d39ccb3b`, a 2026-08-10 |
| Divisão em Pull Requests | um Pull Request exclusivamente de caracterização — [#35](https://github.com/FredericoXX/Projeto-Final/pull/35) |

O Pull Request #35 alterou seis ficheiros, com 1628 linhas acrescentadas e
nenhuma removida: quatro de testes (`backend/tests/moment06_support.py` e os
três `test_moment06_*`) e dois de documentação (este documento e o relatório).
Não tocou em `backend/app/`, `backend/alembic/`, `backend/scripts/`,
`frontend/`, `.github/` nem nos artefactos do Momento 5. O workflow
**Backend checks** concluiu com sucesso em `c885ddf`.

## Problema

As próximas alterações arquiteturais podem modificar contratos e políticas que
hoje estão implícitos em vários consumidores. Sem uma fotografia executável do
protótipo, não é possível distinguir preservação de comportamento de mudança
acidental.

## Objetivo

Fixar por testes o comportamento observável atual de answering, elegibilidade
documental e contratos HTTP públicos. Este momento produz conhecimento e uma
baseline técnica; não melhora nem corrige o protótipo.

## Estado atual relevante

- O snapshot do protótipo está em
  [`02-current-state.md`](../02-current-state.md).
- Answering, persistência transacional e fontes estão em
  [`answering.md`](../../answering.md).
- Retrieval lexical e integridade relacional estão em
  [`database.md`](../../database.md).
- A futura refatoração da elegibilidade está especificada na
  [issue #24](https://github.com/FredericoXX/Projeto-Final/issues/24).

## Invariantes tocadas

Este momento testa isolamento entre instituições, respostas fundamentadas,
auditabilidade histórica, neutralidade do fornecedor, separação de
responsabilidades, disciplina de âmbito e honestidade das verificações, segundo
[`01-project-constitution.md`](../01-project-constitution.md).

## Âmbito

- caracterização do fluxo de answering e da persistência conversacional;
- Fase 0 da issue #24, incluindo C1–C12, D1, D2 e proveniência N → N+1;
- forma exata do payload público de retrieval;
- estados públicos atuais dos dois endpoints de answering;
- testes de sensibilidade por mutações temporárias totalmente revertidas;
- relatório factual da baseline.

## Fora do âmbito

- corrigir defeitos ou alterar comportamento funcional;
- implementar qualquer fase de produção da issue #24;
- criar novas ontologias, resultados de retrieval, políticas, providers,
  agentes, escalação ou mecanismos semânticos;
- alterar frontend, API, base de dados, migrations, corpus, rubrica, baseline
  ou contratos históricos do Momento 5.

## Restrições

O estado final não altera `backend/app/`, `backend/alembic/`,
`backend/scripts/`, `frontend/` ou `.github/`. Só são versionados testes, este
documento e o relatório. Um comportamento inesperado é caracterizado e
registado, nunca corrigido neste momento.

## Fases

### Fase 1 — Fluxo de answering

Caracterizar resposta com evidência, short-circuit sem evidência, cinco reason
codes, persistência do turno, fallback e resolução tardia do provider.

*Critério de paragem*: os caminhos públicos e transacionais atuais estão
cobertos sem duplicar testes existentes, e testes de sensibilidade demonstram
que mudanças críticas são detetadas.

### Fase 2 — Elegibilidade documental

Caracterizar C1–C12 segundo a sua semântica real. Esta fase constitui a
**Fase 0 da issue #24**: inclui a divergência conhecida D2 e o teste de
concorrência N → N+1 da Decisão 7, sem criar as políticas futuras.

*Critério de paragem*: cada condição tem cobertura executável ou uma
justificação estrutural ligada a constraints; N deixa de ser recuperável após
N+1, mas continua a ser a fonte histórica persistida e legível.

### Fase 3 — Contratos HTTP públicos

Fixar o conjunto completo de campos de cada item de
`POST /api/v1/retrieval/search` e os estados `answered` e
`insufficient_evidence` nos dois endpoints de answering.

*Critério de paragem*: qualquer campo ou status acrescentado, removido ou
alterado parte um teste explícito.

## Critérios de aceitação

1. Nenhum ficheiro de produção fica alterado.
2. Nenhum teste existente é removido ou enfraquecido.
3. As expectativas derivam do comportamento de `6e2d09c`.
4. Answering com e sem evidência está caracterizado.
5. Os cinco reason codes e o comportamento HTTP estão fixados.
6. Persistência, fallback, atomicidade e fontes estão cobertos.
7. A aplicação arranca sem credenciais OpenAI e a ausência só se manifesta
   quando a geração é necessária.
8. C1–C12 possuem cobertura ou justificação estrutural explícita.
9. D2 é registada como divergência atual, não como requisito normativo.
10. O teste N → N+1 persiste N, recupera N+1 e mantém N legível.
11. O isolamento institucional está coberto sem alegar Row-Level Security.
12. O payload de retrieval é fixado pelo conjunto exato de propriedades.
13. Ambos os endpoints de answering expõem exatamente os dois estados atuais.
14. Testes de sensibilidade falham perante perturbações relevantes e voltam a
    passar depois da restauração.
15. Os artefactos do Momento 5 permanecem intactos e a baseline continua
    reproduzível.
16. O gate de backend é executado e reportado comando a comando.
17. O diff final contém apenas testes e documentação autorizados.

## Riscos

| Risco | Probabilidade | Mitigação |
| --- | --- | --- |
| Um teste afirmar intenção em vez de comportamento | Média | derivar expectativas do código e confirmar por execução |
| Duplicação tornar a suite frágil | Média | inventariar e referenciar cobertura existente antes de acrescentar casos |
| Uma mutação de sensibilidade permanecer no código | Baixa, impacto alto | restaurar após cada execução e confirmar ausência de diff de produção |
| Confundir C5 de retrieval com persistência | Média, risco central | teste N → N+1 e teste direto de revalidação da versão superada |

## Rollback

Todo o trabalho é aditivo e não possui migration nem estado persistido. O
rollback consiste em remover os novos testes e documentos; nenhuma reversão de
código de produção é necessária.

## Limitações

Esta caracterização não valida a correção semântica das respostas, não mede o
fornecedor real e não prova ausência de alucinações. Também não decide a nova
arquitetura: apenas fixa o protótipo imediatamente anterior a essa evolução.

## Questões em aberto

As decisões de implementação das Fases 1–4 da issue #24 permanecem para o
trabalho posterior e respetiva aprovação. Nenhuma é antecipada aqui.

## Documentação a atualizar

- criar o relatório `docs/relatorios/moment-06-prototype-characterisation.md`
  — feito, integrado pelo Pull Request #35;
- atualizar `02-current-state.md` apenas depois de integração humana, nunca a
  partir desta branch não fundida — a condição verificou-se com o merge
  `a87cd8b`, e a atualização foi feita nesse momento, não antes.

## Fecho

A Fase 0 da issue #24 fica satisfeita por este momento: os testes de
caracterização da elegibilidade da evidência, a divergência conhecida D2 e o
teste de proveniência histórica N → N+1 estão versionados na `main`. Não devem
ser reescritos quando a issue #24 avançar.

O próximo trabalho permitido é a **Fase 1 da issue #24** — o módulo novo com a
política base e as duas políticas derivadas, sem alterar consumidores. Não deve
ser iniciado automaticamente.

## Plano de verificação

Aplica-se o gate de backend de
[`03-quality-gates.md`](../03-quality-gates.md), além dos testes focados, da
reprodução da baseline do Momento 5, dos testes de sensibilidade e da inspeção
final do âmbito Git. O relatório segue
[`05-verification-template.md`](../05-verification-template.md).
