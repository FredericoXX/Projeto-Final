# Institutional Assistant — Frontend

Minimal, responsive web interface for the Institutional Assistant prototype. It
demonstrates the full flow without Swagger or manual requests: sign in, hold a
grounded conversation with sources, and (as an admin) manage documents and
their versions.

The UI is **institution-neutral** — the app name comes from `VITE_APP_NAME`,
never hard-coded — and multilingual (PT/EN), independent of the language of the
conversation itself.

## Technologies

React 18 + TypeScript (strict), Vite, React Router, TanStack Query, Vitest +
React Testing Library + MSW, ESLint. No UI framework and no state library
beyond TanStack Query; the HTTP layer is native `fetch`.

## Structure

```
src/
  api/         typed HTTP client, error parsing, token storage, endpoint modules
  app/         App, router, query client
  auth/        AuthProvider, ProtectedRoute, AdminRoute
  components/  layout, feedback and common presentational components
  features/    auth, conversations and documents pages + query hooks
  i18n/        PT/EN dictionaries, provider and hook
  lib/         date / size / URL helpers
  styles/      CSS variables and global/layout styles
  test/        Vitest setup, MSW server/handlers, fixtures, render helpers
  types/       API DTOs mirroring the backend contracts
```

## Configuration

Copy the example env file and adjust if needed:

```bash
cd frontend
cp .env.example .env
```

- `VITE_APP_NAME` — visible application name.
- `VITE_API_BASE_URL` — API base path (default `/api/v1`, kept same-origin).
- `DEV_PROXY_TARGET` — where the dev server proxies `/api/*` (default
  `http://127.0.0.1:8000`).

The dev server proxies `/api` to the backend, so the browser makes same-origin
requests and the backend needs **no permissive CORS**. In production, serve the
built assets and the API on the same origin or behind a reverse proxy.

Never commit real secrets, tokens or passwords; `.env` is gitignored.

## Running

Backend (in another terminal):

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

- `npm run dev` — start the dev server.
- `npm run build` — type-check and build for production.
- `npm run preview` — preview the production build.
- `npm run lint` — ESLint.
- `npm run typecheck` — TypeScript, no emit.
- `npm run test` / `npm run test:run` — Vitest (watch / once).

## Authentication & routes

The access token is stored in `sessionStorage` only and sent as a bearer
header; `GET /auth/me` is the single source of truth for the current user (the
JWT is never decoded client-side). A 401 anywhere clears the session centrally.
The frontend is **not** a security boundary — the backend authorizes every
request.

Routes: `/login`, `/app/conversations`, `/app/conversations/:id`,
`/admin/documents`, `/admin/documents/:id`. Protected routes render nothing
until the session resolves; `/admin/*` additionally requires an admin.

## Conversations

Questions go only through `POST /conversations/{id}/ask` (never the manual
message endpoint). The persisted turn returned by the backend is the source of
truth — both messages are appended, de-duplicated by id, with no optimistic
insert. Answers render as plain text (never HTML); `insufficient_evidence` is a
normal state, not an error; 502/503 never add a local message and keep the
typed text for retry. `/ask` mutations are never auto-retried.

## Admin documents

Admins can list/filter documents, create a document, upload a version
(multipart `FormData`, boundary set by the browser), reprocess failed versions
(a 409 for referenced versions shows a safe message) and download the original
file via an authenticated request converted to a temporary object URL.

## Testing

All tests run against MSW — no real network, no backend, no API key. Untrusted
content (message bodies, titles, source URLs) is covered by dedicated safety
tests: it is always rendered as text, and only `http`/`https` source URLs
become links.

## Limitations (this phase)

No streaming, WebSocket/SSE, message editing/deletion, feedback, search,
conversational memory, rich Markdown/HTML, dark mode, PWA or production
container. The generation remains experimental and is not hallucination-free.
