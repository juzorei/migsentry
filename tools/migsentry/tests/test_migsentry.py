import json

import pytest

from migsentry.cli import main
from migsentry.rules import scan_sql, split_statements


def test_drop_table_flagged_danger():
    r = scan_sql("DROP TABLE old_users;\n")
    assert r.has_danger and r.findings[0].rule == "drop-table"
    assert r.findings[0].table == "old_users"


def test_add_column_with_default_warn():
    r = scan_sql("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active';\n")
    rules = {f.rule for f in r.findings}
    assert "add-column-with-default" in rules
    assert not any(f.rule == "not-null-existing" for f in r.findings)


def test_set_not_null_danger():
    r = scan_sql("ALTER TABLE users ALTER COLUMN email SET NOT NULL;\n")
    assert any(f.rule == "not-null-existing" and f.severity == "danger" for f in r.findings)


def test_rename_column_danger():
    r = scan_sql("ALTER TABLE users RENAME COLUMN name TO full_name;\n")
    assert any(f.rule == "rename-column" for f in r.findings)


def test_plain_index_warns_concurrently_does_not():
    plain = scan_sql("CREATE INDEX idx_users_email ON users(email);\n")
    conc = scan_sql("CREATE INDEX CONCURRENTLY idx_users_email ON users(email);\n")
    assert any(f.rule == "plain-create-index" for f in plain.findings)
    assert not any(f.rule == "plain-create-index" for f in conc.findings)
    assert any(f.rule == "large-index-build" for f in conc.findings)  # info still fires


def test_fk_not_valid_no_warning_but_direct_fk_warns():
    direct = scan_sql("ALTER TABLE orders ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id);\n")
    assert any(f.rule == "add-foreign-key-direct" for f in direct.findings)


def test_skip_directive():
    sql = "-- migsentry: no-check\nDROP TABLE tmp_scratch;\n"
    r = scan_sql(sql)
    assert r.checked == 0 and len(r.skipped_lines) == 1 and not r.findings
    sql2 = "-- migsentry: no-check\nDROP TABLE a;\nDROP TABLE b;\n"
    r2 = scan_sql(sql2)
    assert r2.checked == 1 and any(f.table == "b" for f in r2.findings)


def test_safe_migration_clean():
    sql = (
        "ALTER TABLE users ADD COLUMN nickname TEXT;\n"
        "CREATE INDEX CONCURRENTLY idx_users_nick ON users(nickname);\n"
    )
    r = scan_sql(sql)
    assert not r.has_danger and all(f.severity == "info" for f in r.findings)


def test_statement_line_numbers():
    sql = "ALTER TABLE a ADD COLUMN x TEXT;\n\n\nDROP TABLE b;\n"
    r = scan_sql(sql)
    drop = next(f for f in r.findings if f.rule == "drop-table")
    assert drop.line == 4


def test_multi_statement_split():
    sql = "ALTER TABLE a ADD COLUMN x TEXT DEFAULT 'q';\nDROP TABLE b;\nTRUNCATE c;\n"
    r = scan_sql(sql)
    assert r.checked == 3


def test_cli_scan_directory_and_exit_code(tmp_path, capsys):
    d = tmp_path / "versions"
    d.mkdir()
    (d / "0001_safe.sql").write_text("ALTER TABLE a ADD COLUMN x TEXT;\n", encoding="utf-8")
    (d / "0002_drop.sql").write_text("DROP TABLE b;\n", encoding="utf-8")
    rc = main(["scan", str(d), "--json"])
    assert rc == 1
    rows = json.loads(capsys.readouterr().out)
    joined = json.dumps(rows)
    assert "0001_safe" in joined and "0002_drop" in joined and "drop-table" in joined


def test_cli_clean_exit_zero(tmp_path, capsys):
    f = tmp_path / "ok.sql"
    f.write_text("ALTER TABLE a ADD COLUMN x TEXT;\n", encoding="utf-8")
    assert main(["scan", str(f)]) == 0
    out = capsys.readouterr().out
    assert "no findings" in out


def test_cli_no_sql_files(tmp_path):
    (tmp_path / "x.txt").write_text("hi", encoding="utf-8")
    assert main(["scan", str(tmp_path)]) == 2
    assert main(["scan", str(tmp_path / "missing.sql")]) == 2
