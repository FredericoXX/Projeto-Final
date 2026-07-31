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

O formato de relatório **v4** acrescenta, quando o retriever ativo o suporta, o
**trace do retrieval lexical** por pergunta:

- a configuração FTS usada (`portuguese`/`english`/`simple`);
- a **contagem** de termos informativos e os marcadores estruturais
  (ordinais/intervalos) reconhecidos — nunca o texto dos termos;
- as variantes planeadas (`exact`, `reduced_and`, `canonical_relaxed_and`,
  `reduced_or`);
- o **limite global de candidatos**, a **quota** de cada variante e quantas
  linhas cada uma devolveu;
- o total devolvido antes da deduplicação, os únicos após deduplicação e os
  candidatos avaliados;
- os removidos por **motivo tipado**: `no_content_match` (nenhuma
  correspondência no conteúdo), `insufficient_coverage` (cobertura abaixo do
  mínimo) e `below_threshold` (limiar de relevância);
- o número de resultados finais;
- por resultado: a estratégia, o `ts_rank_cd` cru, o score composto e os
  componentes do ranking (cobertura, frase exata, ordem, proximidade, título,
  secção, estrutura), com uma razão resumida que inclui a condição de
  elegibilidade aplicada.

As contagens são **matematicamente consistentes** entre si e verificadas por
teste:

```
soma(quota)            <= limite global
soma(devolvidos)       == total antes da deduplicação
únicos após dedup      <= total antes da deduplicação
candidatos avaliados   == únicos após deduplicação
candidatos avaliados   == resultados finais
                          + removidos por ausência de correspondência
                          + removidos por cobertura insuficiente
                          + removidos pelo limiar
```

O corte por `top_k` **não** conta como exclusão de relevância: os resultados
finais são os candidatos que sobreviveram à elegibilidade e ao limiar. As linhas
de detalhe são limitadas para não produzir relatórios enormes, mas as contagens
abrangem sempre todos os candidatos.

A **secção do trace** contém apenas metadados e sinais de ranking: **nunca**
termos da pergunta, conteúdo de chunks, títulos fornecidos, secções, URLs,
prompts, respostas ou segredos.

Essa fronteira é explícita no código. O trace devolvido por `search_with_trace`
é uma estrutura **interna**, em memória, que conhece as formas canónicas dos
termos e serve a depuração e os testes; o relatório recebe uma projeção
**redigida** (`redact_lexical_trace`), em que os termos informativos e os termos
correspondidos passam a contagens. Como o Markdown e o JSON são ambos gerados a
partir dessa projeção, nenhum deles recebe termos derivados — verificado por
`test_lexical_trace_does_not_duplicate_question_terms`. Os ordinais e intervalos
permanecem por serem marcadores estruturais exigidos pelo relatório, não
conteúdo lexical.

**Âmbito, para evitar leitura excessiva:** o relatório como um todo **contém
deliberadamente** a pergunta e a resposta esperada de cada entrada
(`QuestionDiagnostic.question` / `expected_answer`) — são o input do próprio
operador, indispensáveis para interpretar o diagnóstico, e existem desde a v1. É
por isso que o documento abre com um aviso de confidencialidade e não deve ser
publicado sem revisão humana. A garantia acima é mais estreita e diz respeito ao
trace: ele não deriva da pergunta um segundo conjunto de termos canónicos para
arrastar até ao relatório. A proibição literal de registar a pergunta aplica-se
aos **logs**, onde nunca aparece.

O retrieval corre uma única vez por pergunta.

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
