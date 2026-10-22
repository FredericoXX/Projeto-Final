# Política de decisão v1.7 — modo experimental

> **Experimental, desativado por omissão, não avaliado.** Implementa em
> desenvolvimento a *Política de decisão de resposta e protocolo de rotulagem
> v1.7* (1 de outubro de 2026), uma especificação de trabalho sujeita a
> calibração. Não declara aprovação, protocolo congelado, originalidade
> demonstrada nem resultados de avaliação. Os princípios de desenho são
> **candidatos**; os mecanismos conhecidos (recuperação, validação de citações,
> rechecagem transacional) são **adotados**.

Relatório de integração, com a matriz de conformidade:
[`relatorios/policy-v1-7-integration.md`](relatorios/policy-v1-7-integration.md).

## 1. Dois fluxos, uma autoridade por fluxo

| Fluxo | Endpoint | Quem escolhe a ação |
| --- | --- | --- |
| **B0** (atual) | `POST /api/v1/conversations/{id}/ask` | o answering: `answered` → ANSWER, `insufficient_evidence` → ABSTAIN |
| **Política v1.7** | `POST /api/v1/conversations/{id}/decide` | `app.decision.policy.decide` (R01–R12) |

O B0 não foi alterado no seu contrato. Mudou apenas:

- a data de referência passou a ser única por pedido;
- o papel do requerente entra na recuperação (autorização C13, secção 4).

A estratégia de recuperação (o retriever injetado) coexiste com a política sem
a substituir.

## 2. Ativar em desenvolvimento

| Variável | Omissão | Efeito |
| --- | --- | --- |
| `DECISION_POLICY_MODE` | `disabled` | `experimental` ativa `/decide`; com `disabled` responde 503 |
| `DECISION_ESTIMATOR_PROVIDER` | `openai` | estimador real das dimensões; qualquer outro valor → 503 |
| `DECISION_ESTIMATOR_MODEL` | — | modelo do estimador; sem valor usa `OPENAI_MODEL` |
| `DECISION_ESTIMATOR_TIMEOUT_SECONDS` | `30` | timeout fixo por chamada |
| `DECISION_ESTIMATOR_MAX_ATTEMPTS` | `1` | tentativas fixas (1–3) |
| `DECISION_RETRIEVAL_TOP_K` | `5` | passagens por leitura, com o teto de `ANSWERING_MAX_TOP_K` |

A instituição precisa ainda de uma configuração de decisão, publicada pelo
admin institucional:

```http
PUT /api/v1/decision/catalog
{
  "scope_description": "Atendimento académico: matrículas, inscrições, ...",
  "topics": [{"code": "enrolment", "label": "Matrículas"}],
  "services": [
    {"service_id": "academic-office", "name": "Serviços Académicos",
     "email": "academicos@example.org", "topics": ["enrolment"]}
  ]
}
```

- Cada publicação cria uma versão nova e imutável. A anterior fica no
  histórico (`GET /api/v1/decision/catalog/versions`).
- Cada tema tem no máximo um serviço competente.
- Os contactos são validados como os do destino E1.
- O destino genérico da instituição (`human_support_*`) **não** entra no
  catálogo e não prova competência para nenhum tema.

A interface mostra a opção "Modo experimental" na conversa só quando
`GET /api/v1/decision/status` indica o modo ativo e o catálogo configurado.

## 3. Dimensões, ordem de recolha e regras

Contratos em [`app/decision/dimensions.py`](../backend/app/decision/dimensions.py).
Os valores serializados de [`app/decision/contracts.py`](../backend/app/decision/contracts.py)
são reutilizados; a v1.7 acrescentou `administrative_action_required` a D2.

| Dimensão | O que é | Origem |
| --- | --- | --- |
| D0 | evidência admissível: `RetrievalEligibility` (C1–C11) + C13 | backend, na recuperação |
| D1 | âmbito, contra a descrição configurada da instituição | estimador |
| D2 | restrições (conjunto, vazio sem restrições) | estimador |
| D3 | especificidade, leituras, materialidade, distinguibilidade, cobertura admissível por leitura | estimador + D0 |
| D4 | suporte completo por item; suficiência derivada; parcial enganosa | estimador + D0 |
| D5 | conflito sobre o mesmo item e nas mesmas condições | estimador + D0 |
| D6 | serviço competente do catálogo, por tema | backend |

