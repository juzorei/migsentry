# migsentry

[English](README.md) | [Русский](README.ru.md)

[![CI](https://github.com/juzorei/migsentry/actions/workflows/ci.yml/badge.svg)](https://github.com/juzorei/migsentry/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/github/license/juzorei/migsentry)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/migsentry)](https://pypi.org/project/migsentry/)

An agent skill and a CLI that review database migrations for the operations that lock tables, rewrite data or break the running app — before they hit prod.

A migration is a deploy artifact like code, except its bugs lock production tables. `migsentry` scans migration SQL from any source (Alembic autogenerate, Django `sqlmigrate`, Prisma, handwritten) and flags the dangerous classes with engine-specific *why* lines and the expand/contract *fix* for each:

```text
$ migsentry scan migrations/versions/
== migrations/versions/0007_rename.sql: 3 checked, 0 skipped
  [DANGER] L1    rename-column on name
          ALTER TABLE users RENAME COLUMN name TO full_name;
          why: A rename moves the schema and code in one step only if they deploy together — they never do.
          fix: Expand/contract: add the new column, dual-write, backfill, move readers, then drop the old name.
  -> 3 finding(s): 2 danger, 1 info
```

Exit code 1 on any danger finding — CI-gateable. Known-safe statements are marked with a `-- migsentry: no-check` directive on the exact statement, never silenced file-wide.

## What's in the repo

- **[skills/migration-safety-review](skills/migration-safety-review)** — the review workflow for coding agents: scan first, understand each verdict class (locking semantics per engine, CONCURRENTLY and its transaction caveats, NOT VALID/VALIDATE foreign keys), the expand/contract pattern as the answer to almost every danger, the beyond-the-scanner checklist (autogenerate diffing models not intent, batching backfills, reversibility honesty), and a report format that never leaves a danger unexplained.
- **tools/migsentry** — the CLI ([README](tools/migsentry/README.md)): danger/warn/info verdicts, engine-specific explanations, `--json`, per-statement skip directives, stdlib only.

## Install

```bash
pip install migsentry
npx skills add juzorei/migsentry
```

## More from this portfolio

Part of a series of focused skill+CLI tools by the same author:

- [ci-autopsy](https://github.com/juzorei/ci-autopsy) — gate the scan in CI, read failures like a triage
- [bumpmap](https://github.com/juzorei/bumpmap) — the sibling risk: dependency upgrades
- [hookbench](https://github.com/juzorei/hookbench) — integration tests that survive handler churn

Browse the rest at the [juzorei profile](https://github.com/juzorei?tab=repositories).

## Scope

Review migrations you own or are authorized to change. The advice assumes a database you can back up.

MIT licensed.
