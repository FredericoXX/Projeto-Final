# Database Notes

## Migration history (do not edit)

| Order | Revision | Description |
|---|---|---|
| 1 | `db13417f9dc4` | Enable the `pgvector` extension |
| 2 | `9cf6ff5ac49c` | Create the `users` table (`id`, `email`, `password_hash`, `created_at`) |
| 3 | `de4e133df3c9` | Create the `institutions` table |

These migrations are historical and must not be edited, dropped, or squashed.
The `users` table created by `9cf6ff5ac49c` is intentionally minimal — it
predates the multi-institution model and is completed by a later migration
(see below), never replaced.

## Planned: completing the `users` table (Block 2)

Block 1 (Institutions) is stable. Block 2 (Users) has not started yet — no
User API endpoints, schemas, or authentication exist in the codebase. Before
that work begins, this decision is recorded so the next migration is written
consistently with the current schema:

- A **new** Alembic migration will alter the existing `users` table. It will
  not drop or recreate it.
- The migration will add:
  - `institution_id` — `NOT NULL`, foreign key to `institutions.id`
  - `full_name`
  - `role`
  - `is_active`
  - `updated_at`
- `institution_id` ties every user to exactly one institution, consistent
  with the multi-institution design established for `institutions`.
- Because `institution_id` is `NOT NULL` and the table may already contain
  rows, the migration will need a backfill strategy (or the table is empty
  in every environment so far — confirm before writing it) rather than
  adding the column as `NOT NULL` directly.
- This migration is scoped to Block 2 and is deliberately not created yet.
