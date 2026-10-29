---
name: migration-safety-review
description: Review a database migration (Alembic, Django, Prisma, handwritten SQL) for operations that will lock tables, rewrite data or break the running app before it deploys. Use whenever the user writes, edits or autogenerates a schema migration, says "review this migration", asks "is this safe to run on prod", mentions Alembic/autogenerate, Django migrations, Prisma migrate, `sqlmigrate`, " ALTER TABLE", "add index", wants to rename or drop a column, or a deploy window is coming and migrations must not stall the database. Covers locking semantics (Postgres ACCESS EXCLUSIVE, MySQL rewrites), NOT NULL on existing columns, index builds with/without CONCURRENTLY, unvalidated foreign keys, and the expand/contract pattern.
---

# Migration safety review

A migration is a deploy artifact like code, except its bugs lock production tables. The review has one purpose: **catch the operations that stall or break the database before they run — while they're still text.**

Install the CLI:

```bash
pip install migsentry
```

## 1. Scan first, read findings, then reason

```bash
migsentry scan migrations/versions/         # directory of SQL, or single files
```

```text
== migrations/versions/0007_rename.sql: 3 checked, 0 skipped
  [DANGER] L1    rename-column on name
          ALTER TABLE users RENAME COLUMN name TO full_name;
          why: A rename moves the schema and code in one step only if they deploy together — they never do.
          fix: Expand/contract: add the new column, dual-write, backfill, move readers, then drop the old name.
  -> 3 finding(s): 2 danger, 1 info
```

Exit code 1 means at least one `danger` finding — CI-gateable. Known-safe statements can be marked per-statement, never per-file silent:

```sql
-- migsentry: no-check
DROP TABLE tmp_scratch;
```

A clean scan is not a green light: the scanner covers the dangerous-operation classes, not your application's semantics.

## 2. The verdict classes and what each really means

- **drop-table / drop-column (danger)** — instant, unrecoverable, breaks every live reader. Only after the code that touches the object has been fully deployed *and* a release cycle passed. Take a backup first; "we'll restore from the old branch" is not a backup.
- **rename-column (danger)** — schema moves, code doesn't: every query between deploy and restart fails on the old name. Expand/contract always.
- **not-null-existing (danger)** — `SET NOT NULL` scans the entire table under an ACCESS EXCLUSIVE lock and aborts on any violating row. On a hot table that's an outage with an error message.
- **alter-type (danger)** — full table rewrite; a failing cast aborts mid-rewrite.
- **plain-create-index (warn)** — blocks writes for the whole build. `CREATE INDEX CONCURRENTLY` avoids it, but: it can't run inside a transaction (Alembic and Django need explicit handling — check your specific tooling's autocommit mode), and a *failed* concurrent build leaves an INVALID index that silently sits there. After running it in prod, check for INVALIDs:
  `SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;`
- **add-foreign-key-direct (warn)** — row-by-row validation under lock. Two-step: `ADD CONSTRAINT ... NOT VALID` (instant) then `VALIDATE CONSTRAINT` (weak lock).
- **add-column-with-default (warn)** — engine-dependent: Postgres 11+ is fast for constant defaults, MySQL rewrites the table. Know your engine and version before shrugging this off.
- **large-index-build / lock-table / truncate** — read the `fix` line in the finding; they're context-dependent.

The engine matters more than the rule: verify the actual Postgres/MySQL version in use before relying on a "fast path" (e.g. Postgres 11 fast defaults, MySQL 8 instant ADD COLUMN) — the scanner assumes the cautious reading.

## 3. The answer to almost every danger finding: expand/contract

Three deploys, zero downtime, for a rename (the pattern generalizes to type changes and NOT NULL tightening):

1. **Expand:** `ALTER TABLE users ADD COLUMN full_name TEXT;` — deploy code that dual-writes (on write: set both; on read: prefer new, fall back to old).
2. **Contract:** backfill in batches (`UPDATE ... WHERE full_name IS NULL AND id BETWEEN ...` — batched by primary key, committed per batch, never one giant UPDATE); move reads to the new column; deploy.
3. **Drop:** remove the old column in a *later* migration, after logs confirm nothing references it.

The common failure isn't forgetting a step — it's collapsing steps 2 and 3 into one deploy "to save time". That's exactly the bug the review exists to catch.

## 4. Migration-file review checklist

Beyond the scanner: read the migration like a reviewer, not just rule-match it.

- **Reversibility:** can it be rolled back without data loss? A migration that drops data is not reversible — say so in the PR explicitly instead of writing a fake `down()`.
- **Autogenerate trust:** Alembic/Django autogenerate diffs *models*, not *data* and not *intent*. It is happy to autogenerate a destructive rename as a drop+add (silently losing data). Never review autogenerated SQL with "looks fine".
- **Data migrations:** a `RunPython`/backfill touching a big table needs batching and a progress log; a single UPDATE over 50M rows holds locks proportional to its runtime.
- **Transactionality:** on Postgres most DDL is transactional and you should keep it so; `CONCURRENTLY` is the exception (autocommit). If the tooling wraps everything in one transaction, the CONCURRENTLY build fails — check before it reaches prod.
- **Size honesty:** the same statement is a non-event on a 1k-row table and an outage on a 50M-row table. Check row counts (or ask) before judging severity.

## 5. Report

```text
verdict:  0007_rename.sql — NOT SAFE TO DEPLOY AS WRITTEN
danger:   rename-column (L1), not-null-existing (L2) — both lock app-critical tables
fix:      expand/contract sketch provided (3 deploys); SET NOT NULL → backfill + NOT VALID pattern
verified: migsentry scan exit 1 (2 danger); re-scan after the rewrite is green (exit 0)
```

If a finding is a deliberate, backup-verified drop with the code already deployed — say that explicitly with the checklist for the drop, instead of leaving the danger unexplained.

## Scope

Review migrations the user owns or is authorized to change. The advice assumes a relational database you can take a backup of; a "just run it" recommendation on someone else's prod is out of this skill's contract.
