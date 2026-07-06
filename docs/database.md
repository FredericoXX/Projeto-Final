# Database Notes

## Migration history

| Order | Revision | Description |
|---|---|---|
| 1 | `db13417f9dc4` | Enable the `pgvector` extension |
| 2 | `de4e133df3c9` | Create the `institutions` table |
| 3 | `9cf6ff5ac49c` | Create the `users` table with `institution_id` and the required multi-institution fields |

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

## Current status

The base `users` schema is now prepared for the multi-institution model.
There is no User API and no authentication implemented yet. The next work
is to build the schemas, services, administrative endpoints, and
authentication on top of this schema.
