# Database Notes

## Migration history

| Order | Revision | Description |
|---|---|---|
| 1 | `db13417f9dc4` | Enable the `pgvector` extension |
| 2 | `de4e133df3c9` | Create the `institutions` table |
| 3 | `9cf6ff5ac49c` | Create the `users` table with `institution_id` and the required multi-institution fields |
| 4 | `9ec09d09f22f` | Create the `conversations` and `messages` tables |

Since the project is still in local-only development with no shared
environments, no production data, and disposable databases, the `users`
migration was rewritten in place to create the table already correctly
shaped for the multi-institution model, instead of adding a fourth
migration to alter it later. There is no separate "complete `users`"
migration — the historical migration itself is now correct.

The `users` table (as created by `9cf6ff5ac49c`) has:

- `id` — UUID, primary key, application-generated via the ORM default
- `institution_id` — UUID, `NOT NULL`, foreign key to `institutions.id`, indexed
- `full_name` — `String(255)`, `NOT NULL`
- `email` — `String(255)`, `NOT NULL`, globally unique
- `password_hash` — `String(255)`, `NOT NULL`
- `role` — `String(50)`, `NOT NULL`, server default `"user"`
- `is_active` — `Boolean`, `NOT NULL`, server default `true`
- `created_at` — timezone-aware timestamp, `NOT NULL`, server default `now()`
- `updated_at` — timezone-aware timestamp, `NOT NULL`, server default `now()`

`email` uniqueness remains global (not scoped per institution) — that is
unchanged from the original design and was not revisited in this pass.

The `institutions`, `users`, `conversations` and `messages` tables all
have a full API on top of them: institution management, a user
management API scoped to the authenticated admin's institution,
JWT + Argon2 based authentication (login and initial-admin
registration), and a conversations/messages API scoped to the
authenticated user's institution (and, for non-admins, to their own
conversations). See
[`app/api/routes/institutions.py`](../backend/app/api/routes/institutions.py),
[`app/api/routes/users.py`](../backend/app/api/routes/users.py),
[`app/api/routes/auth.py`](../backend/app/api/routes/auth.py) and
[`app/api/routes/conversations.py`](../backend/app/api/routes/conversations.py).

A conversation belongs to one institution and one user, and groups the
messages exchanged in an assistant session. This phase only covers
persistence and CRUD-style endpoints — no RAG, embeddings, retrieval or
LLM generation is implemented yet.

## Institutional security rules

These rules were added after a security review found the institutions
API was fully public and a few multi-institution invariants were
unenforced. They apply on top of the per-request `institution_id`
scoping already described above.

- **No `platform_admin` role yet.** Creating an institution
  (`POST /api/v1/institutions`) and registering its first admin
  (`POST /api/v1/auth/register-initial-admin`) are bootstrap-only
  operations, gated by the `BOOTSTRAP_TOKEN` setting sent as the
  `X-Bootstrap-Token` header — not by a JWT, since no admin exists yet
  at that point. A missing or wrong token, or an unset `BOOTSTRAP_TOKEN`,
  fails closed with 401. This is a temporary stand-in until a real
  platform-level admin role exists; see the
  [README bootstrap walkthrough](../README.md#bootstrapping-an-institution).
- **Reading and updating an institution require an authenticated admin,
  scoped to their own institution.** `GET /api/v1/institutions`,
  `GET /api/v1/institutions/{id}` and `PATCH /api/v1/institutions/{id}`
  all require a valid admin JWT. An admin's `institution_id` is never
  taken from the request payload or path for authorization purposes —
  only from the authenticated user. Any `id` other than the admin's own
  institution is reported as 404 (`resource_not_found`), the same as a
  non-existent institution, so these endpoints never confirm that
  another tenant exists.
- **An institution's `is_active` flag is enforced on every authenticated
  request, not only at login.** `get_current_user` re-checks both the
  user's and their institution's `is_active` on every call, so
  deactivating an institution immediately invalidates all outstanding
  tokens for its users (they get 401 on their next request, including
  `/auth/me`). Login also fails (401, generic message) if the user's
  institution is inactive, using the same wording as a wrong password so
  the response never reveals *why* it failed.
- **An institution must always keep at least one active admin.** In
  `PATCH /api/v1/users/{id}`: an admin can never deactivate their own
  account; and if a user is the institution's last active admin,
  neither deactivating them (`is_active: false`) nor changing their
  `role` away from `"admin"` is allowed (409 `resource_conflict`). With
  two or more active admins, one admin may deactivate or change the role
  of another.
- **`register_initial_admin` is race-safe.** It takes a `SELECT ... FOR
  UPDATE` lock on the institution row before checking for an existing
  admin, so two concurrent registrations for the same institution are
  serialized — only one can succeed; the other gets 409.

## Current status

No RAG, embeddings, retrieval or agent behavior is implemented yet —
current work is limited to persistence, CRUD APIs, authentication and
the institutional security rules described above.
