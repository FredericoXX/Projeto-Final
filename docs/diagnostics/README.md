# Diagnóstico do pipeline documental

Esta diretoria pertence à ferramenta interna, removível e exclusivamente
de diagnóstico `python -m scripts.diagnose_document_pipeline` (executada
a partir de `backend/`). A ferramenta observa dados já persistidos —
texto extraído, chunks e resultados do retrieval existente — numa
transação PostgreSQL read-only e produz um relatório técnico. Não corrige
nada, não chama o answering pipeline nem a OpenAI.

O formato de relatório v2 inclui os metadados estruturais persistidos
(`page_number`, `section_title`, `structure_type` e `chunking_strategy`),
contagens de chunks por página/tipo, `table_row`, fragments de fallback,
chunks que atravessam páginas e linhas de tabela divididas. Para cada pergunta,
continua a indicar factos no mesmo chunk/contexto fragmentado e acrescenta se
todos os factos esperados aparecem na mesma `table_row`.

O formato de relatório **v3** (Momento 4) acrescenta, quando o retriever ativo
o suporta, o **trace do retrieval lexical** por pergunta: a configuração FTS
usada (`portuguese`/`english`/`simple`), os termos informativos e ordinais/
intervalos canónicos da pergunta, as variantes planeadas e o número de
candidatos por variante, o `candidate_limit`, os candidatos únicos, os removidos
pelo limiar, e — por resultado — a estratégia, o `ts_rank_cd` cru, o score
composto e os componentes do ranking (cobertura, frase exata, proximidade,
título, secção, estrutura) com uma razão resumida. O trace contém apenas
metadados e sinais de ranking: **nunca** conteúdo de chunks, títulos fornecidos,
secções, URLs ou segredos. O retrieval corre uma única vez por pergunta.

`PAGE_SEPARATOR = "\f"` é tratado como fronteira válida, não como conteúdo
perdido entre chunks. O diagnóstico apenas observa o texto e os metadados já
guardados: não reabre PDF, não executa OCR/rebuild, não interpreta a tabela e
não altera retrieval, ranking, answering ou a base.

## Estrutura

- `examples/` — ficheiros de perguntas **sanitizados** e versionáveis
  (sem IDs reais, storage paths, tokens, dados pessoais ou excertos
  extensos). O exemplo `calendar-2026-2027.example.json` contém as
  perguntas e factos esperados do calendário académico; os valores
  esperados **necessitam de validação humana contra o PDF real** antes de
  serem tratados como verdade de referência.
- `generated/` — relatórios reais produzidos pela ferramenta. Esta
  diretoria é **ignorada pelo Git** (ver `.gitignore` na raiz).

## Como gerar relatórios

A partir de `backend/` (ver a secção "Diagnóstico do pipeline documental"
em `docs/document-core.md` para a lista completa de argumentos e códigos
de saída):

```powershell
python -m scripts.diagnose_document_pipeline --institution-id "<INSTITUTION_ID>" --filename "<FICHEIRO>" --questions-file "../docs/diagnostics/examples/calendar-2026-2027.example.json" --output "../docs/diagnostics/generated/relatorio.md" --format markdown
```

## Privacidade — leia antes de partilhar

- Os relatórios reais contêm **excertos de documentos institucionais**,
  títulos e identificadores técnicos reais.
- **Não devem ser publicados nem partilhados sem revisão humana.**
- IDs reais e excertos **não devem ser enviados para o GitHub**: a
  diretoria `generated/` está ignorada precisamente para impedir commits
  acidentais; não contornar essa regra com `git add -f`.
- Apenas ficheiros de exemplo sanitizados (como os de `examples/`) podem
  ser versionados.
