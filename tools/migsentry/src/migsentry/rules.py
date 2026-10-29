"""Dangerous-migration rule engine: migration SQL in, findings out.

Scans migration SQL from any source (Alembic autogenerate, Django sqlmigrate,
Prisma, handwritten) against a registry of dangerous-operation rules, with the
expand/contract alternative for each. Line directives (-- migsentry: no-check)
skip the following statement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SEVERITIES = ("info", "warn", "danger")


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    line: int
    table: str
    detail: str
    fix: str
    snippet: str = ""


@dataclass(frozen=True)
class SqlRule:
    name: str
    severity: str
    pattern: re.Pattern
    table_group: int = 0       # 0 = no captured table
    detail: str = ""
    fix: str = ""
    statement_scoped: bool = True


@dataclass
class Statement:
    line: int                  # 1-based line in the file where the statement starts
    text: str
    skipped: bool = False


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    statements: list[Statement] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    skipped_lines: list[int] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in SEVERITIES}
        for f in self.findings:
            out[f.severity] += 1
        return out

    @property
    def has_danger(self) -> bool:
        return any(f.severity == "danger" for f in self.findings)

    @property
    def checked(self) -> int:
        return sum(1 for s in self.statements if not s.skipped)


def _compile(name, severity, pattern, table_group, detail, fix):
    return SqlRule(name, severity, re.compile(pattern, re.IGNORECASE), table_group, detail, fix)


BUILTIN: list[SqlRule] = [
    _compile("drop-table", "danger",
             r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?[`\"'\[]?(\w+)", 1,
             "Dropping a table is instant and unrecoverable; any code still touching it fails immediately.",
             "Deploy the code that stops using the table first; drop after a full release cycle, with a backup taken."),
    _compile("drop-column", "danger",
             r"\bDROP\s+COLUMN\s+[`\"'\[]?(\w+)", 1,
             "Dropping a column is unrecoverable and breaks every reader and writer still touching it.",
             "Stop all code reading/writing the column and deploy; only then drop (with a backup)."),
    _compile("rename-column", "danger",
             r"\b(?:RENAME\s+(?:COLUMN\s+)?|CHANGE\s+(?:COLUMN\s+)?)[`\"'\[]?(\w+)[`\"'\]]?\s+TO\s+", 1,
             "A rename moves the schema and code in one step only if they deploy together — they never do. "
             "Every query between deploy and restart fails on the missing old name.",
             "Expand/contract: add the new column, dual-write, backfill, move readers, then drop the old name."),
    _compile("not-null-existing", "danger",
             r"\bALTER\s+TABLE\s+[`\"'\[]?(\w+)[`\"'\]]?(?:\s+WITH\s+OUT\s+ROWID)?\b[^;]*\bSET\s+NOT\s+NULL\b", 1,
             "SET NOT NULL scans the whole table under an ACCESS EXCLUSIVE lock; rows violating it abort the migration.",
             "Add nullable with default, backfill in batches, then ADD CONSTRAINT ... NOT NULL NOT VALID; VALIDATE CONSTRAINT."),
    _compile("add-column-with-default", "warn",
             r"\bALTER\s+TABLE\s+[`\"'\[]?(\w+)[`\"'\]]?\s+ADD\s+(?:COLUMN\s+)?\s*[`\"'\[]?\w+[`\"'\]]?\s+\w+\s+(?:NOT\s+NULL\s+)?DEFAULT", 1,
             "Postgres 11+ applies a default without a rewrite, but MySQL historically rewrites the whole table "
             "for ADD COLUMN, and older Postgres rewrites for non-constant defaults.",
             "Add the column nullable without DEFAULT, backfill in batches, add the default in a later migration."),
    _compile("alter-type", "danger",
             r"\bALTER\s+TABLE\s+[`\"'\[]?(\w+)[`\"'\]]?\s+.*\b(?:TYPE|MODIFY)\b", 1,
             "Type conversion rewrites the table under ACCESS EXCLUSIVE; failing casts abort mid-rewrite.",
             "Add a new column of the target type, dual-write with a cast in code, backfill, switch reads, drop later."),
    _compile("plain-create-index", "warn",
             r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?!.*\bCONCURRENTLY\b)", 0,
             "A plain CREATE INDEX blocks writes for the whole index build on Postgres and takes locks on MySQL too.",
             "Use CREATE INDEX CONCURRENTLY on any table taking writes; afterwards check for INVALID indexes "
             "(a failed concurrent build leaves one) and drop them with DROP INDEX CONCURRENTLY."),
    _compile("add-foreign-key-direct", "warn",
             r"\bADD\s+(?:CONSTRAINT\s+\w+\s+)?FOREIGN\s+KEY", 0,
             "Adding a FOREIGN KEY validates every row of the child table while holding locks.",
             "ADD CONSTRAINT ... NOT VALID installs it instantly; VALIDATE CONSTRAINT uses a weaker lock."),
    _compile("large-index-build", "info",
             r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b", 0,
             "Even CONCURRENTLY scans the entire table; on multi-GB tables budget time and IO.",
             "Prefer a partial index (WHERE ...) when queries touch a slice; measure before and after."),
    _compile("truncate", "danger",
             r"\bTRUNCATE\s+(?:TABLE\s+)?[`\"'\[]?(\w+)", 1,
             "TRUNCATE removes every row instantly and is not transactional on all engines.",
             "Snapshot the table first; in production prefer audited batched DELETEs with a WHERE."),
    _compile("lock-table", "warn", r"\bLOCK\s+TABLE", 0,
             "Explicit table locks serialize all access and can deadlock against a busy app.",
             "Take the narrowest lock for the shortest window; on Postgres, prefer advisory locks."),
]

SKIP_MARKER = re.compile(r"(?i)^--\s*migsentry:\s*no-check\b")


def split_statements(sql: str) -> Statement:
    """Yield statements with their starting line and the skip markers preceding them."""
    statement = ""
    start_line = 1
    line_no = 0
    skip_next = False
    for line in sql.splitlines():
        line_no += 1
        if SKIP_MARKER.match(line.strip()):
            skip_next = True
            continue
        if not statement.strip() and start_line <= line_no:
            start_line = line_no if not statement else start_line
        if not statement:
            start_line = line_no
        statement += line + "\n"
        if ";" in line and not line.strip().startswith("--"):
            yield Statement(start_line, statement, skipped=skip_next)
            statement = ""
            skip_next = False
    if statement.strip():
        yield Statement(start_line, statement, skipped=skip_next)


def scan_sql(sql: str, path: str = "<input>") -> Report:
    report = Report(files=[path])
    for stmt in split_statements(sql):
        report.statements.append(stmt)
        if stmt.skipped:
            report.skipped_lines.append(stmt.line)
            continue
        for rule in BUILTIN:
            m = rule.pattern.search(stmt.text)
            if not m:
                continue
            table = ""
            if rule.table_group:
                try:
                    table = m.group(rule.table_group)
                except IndexError:
                    table = ""
            snippet = " ".join(stmt.text.strip().split())[:120]
            report.findings.append(Finding(
                rule.name, rule.severity, stmt.line + stmt.text[: m.start()].count("\n"),
                table, rule.detail, rule.fix, snippet))
    return report