**Ordem de recolha** (não a precedência):

1. Análise do pedido.
2. D1 fora de âmbito termina **sem recuperação**.
3. D2 termina a escolha. Só se recupera, com limite, o procedimento documentado
   que o pedido também pergunte.
4. Caso contrário, há recuperação por leitura quando a ambiguidade é material,
   e única nos restantes casos. D0 aplica-se dentro da recuperação, antes de
   qualquer cobertura, suporte ou conflito.
5. Diagnóstico temporal.
6. Avaliação sobre passagens admissíveis.
7. Política, depois composição.

`PolicyInput` recusa qualquer leitura, item ou conflito que cite evidência fora
de D0.

**Regras**: tabela no topo de [`app/decision/policy.py`](../backend/app/decision/policy.py).
A primeira regra terminal satisfeita ganha. O ato administrativo precede o dado
pessoal. Não existe uma quinta ação para resposta parcial: R10 é ANSWER com
lacuna declarada.

Hipótese de desenho revisável (F15): uma leitura material sem cobertura
admissível impede CLARIFY, e o caso segue para R11/R12.

## 4. Autorização documental por papel (C13)

`documents.access_roles` restringe os papéis que um documento pode
fundamentar. A lista vazia significa sem restrição; é o valor de todos os
documentos anteriores à migração `a8c4e2f6b1d9`.

É um mecanismo separado do isolamento institucional (C1–C3) e aplica-se em
quatro pontos:

- **contexto do modelo**: na recuperação, para B0 e para a política;
- **pesquisa de evidência**: em `/retrieval/search`;
- **persistência**: em `CitationPersistenceEligibility`, com o papel relido sob
  lock;
- **leitura das fontes**: uma fonte de documento entretanto vedado é omitida,
  sem alterar o snapshot.

Garantias:

- `documents.manage` governa a gestão, não a fundamentação.
- O papel vem sempre da identidade autenticada e revalidada.
- Papéis simulados existem só no executor offline.
- Nenhuma ablação desliga C13 ou o isolamento.

`requester_role=None`, usado por consumidores offline como snapshots, scripts de
avaliação de P1 e diagnóstico, só admite documentos sem restrição.

Versão da semântica: `DOCUMENT_ACCESS_POLICY_VERSION = "document_role_access_v1"`.

## 5. Ações e mensagens

**ANSWER**
- É a única ação que chama o gerador substantivo, com o contexto restrito à
  evidência dos itens respondidos.
- A validação exige que cada item respondido cite pelo menos uma das suas
  evidências; caso contrário é falha técnica, 502.
- Em R10, a mensagem acrescenta deterministicamente os itens não suportados.

**CLARIFY**
- Pergunta fechada com 2 ou 3 leituras, sem resposta substantiva.
- A continuação (`clarification: {message_id, reading_id}`) inicia uma decisão
  nova a partir do pedido original e da leitura escolhida, e revalida toda a
  admissibilidade.
- Não há memória conversacional aberta.

**ABSTAIN e ESCALATE**
- Usam modelos versionados (`decision_messages_v1`).
- Em conflito, citam as duas orientações divergentes sem escolher uma.
- Em R02/R04, o procedimento só entra como excerto verbatim e citado de
  evidência admissível.
- ESCALATE indica serviço, contacto, motivo e o resumo a apresentar. É E1:
  uma **recomendação**, que afirma expressamente que o pedido não foi enviado.
- A origem fica registada como `decision_trigger="automatic"` e
  `handoff_trigger="policy_decision"`, distinta do encaminhamento pedido pelo
  utilizador.

**Diagnóstico temporal**
- Documentos relevantes, autorizados e excluídos apenas por validade.
- O aviso só aparece quando **apenas** foi encontrada informação fora de vigor:
  há documentos excluídos por validade e nenhuma evidência vigente suporta um
  item, cobre uma leitura ou entra num conflito
  (`only_outside_validity_found`).
- Muda a mensagem, nunca a ação.
- Só nomeia o título; o conteúdo caducado não é usado.
- Sem resultados, não se afirma desatualização.
- "Não encontrei" é sempre relativo aos documentos consultados.

