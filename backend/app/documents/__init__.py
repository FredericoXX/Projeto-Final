"""Domínio documental: regras que dependem dos documentos, não da pesquisa.

Contém, para já, apenas a política de admissibilidade da evidência
(:mod:`app.documents.retrievability`). O pacote existe para que essa política
viva **fora** de ``app.retrieval``: a estratégia de recuperação depende da
política, e não o contrário.
"""
