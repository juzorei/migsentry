# migsentry

Scan database migration SQL for the operations that lock tables, rewrite data or break the running app — before they hit prod.

```text
$ migsentry scan migrations/versions/
== migrations/versions/0007_rename.sql: 3 checked, 0 skipped
  [DANGER] L1    rename-column on name
          ALTER TABLE users RENAME COLUMN name TO full_name;
          why: A rename moves the schema and code in one step only if they deploy together — they never do.
          fix: Expand/contract: add the new column, dual-write, backfill, move readers, then drop the old name.
  -> 3 finding(s): 2 danger, 1 info
```

Works on any source of migration SQL: Alembic autogenerate, Django `sqlmigrate` output, Prisma, handwritten. Exit code 1 on any `danger` finding — CI-gateable. Per-statement opt-outs with a directive, never silent file-level skips:

```sql
-- migsentry: no-check
DROP TABLE tmp_scratch;
```

What it flags (the classic expand/contract canon, aligned with strong_migrations/squawk checklists):

| Class | Severity | Headline |
|---|---|---|
| drop-table / drop-column / truncate / rename-column / alter-type / not-null-existing | danger | unrecoverable, breaks live readers, or full-table rewrite under ACCESS EXCLUSIVE |
| plain CREATE INDEX / direct FOREIGN KEY / ADD COLUMN with DEFAULT / LOCK TABLE | warn | locking pitfalls with a known two-step or CONCURRENTLY fix |
| any CREATE INDEX | info | even CONCURRENTLY scans everything — budget time on big tables |

Each finding prints *why* (engine-specific locking semantics) and *fix* (the expand/contract alternative). Python 3.11+, stdlib only.

```text
migsentry scan <file-or-dir>... [--json]
```

Install: `pip install migsentry` — or from this repo:
`pip install "git+https://github.com/juzorei/migsentry#subdirectory=tools/migsentry"`

The companion agent skill lives in [skills/migration-safety-review](../skills/migration-safety-review). Skills: `npx skills add juzorei/migsentry`.
