# Geração Experimental de Respostas Fundamentadas (Fase 3, Etapa 2)

## Natureza experimental

Esta etapa adiciona geração de respostas aumentada por evidências sobre a
baseline lexical existente. **Não é uma decisão arquitetural definitiva**:
a abordagem final depende da revisão da literatura e da avaliação
experimental. O sistema **não** deve ser apresentado como livre de
alucinações — a validação desta etapa é determinística e estrutural, não
semântica.

Continuam a **não** existir: embeddings, pesquisa semântica, pesquisa
híbrida, reranking, validação por segundo LLM, confidence score final,
integração automática com conversas, persistência de respostas ou
prompts, feedback, escalonamento humano, frontend.

## Fluxo

```
pergunta autenticada
→ resolução de instituição e idioma (regras existentes)
→ normalização da pergunta (text_normalization)
→ recuperação de evidências (contrato Retriever já existente)
→ política de evidência (zero evidências → fallback, sem gerador)
→ construção de contexto limitado (answering/context.py)
→ geração controlada (contrato AnswerGenerator)
→ validação determinística (answering/validation.py)
→ resposta com fontes citadas
```

## Endpoint

`POST /api/v1/answering/ask` — autenticado; qualquer utilizador ativo de
uma instituição ativa pode perguntar. O endpoint de retrieval
(`POST /api/v1/retrieval/search`) mantém-se inalterado.

Pedido: `query` (1–1000 caracteres), `language` (opcional, validado
contra os idiomas da instituição), `top_k` (opcional; default
`ANSWERING_DEFAULT_TOP_K`, máximo `ANSWERING_MAX_TOP_K`),
`official_only` (default `true`). `institution_id`/`user_id` no payload
são rejeitados com 422.

Respostas HTTP:

- `200` com `status: "answered"` — resposta gerada e validada, com
  `sources` (apenas as evidências citadas, pela ordem das citações);
- `200` com `status: "insufficient_evidence"` — sem evidências; mensagem
  de fallback determinística, `sources: []`, gerador nunca contactado;
- `422` — payload inválido, idioma não suportado, `top_k` acima do
  máximo, pergunta que normaliza para vazio;
- `503` (`service_unavailable`) — provider não configurado (sem
  `OPENAI_API_KEY`/`OPENAI_MODEL`) quando a geração é necessária;
- `502` (`upstream_error`) — falha operacional do provider ou resposta
  gerada que falhou a validação.

## Arquitetura

- `app/answering/base.py` — contratos neutros: `AnsweringContext`,
  `ContextEvidence`, `GeneratedAnswer`, `AnswerGenerator` (Protocol) e as
  exceções tipadas (`AnswerGeneratorUnavailableError` → 503,
  `AnswerGenerationError` / `InvalidGeneratedAnswerError` → 502).
- `app/answering/context.py` — atribui IDs estáveis (E1, E2, ...) pela
  ordem do ranking, deduplica chunks e seleciona evidências completas até
  o JSON final atingir `ANSWERING_MAX_CONTEXT_CHARS` (exceção documentada:
  a melhor evidência entra sempre). Campos internos nunca são incluídos.
- `app/answering/prompts.py` — usa um system prompt completamente estático
  e normativo. Instituição, pergunta, idioma e evidências são valores de
  um único objeto criado com `json.dumps`; títulos, URLs e conteúdo não
  conseguem alterar sintaticamente a estrutura exterior.
- `app/answering/validation.py` — validação determinística: resposta não
  vazia, dentro de `ANSWERING_MAX_ANSWER_CHARS`, citações não vazias, sem
  duplicados e todas existentes no contexto. Violação → geração rejeitada
  (nunca se adivinha a fonte). Logs recebem apenas reason codes estáveis e
  contagens, nunca IDs ou texto devolvido pelo fornecedor.
- `app/answering/fallback.py` — mensagens fixas por idioma (pt/en);
  idioma sem mensagem própria usa inglês (documentado), nunca erro 500.
- `app/answering/providers/openai.py` — único módulo que conhece o SDK;
  converte qualquer falha em exceções internas seguras; nunca regista
  mensagem, traceback, chave, pergunta, contexto, headers ou resposta
  bruta do fornecedor. O cliente usa `max_retries=0` explicitamente.
- `app/answering/dependencies.py` — `get_answer_generator()` devolve o
  provider configurado sem acoplar rota/service à classe concreta,
  permitindo outro fornecedor, modelo local ou gerador determinístico.
- `app/services/answering_service.py` — orquestração fina; sem SQL, sem
  SDK, sem persistência.

## Política de evidência

- zero evidências → `insufficient_evidence` (fallback, sem gerador);
- uma ou mais evidências → geração permitida;
- resposta sem citações válidas → geração rejeitada (502);
- todas as fontes devolvidas foram citadas pelo gerador.

Sem confidence score numérico nesta etapa; o score lexical (`ts_rank_cd`)
não é tratado como probabilidade nem como medida universal de confiança.

## Configuração

Ver `.env.example`:

- `ANSWER_GENERATOR_PROVIDER` (default `openai`);
- `ANSWERING_DEFAULT_TOP_K` / `ANSWERING_MAX_TOP_K`;
- `ANSWERING_MAX_CONTEXT_CHARS` / `ANSWERING_MAX_ANSWER_CHARS`;
- `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`.

**A aplicação inicia sem `OPENAI_API_KEY`** — a ausência de configuração
só produz efeito (503) quando o endpoint de answering precisa de gerar.
Perguntas sem evidências continuam a devolver o fallback sem contactar o
provider. A chave nunca aparece em logs, exceções ou respostas. Os testes
correm sem rede e sem credenciais (o adapter é testado com um cliente
simulado; o gerador é substituído por dependency override).

## Separação entre instruções e dados

O system prompt contém apenas regras controladas pela aplicação. Todos os
dados institucionais são tratados como não confiáveis e enviados no payload
JSON da mensagem de utilizador. A serialização estruturada reduz ambiguidades
de fronteira e impede que conteúdo documental, delimitadores falsos ou JSON
embutido alterem sintaticamente a estrutura construída pela aplicação.

Esta medida não elimina prompt injection nem alucinações: o conteúdo continua
não confiável, o modelo continua sujeito a avaliação experimental e a
validação desta etapa permanece estrutural, não semântica.
