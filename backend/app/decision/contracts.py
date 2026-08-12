"""Contratos mínimos de decisão agêntica (A2.1) — vocabulário, não política.

Materializa os quatro contratos que a modelação A2.0 considerou suficientemente
estáveis para implementação provisória. É deliberadamente aborrecido: quatro
enumerações e nada mais.

Estado nesta fase: o módulo existe e é testado, mas **nenhum consumidor o usa**.
Apagá-lo não altera o comportamento do sistema. O padrão é o da Fase 1 da issue
#24 (:mod:`app.documents.retrievability`): tipos primeiro, consumidores depois.

Isto **não é uma policy**
------------------------

Não existe aqui — nem deve passar a existir nesta fase — qualquer regra que
ligue um contrato a outro. Em particular, e porque são as tentações previsíveis:

- ``PERSONAL_DATA_REQUIRED`` **não** está mapeado para ``ESCALATE``;
- ``PARTIALLY_ANSWERABLE`` **não** está mapeado para ``ANSWER``, ``CLARIFY`` nem
  ``ABSTAIN``;
- ``NOT_ANSWERABLE`` **não** está mapeado para ``ABSTAIN``.

Estas associações dependem de decisões de investigação ainda abertas com a
orientadora, e escrevê-las aqui seria fixar em código uma resposta que ainda não
foi dada. A matriz de decisão pertence a uma fase posterior.

A ordem em que estas dimensões são avaliadas também **não** está definida aqui:
a A2.0 estabeleceu precedência conceptual, não pipeline executável.

Deliberadamente fora
--------------------

- ``RequestSpecificity`` (subespecificação/ambiguidade) — a A2.0 concluiu que é
  ortogonal à answerability, mas a dimensão aguarda validação. É por isso que
  ``AMBIGUOUS`` **não** é um valor de :class:`AnswerabilityClass`;
- ``DecisionReason`` — provavelmente uma referência estruturada às dimensões
  acima, e não uma enumeração paralela; as dimensões ainda não estão fixadas;
- ``RetrievalOutcome`` — o que a recuperação encontrou é outro nível, e os seus
  valores plausíveis ainda dependem da estratégia de recuperação;
- evidência contraditória — problema em aberto, que **não** deve ser arrumado
  dentro de ``NOT_ANSWERABLE`` como decisão normativa permanente.

Os valores serializados são estáveis e explícitos: mesmo sem consumidores, um
valor implícito hoje é uma migração de dados amanhã.
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

    Outros valores candidatos foram considerados pela A2.0 e ficaram de fora
    por não mudarem nenhuma decisão nesta fase, ou por nomearem o desfecho em
    vez da propriedade do pedido.
    """

    PERSONAL_DATA_REQUIRED = "personal_data_required"


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

    ``CLARIFY`` existe aqui sem que exista ainda a dimensão que descreverá
    *quando* é apropriado; é intencional, porque a ação faz parte do espaço de
    decisão independentemente de como vier a ser justificada.

    Falhas técnicas — indisponibilidade do fornecedor, rejeição da validação
    determinística — não são desfechos desta enumeração: o sistema não escolheu
    falhar. Recuperar documentos também não é um desfecho, é uma etapa interna.
    """

    ANSWER = "answer"
    CLARIFY = "clarify"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"
