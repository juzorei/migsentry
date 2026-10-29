"""migsentry CLI: scan migration files for dangerous operations before they hit prod."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .rules import Report, scan_sql


def fmt_report(report: Report, path: str) -> None:
    counts = report.counts()
    print(f"== {path}: {report.checked} checked, {len(report.skipped_lines)} skipped")
    for f in sorted(report.findings, key=lambda f: (list(("danger", "warn", "info")).index(f.severity), f.line)):
        where = f" on {f.table}" if f.table else ""
        print(f"  [{f.severity.upper():5}] L{f.line:<4} {f.rule}{where}")
        print(f"          {f.snippet}")
        print(f"          why: {f.detail}")
        print(f"          fix: {f.fix}")
    total = sum(counts.values())
    summary = "no findings" if not total else ", ".join(
        f"{counts[s]} {s}" for s in ("danger", "warn", "info") if counts[s])
    print(f"  -> {total} finding(s): {summary}")


def cmd_scan(args) -> int:
    reports = []
    for target in args.targets:
        p = Path(target)
        if p.is_dir():
            files = sorted(str(x) for x in p.rglob("*") if x.suffix in (".sql",))
            if not files:
                print(f"migsentry: no .sql files under {target}", file=sys.stderr)
                return 2
        else:
            files = [str(p)]
        for f in files:
            sql = Path(f).read_text(encoding="utf-8", errors="replace")
            reports.append((scan_sql(sql, f), f))
    if args.json:
        print(json.dumps([_report_json(r) for r, _ in reports], indent=2))
    else:
        for r, f in reports:
            fmt_report(r, f)
    any_danger = any(r.has_danger for r, _ in reports)
    return 1 if any_danger else 0


def _report_json(r: Report):
    return {
        "files": r.files, "statements": r.checked, "skipped": len(r.skipped_lines),
        "counts": r.counts(),
        "findings": [{"rule": f.rule, "severity": f.severity, "line": f.line,
                      "table": f.table, "detail": f.detail, "fix": f.fix} for f in r.findings],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="migsentry", description=__doc__)
    parser.add_argument("--version", action="version", version=f"migsentry {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("scan", help="scan .sql migration files (or a directory) for dangerous operations")
    p.add_argument("targets", nargs="+")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scan)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except OSError as exc:
        print(f"migsentry: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
