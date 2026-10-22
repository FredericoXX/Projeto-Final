"""Contratos mínimos de decisão agêntica — vocabulário, não política.

Materializa os contratos que a modelação A2.0 considerou suficientemente
estáveis (A2.1), mais o valor ``ADMINISTRATIVE_ACTION_REQUIRED`` que a política
de decisão v1.7 acrescenta à dimensão D2. É deliberadamente aborrecido:
enumerações e nada mais.

Consumidores atuais (verificados no código, não presumidos): o encaminhamento
humano E1 (:mod:`app.services.human_handoff_service`) usa ``DecisionOutcome``;
a extensão experimental da política v1.7 usa todos — os contratos tipados das
dimensões em :mod:`app.decision.dimensions` e as regras em
:mod:`app.decision.policy`.

Isto **não é uma policy**
------------------------

Este módulo continua sem qualquer regra que ligue um contrato a outro. As
associações da v1.7 — por exemplo, ``PERSONAL_DATA_REQUIRED`` → ``ESCALATE``
**apenas** quando existe serviço competente (R04), ``ABSTAIN`` caso contrário
(R05) — vivem em :mod:`app.decision.policy`, num modo experimental desativado
por omissão. A v1.7 é uma especificação de trabalho sujeita a calibração; fixá-la
aqui transformaria uma hipótese em vocabulário.

Nota de versão: até à v1.7, este módulo declarava que nenhuma destas
associações existia, porque as decisões estavam em aberto (A2.1, A2.2). Essa
declaração descreve o estado anterior e foi substituída por esta.

Deliberadamente fora deste módulo
---------------------------------

- a especificidade do pedido (D3), a razão estruturada da decisão e o conflito
  entre evidências (D5) — contratos compostos, não enumerações; vivem em
  :mod:`app.decision.dimensions`. ``AMBIGUOUS`` continua a **não** ser um valor
  de :class:`AnswerabilityClass`: a subespecificação é ortogonal à cobertura;
- ``RetrievalOutcome`` — o que a recuperação encontrou é outro nível, e os seus
  valores plausíveis ainda dependem da estratégia de recuperação;
- evidência contraditória **não** é arrumada dentro de ``NOT_ANSWERABLE``: tem
  dimensão própria (D5).

Os valores serializados são estáveis e explícitos: um valor implícito hoje é
uma migração de dados amanhã.
"""

from enum import StrEnum


class ScopeClass(StrEnum):
    """O tema do pedido pertence ao domínio institucional do assistente?

    ``IN_SCOPE`` — o tema do pedido pertence ao domínio institucional que o
    assistente foi concebido para apoiar.

    ``OUT_OF_SCOPE`` — o pedido não pertence ao domínio institucional definido
    para o assistente.

    **A capacidade técnica atual não define o âmbito.** Isto é a distinção
    central deste contrato, e a que é mais fácil perder: "Qual é a minha nota?"
    é um tema académico, logo ``IN_SCOPE``, mesmo que o protótipo não consiga —
    nem deva — obter a nota. O obstáculo desse pedido é uma restrição do pedido
    (:class:`RequestConstraint`), não o seu tema.

    ``OUT_OF_SCOPE`` também não significa "não há documento", "não sei
    responder" nem "preciso de um humano": cada uma dessas situações tem o seu
    próprio contrato, ou está declarada como pendente.

    O âmbito é relativo à configuração de cada instituição, e não a uma noção
    universal de "assunto académico".
    """

    IN_SCOPE = "in_scope"
    OUT_OF_SCOPE = "out_of_scope"


