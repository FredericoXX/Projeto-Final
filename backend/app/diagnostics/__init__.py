"""Ferramentas internas de diagnóstico, fora do runtime da aplicação.

Este pacote nunca é importado por app.main, por routers ou por services:
é usado apenas por scripts de linha de comandos e pelos testes. Importar
este pacote não pode ter efeitos secundários.
"""
