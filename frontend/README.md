# Assistente Institucional — Frontend

Interface web mínima e responsiva para o protótipo do Assistente Institucional.
Ela demonstra o fluxo completo sem Swagger nem pedidos manuais: iniciar sessão,
manter uma conversa fundamentada com fontes e, como administrador, gerir
documentos e as respetivas versões.

A interface é **neutra em relação à instituição**: o nome da aplicação vem de
`VITE_APP_NAME` e nunca fica fixo no código. Também é multilíngue (PT/EN),
independentemente do idioma da própria conversa.

## Tecnologias

React 18 + TypeScript (strict), Vite, React Router, TanStack Query, Vitest,
React Testing Library, MSW e ESLint. Não há framework de interface nem
biblioteca de estado além do TanStack Query; a camada HTTP usa `fetch` nativo.

## Estrutura

```
src/
  api/         cliente HTTP tipado, tratamento de erros, armazenamento do token e módulos de endpoints
  app/         aplicação, roteador e cliente de consultas
  auth/        provedor de autenticação e proteções de rotas
  components/  layout, feedback e componentes visuais comuns
  features/    páginas de autenticação, conversas e documentos, com hooks de consulta
  i18n/        dicionários PT/EN, provedor e hook
  lib/         utilitários de data, tamanho e URL
  styles/      variáveis CSS e estilos globais/de layout
  test/        configuração do Vitest, servidor/handlers MSW, fixtures e auxiliares de renderização
  types/       DTOs da API que refletem os contratos do backend
```

## Configuração

Copie o arquivo de ambiente de exemplo e ajuste-o, se necessário:

```bash
cd frontend
cp .env.example .env
```

- `VITE_APP_NAME` — nome visível da aplicação.
- `VITE_API_BASE_URL` — caminho-base da API (por omissão, `/api/v1`, mantido
  na mesma origem).
- `DEV_PROXY_TARGET` — destino para o qual o servidor de desenvolvimento
  encaminha `/api/*` (por omissão, `http://127.0.0.1:8000`).

O servidor de desenvolvimento encaminha `/api` para o backend. Assim, o
navegador faz pedidos de mesma origem e o backend **não precisa de CORS
permissivo**. Em produção, disponibilize os arquivos compilados e a API na
mesma origem ou por trás de um proxy reverso.

Nunca faça commit de segredos, tokens ou palavras-passe reais; `.env` está
ignorado pelo Git.

## Execução

Backend (noutro terminal):

```bash
cd backend
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

- Frontend: http://localhost:5173
- Backend: http://127.0.0.1:8000

## Scripts

- `npm run dev` — inicia o servidor de desenvolvimento.
- `npm run build` — verifica os tipos e compila para produção.
- `npm run preview` — pré-visualiza a compilação de produção.
- `npm run lint` — executa o ESLint.
- `npm run typecheck` — verifica o TypeScript sem emitir arquivos.
- `npm run test` / `npm run test:run` — executa o Vitest em modo contínuo ou
  uma única vez, respetivamente.

## Autenticação e rotas

O token de acesso é guardado apenas em `sessionStorage` e enviado no cabeçalho
Bearer. `GET /auth/me` é a única fonte de verdade para o utilizador atual; o
JWT nunca é decodificado no cliente. Uma resposta 401 em qualquer ponto limpa
a sessão de forma centralizada. O frontend **não** é uma fronteira de
segurança: o backend autoriza todos os pedidos.

Rotas: `/login`, `/app/conversations`, `/app/conversations/:id`,
`/admin/documents` e `/admin/documents/:id`. As rotas protegidas não renderizam
conteúdo até a sessão ser resolvida; `/admin/*` exige adicionalmente um
administrador.

## Conversas

As perguntas passam apenas por `POST /conversations/{id}/ask`, nunca pelo
endpoint de criação manual de mensagens. O turno persistido devolvido pelo
backend é a fonte de verdade: ambas as mensagens são acrescentadas e
desduplicadas por ID, sem inserção otimista. As respostas são apresentadas
como texto simples, nunca como HTML. `insufficient_evidence` é um estado normal,
não um erro; respostas 502/503 não acrescentam uma mensagem local e preservam
o texto digitado para nova tentativa. As mutações de `/ask` nunca são repetidas
automaticamente.

## Administração de documentos

Administradores podem listar e filtrar documentos, criar um documento, enviar
uma versão (`FormData` multipart, com o delimitador definido pelo navegador),
reprocessar versões com falha — um 409 para versões referenciadas apresenta uma
mensagem segura — e descarregar o arquivo original por um pedido autenticado
convertido num URL de objeto temporário.

## Testes

Todos os testes usam MSW: não há rede real, backend nem chave de API. Conteúdo
não confiável — corpos de mensagens, títulos e URLs de fontes — possui testes
de segurança dedicados: é sempre renderizado como texto, e apenas URLs de fonte
`http`/`https` se tornam links.

## Limitações desta fase

Não há streaming, WebSocket/SSE, edição ou eliminação de mensagens, feedback,
pesquisa, memória conversacional, Markdown/HTML rico, modo escuro, PWA nem
contentor de produção. A geração continua experimental e não está livre de
alucinações.
