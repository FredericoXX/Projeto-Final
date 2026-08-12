"""Domínio da decisão: o que o assistente faz perante um pedido.

Contém, para já, apenas os contratos provisórios da A2.1
(:mod:`app.decision.contracts`) — vocabulário, sem política e sem consumidores.

O pacote existe para que esta decisão viva **fora** de ``app.answering`` e de
``app.retrieval``: a geração de respostas e a recuperação de evidências são
etapas de que a decisão depende, e não o contrário.

Não é ``app.agent``: a arquitetura do agente não está decidida, e nada aqui
pressupõe orquestrador, máquina de estados ou grafo.
"""
