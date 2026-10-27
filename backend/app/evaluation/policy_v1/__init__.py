"""Executor preparado da avaliação da política de decisão v1.7.

Prepara — não executa — a avaliação formal. Contém as sete condições sobre
packets arquiváveis (:mod:`.conditions`, :mod:`.packets`), as execuções
numeradas (:mod:`.runs`), as métricas e intervalos (:mod:`.metrics`,
:mod:`.statistics`), os rótulos humanos e o acordo entre anotadores
(:mod:`.labels`) e a receita de congelamento (:mod:`.freeze`). O relatório
arquivado da recolha e a agregação partilhada vivem em :mod:`.report`; a
identidade das mensagens e os juízos M7 vinculados, em :mod:`.message_ratings`;
a exportação para revisão humana, em :mod:`.message_review`; e a reanálise
offline das respostas já recolhidas, em :mod:`.rescoring`.

Os casos novos chamam-se **conjunto de avaliação da política v1** e usam
exclusivamente o corpus/suplemento **P2**. P1 e os artefactos de D4.10/D4.10a
não são lidos nem alterados por este pacote.

A avaliação formal exige corpus, adjudicação e protocolo congelados; sem eles,
o executor (``scripts/run_policy_v1_evaluation.py``) só corre ensaios de
desenvolvimento, marcados como tal. Nenhum rótulo humano é criado aqui.
"""
