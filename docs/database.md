# Database Notes

## Migration history

| Order | Revision | Description |
|---|---|---|
| 1 | `db13417f9dc4` | Enable the `pgvector` extension |
| 2 | `de4e133df3c9` | Create the `institutions` table |
| 3 | `9cf6ff5ac49c` | Create the `users` table with `institution_id` and the required multi-institution fields |
| 4 | `9ec09d09f22f` | Create the `conversations` and `messages` tables |
| 5 | `3ed4bcad52c8` | Add composite multi-institution foreign keys and their supporting unique constraints |

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
persistence and CRUD-style endpoints. The information-retrieval approach
(RAG or otherwise) is still an open question for the project's
literature review — nothing here should be read as a decision already
made; pgvector is enabled purely as infrastructure available for that
future work.

A message's `user_id` records who actually authored it: for `role="user"`
it's the sending user; for `role="system"` it's the admin who created it
manually (see `message_service.create_message`), which is what makes
system messages auditable. It is only ever `NULL` for future automatic
`"assistant"` messages, which aren't created through this API yet — role
`"system"` does **not** imply a null `user_id`.

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
- **`register_initial_admin` is race-safe, and refuses inactive
  institutions.** It takes a `SELECT ... FOR UPDATE` lock on the
  institution row before checking for an existing admin, so two
  concurrent registrations for the same institution are serialized —
  only one can succeed; the other gets 409. It also rejects (409) an
  attempt to register the first admin of an institution whose
  `is_active` is `false`: that admin could never log in anyway
  (`authenticate_user` also checks the institution's `is_active`), so
  it's better to refuse upfront than create an unusable account.
- **The last-admin invariant is enforced transactionally.** When
  `PATCH /api/v1/users/{id}` would deactivate or demote the institution's
  last active admin, `user_service.update_user` takes a
  `SELECT ... FOR UPDATE` lock on the institution row before counting
  active admins, so two concurrent requests targeting admins of the same
  institution are serialized — the second one re-counts active admins
  only after the first has committed, so the invariant (at least one
  active admin) can't be violated by a race.
- **An institutional admin can't (de)activate their own institution.**
  `PATCH /api/v1/institutions/{id}` uses the `InstitutionAdminUpdate`
  schema, which has no `is_active` field and uses `extra="forbid"` —
  sending `is_active` there is a 422, not a silent no-op. This closes
  off the obvious way an admin could lock themselves (and everyone else
  at that institution) out with no recovery path. The only way to
  (de)activate an institution now is the bootstrap-only
  `PATCH /api/v1/bootstrap/institutions/{id}/status` endpoint (gated by
  `X-Bootstrap-Token`, payload limited to `{"is_active": bool}`); see the
  [README walkthrough](../README.md#reactivating-an-institution).
- **PostgreSQL enforces cross-institution consistency directly, not just
  application code.** Migration `3ed4bcad52c8` adds "degenerate" unique
  constraints on `(id, institution_id)` for `users` and `conversations`
  (id alone is already unique; these exist only to be referenced) and
  replaces the plain foreign keys they superseded with composite ones:
  `conversations.(user_id, institution_id)` → `users.(id, institution_id)`,
  `messages.(conversation_id, institution_id)` →
  `conversations.(id, institution_id)`, and
  `messages.(user_id, institution_id)` → `users.(id, institution_id)`
  (skipped by PostgreSQL when `user_id` is `NULL`, its default `MATCH
  SIMPLE` behavior). A conversation whose `user_id` belongs to a
  different institution than its own `institution_id`, or a message
  whose `conversation_id`/`user_id` belongs to a different institution,
  is now rejected by the database itself — the previous simple foreign
  keys only checked that the referenced row existed, not that it
  belonged to the same institution.
- **A conversation's `status` gates further activity.** `active` is the
  only status that accepts new messages or `PATCH` updates; `closed` and
  `archived` are **final** states in this prototype — both reject new
  messages and any `PATCH` (including one attempting to move the status
  back to `active`) with 409. There is no reopen endpoint in this phase.
- **A conversation's/message's `language` is always institution-aware.**
  On `POST /api/v1/conversations`, an omitted `language` defaults to
  `institution.default_language`; a provided one is normalized and must
  be one of `institution.supported_languages`, or the request gets 422.
  On `POST .../messages`, an omitted `language` inherits the
  conversation's `language`; a provided one is validated the same way,
  against the *same* institution's `supported_languages` (different
  institutions can support different languages). This resolution lives
  in `app.core.language.resolve_language`, called from both
  `conversation_service` and `message_service`, so the rule is
  implemented once. Updating an institution's `supported_languages` to
  drop its current `default_language` was already rejected before this
  pass (`institution_service.update_institution` re-validates the
  resulting configuration on every `PATCH`); historical conversations
  are not migrated if an institution's supported languages change later.

## Current status

No RAG, embeddings, retrieval or agent behavior is implemented — the
retrieval approach is an open question for the literature review, not a
decision already made in this codebase. Current work is limited to
persistence, CRUD APIs, authentication and the core domain invariants
described above (institutional security rules, conversation/message
state and language rules, and multi-institution data integrity).