## 6. Data de referência e vigência

- **Em operação**: uma única data UTC, estabelecida no início do pedido e usada
  na recuperação, no diagnóstico, na política, na revalidação das fontes, nos
  metadados e no registo.
- **Em avaliação**: a data fixada em cada caso, nunca o relógio do servidor.
- A vigência normativa pertence ao **documento lógico** (`documents.valid_from`
  e `valid_until`). A última versão processada (C5) é outra coisa e não herda
  validade.
- Calendários coexistentes representam-se como documentos lógicos distintos,
  cada um com o seu intervalo.
- Os limites são inclusivos na data de referência, e os testes cobrem-nos.

## 7. Persistência, auditoria e falhas

- **Mensagens**: um turno grava a mensagem do utilizador e a do assistente,
  sob os mesmos locks do B0 (instituição → utilizador → conversa).
- **Fontes citadas**: são revalidadas.
- **Metadados públicos** (`extra_metadata`): ação, regra, versões, opções,
  destino, itens em lacuna e aviso temporal.
- **Alteração de papel**: se o papel mudar durante a decisão, o turno é
  invalidado com 409.
- **Tudo aquilo em que a decisão assentou** é relido sob `FOR SHARE` com o
  papel persistido: as evidências admissíveis, citadas ou não, e os documentos
  do diagnóstico temporal. Um documento entretanto eliminado ou vedado ao papel
  invalida o turno (409).
- **`decision_records`**: registo interno protegido, sem endpoint de leitura.
  Guarda as entradas validadas (D0–D6 e a origem de cada estimativa), a razão
  estruturada, as versões, a configuração da recuperação, os identificadores e
  hashes das evidências admissíveis (sem conteúdo), as tentativas, a duração e
  a utilização do fornecedor, separada por estimador e gerador.
- **Raciocínio do modelo**: nunca é guardado.
- **Custo monetário**: não é calculado.
- **Falhas técnicas** (timeout, indisponibilidade, saída inválida, fontes
  alteradas) devolvem o erro próprio (502, 503 ou 409), não gravam mensagens e
  ficam com `status='technical_failure'`. **Não são ABSTAIN.** Quando o gerador
  chegou a ser chamado, a falha regista a tentativa e os tokens conhecidos;
  quando não chegou, `generator` fica `null`.
- **Replay**: `python -m scripts.replay_decision_record` refaz a decisão a
  partir das entradas arquivadas.

## 8. Avaliação — preparada, não executada

Pacote [`app/evaluation/policy_v1/`](../backend/app/evaluation/policy_v1/) e
[`evaluation/policy-v1/README.md`](evaluation/policy-v1/README.md):

- as condições B0, B1-plena, B1-composição, P-oráculo, P-e2e, A-sem-filtro e
  A-sem-diagnóstico, sobre packets arquiváveis;
- três execuções numeradas;
- as métricas, com os identificadores M1–M9 versionados em `config.METRIC_IDS`;
- a atribuição de erros por replay contrafactual, com inspeção humana pendente;
- snapshots por papel do caso;
- a ferramenta de rótulos;
- a receita de congelamento.

A avaliação formal exige corpus P2, adjudicação e protocolo congelados, que não
existem.

## 9. Limites conhecidos

- O documento v1.7 não está no repositório. A numeração M3–M9 e os códigos
  F02, F03, F14, F15 e DP1–DP6 não puderam ser verificados (ver o relatório).
- Os estimadores reais nunca foram executados neste repositório: os testes usam
  doubles determinísticos. A qualidade das estimativas é desconhecida.
- Os identificadores M3–M8 são **provisórios** (ordem da enumeração no
  prompt) e M9 está por atribuir. A qualidade da mensagem (M7) usa um único
  juízo humano "aceitável/não aceitável", porque o prompt não define critérios.
- O diagnóstico de pipeline documental avalia C13 sem papel. Um documento
  restrito aparece como não recuperável "sem papel".
- F14, autorização por papel na avaliação, só pode ser declarado testado com um
  corpus sintético identificado. Aqui há enforcement e testes técnicos, não
  avaliação.