class RequestConstraint(StrEnum):
    """Propriedade do pedido que impede o fluxo documental normal.

    ``PERSONAL_DATA_REQUIRED`` — o pedido só pode ser satisfeito
    substantivamente mediante acesso a informação específica de uma pessoa, que
    não faz parte da documentação institucional geral disponível ao fluxo
    documental.

    O discriminante não é a presença de um possessivo. "Qual é a minha nota?"
    tem a restrição, porque o valor pedido vive num registo individual; "Como
    posso consultar as minhas notas?" pode não a ter, porque o procedimento
    está documentado.

    **Não existe ``NONE``, e a omissão é deliberada.** Uma restrição é uma
    propriedade que pode ocorrer zero ou mais vezes; a ausência de restrições é
    a coleção vazia — ``frozenset()`` — e não um membro artificial dentro do
    próprio conjunto de restrições.

    ``ADMINISTRATIVE_ACTION_REQUIRED`` — o pedido só fica satisfeito com a
    execução de um ato administrativo (inscrever, anular, emitir, alterar),
    que o assistente não pratica. "Inscreva-me" tem a restrição; "Como faço a
    inscrição?" não a tem, porque pede informação sobre o procedimento.
    Acrescentado pela política v1.7 (D2); a A2.0 tinha-o adiado.

    Outros valores candidatos foram considerados pela A2.0 e ficaram de fora
    por não mudarem nenhuma decisão, ou por nomearem o desfecho em vez da
    propriedade do pedido.
    """

    PERSONAL_DATA_REQUIRED = "personal_data_required"
    ADMINISTRATIVE_ACTION_REQUIRED = "administrative_action_required"


class AnswerabilityClass(StrEnum):
    """Até que ponto a evidência disponível suporta o pedido.

    ``FULLY_ANSWERABLE`` — a evidência/contexto disponível suporta
    adequadamente todas as partes substantivas do pedido que devem ser
    respondidas.

    ``PARTIALLY_ANSWERABLE`` — a evidência/contexto suporta apenas parte
    substantiva do pedido.

    ``NOT_ANSWERABLE`` — a evidência/contexto disponível não permite produzir
    uma resposta substantiva adequadamente fundamentada.

    O nome ``NOT_ANSWERABLE`` é escolhido contra ``INSUFFICIENT_EVIDENCE``, que
    já é um estado público observável do answering e é também um valor plausível
    de um futuro ``RetrievalOutcome``. Três conceitos distintos, em três níveis
    distintos, com o mesmo nome, seriam indistinguíveis em discussão e em
    anotação.

    ``AMBIGUOUS`` **não** pertence a esta enumeração: a subespecificação é uma
    propriedade do pedido, não da cobertura da evidência, e vive numa dimensão
    própria ainda não estabilizada.

    Esta classe descreve uma relação entre pedido e evidência. **Não** é o
    resultado da recuperação: um conjunto de evidências não vazio pode ser
    ``NOT_ANSWERABLE``, e a ausência de resultados tem causas que esta dimensão
    não distingue.
    """

    FULLY_ANSWERABLE = "fully_answerable"
    PARTIALLY_ANSWERABLE = "partially_answerable"
    NOT_ANSWERABLE = "not_answerable"


class DecisionOutcome(StrEnum):
    """A ação que o assistente executa perante o pedido.

    ``ANSWER`` — produzir uma resposta substantiva ao utilizador.

    ``CLARIFY`` — solicitar informação adicional ao utilizador para resolver
    uma incerteza/subespecificação relevante.

    ``ABSTAIN`` — não produzir uma resposta substantiva porque o sistema não
    deve responder nas condições observadas.

    ``ESCALATE`` — encaminhar explicitamente o caso para intervenção humana.

    ``ABSTAIN`` e ``ESCALATE`` não são sinónimos: o primeiro termina o fluxo, o
    segundo declara que o caso continua com uma pessoa.

    *Quando* ``CLARIFY`` é apropriado é decidido pela dimensão D3 e pela regra
    R06 da política v1.7, fora deste módulo.

    Falhas técnicas — indisponibilidade do fornecedor, rejeição da validação
    determinística — não são desfechos desta enumeração: o sistema não escolheu
    falhar. Recuperar documentos também não é um desfecho, é uma etapa interna.
    """

    ANSWER = "answer"
    CLARIFY = "clarify"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"
