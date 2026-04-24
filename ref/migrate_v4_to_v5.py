"""SSL migration tool · v4.x → v5.0

Reads a v4 SSL file (indentation-based blocks, ~weight annotations) and emits
a v5-compliant file with braced blocks, clean @extends, and SSL_VERSION := 5.0.

Usage:
    python3 migrate_v4_to_v5.py <file.ssl>              # preview to stdout
    python3 migrate_v4_to_v5.py --write <file.ssl>      # overwrite in place
    python3 migrate_v4_to_v5.py --write --backup <file.ssl>  # write + .bak
    python3 migrate_v4_to_v5.py --all /root/bluewave/braaineer/agents /root/bluewave/tenants

Safe to run multiple times — if the file already declares SSL_VERSION := 5.0,
the tool skips it.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

_RE_BLOCK_V4_OPEN = re.compile(r"^@([a-z_][a-z0-9_]*)\s*(?:~[\d.]+)?\s*\{?\s*$")
_RE_EXTENDS = re.compile(r"^@extends\s+([a-zA-Z_][\w]*)(?:\.ssl)?\s*$")
_RE_BLOCK_CLOSE = re.compile(r"^\}\s*$")
_RE_VERSION = re.compile(r"^SSL_VERSION\s*:=\s*([\d.]+)\s*$")
_RE_ATTR = re.compile(r"^([a-z_][a-z0-9_]*)\s*:\s*([^=].*)$")  # v4 uses : not :=
_RE_ATTR_TYPED = re.compile(r"^([a-z_][a-z0-9_]*)\s*:\s*(string|int|float|bool)\s*=\s*(.+)$")
_RE_RESERVED_ATTR = re.compile(r"^([A-Z_][A-Z0-9_]*)\s*:=\s*(.+)$")
_RE_INDENTED = re.compile(r"^\s{2,}(.+)$")  # indented content under v4 blocks


def _is_line_comment(line: str) -> bool:
    return line.strip().startswith("//")


def _is_block_comment_start(line: str) -> bool:
    return "/*" in line and "*/" not in line


def migrate(raw: str) -> str:
    """Return v5-compliant SSL text from a v4 input."""
    lines = raw.split("\n")
    out: list[str] = []
    i = 0
    in_block = False
    in_block_comment = False

    # Check if already v5
    for line in lines:
        m = _RE_VERSION.match(line.strip())
        if m and m.group(1) == "5.0":
            return raw  # already migrated

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # comments pass through
        if in_block_comment:
            out.append(line)
            if "*/" in line:
                in_block_comment = False
            i += 1
            continue
        if _is_block_comment_start(line):
            out.append(line)
            in_block_comment = True
            i += 1
            continue
        if _is_line_comment(line) or stripped == "":
            out.append(line)
            i += 1
            continue

        # SSL_VERSION
        m = _RE_VERSION.match(stripped)
        if m:
            out.append("SSL_VERSION := 5.0")
            i += 1
            continue

        # @extends (normalize: strip .ssl)
        m = _RE_EXTENDS.match(stripped)
        if m:
            out.append(f"@extends {m.group(1)}")
            i += 1
            continue

        # @block opener (v4: indentation-based; v5: braced)
        m = _RE_BLOCK_V4_OPEN.match(stripped)
        if m and "{" not in line:
            block_name = m.group(1)
            out.append(f"@{block_name} {{")
            in_block = True
            i += 1
            # consume indented content until next top-level non-blank line
            block_body: list[str] = []
            while i < len(lines):
                inner = lines[i]
                inner_stripped = inner.strip()
                # blank line inside block → keep
                if not inner_stripped:
                    block_body.append("")
                    i += 1
                    continue
                # line-comment inside block
                if _is_line_comment(inner):
                    block_body.append("  " + inner_stripped)
                    i += 1
                    continue
                # still indented? continues the block
                if inner.startswith("  ") or inner.startswith("\t"):
                    content = inner_stripped
                    # convert `>>> rule` to bullet
                    if content.startswith(">>> "):
                        content = "- " + content[4:]
                    elif content.startswith(">>>"):
                        content = "- " + content[3:]
                    # convert `$ var := value $` inline vars to comment
                    if content.startswith("$") and content.endswith("$"):
                        content = f"// legacy v4 var: {content.strip('$').strip()}"
                    # convert `key : type = value` to `key: value`
                    tm = _RE_ATTR_TYPED.match(content)
                    if tm:
                        content = f"{tm.group(1)}: {tm.group(3)}"
                    block_body.append("  " + content)
                    i += 1
                    continue
                # next top-level thing → close block
                break
            # trim trailing blank lines from body
            while block_body and not block_body[-1].strip():
                block_body.pop()
            out.extend(block_body)
            out.append("}")
            in_block = False
            continue

        # reserved-case attribute (SSL_VERSION handled above; leave others)
        m = _RE_RESERVED_ATTR.match(stripped)
        if m:
            out.append(stripped)
            i += 1
            continue

        # v4 typed attribute at top level
        m = _RE_ATTR_TYPED.match(stripped)
        if m:
            key, tp, val = m.group(1), m.group(2), m.group(3).strip()
            # keep value as-is; migrate to := form
            if tp == "string" and not (val.startswith('"') and val.endswith('"')):
                val = f'"{val}"'
            out.append(f"{key} := {val}")
            i += 1
            continue

        # v4 untyped attribute (`key : value`)
        m = _RE_ATTR.match(stripped)
        if m:
            key, val = m.group(1), m.group(2).strip()
            # decide if val looks like a number/bool
            if val in ("true", "false", "null"):
                pass
            elif re.match(r"^-?\d+(\.\d+)?$", val):
                pass
            else:
                val = f'"{val}"' if not (val.startswith('"') or val.startswith("[")) else val
            out.append(f"{key} := {val}")
            i += 1
            continue

        # unknown line — preserve as comment so nothing is lost
        out.append(f"// [v4-migration] preserved: {line.rstrip()}")
        i += 1

    # ensure SSL_VERSION is at top
    result = "\n".join(out)
    if "SSL_VERSION := 5.0" not in result:
        result = "SSL_VERSION := 5.0\n" + result
    return result


def migrate_file(path: Path, write: bool = False, backup: bool = False) -> tuple[bool, str]:
    """Migrate one file. Returns (changed, output)."""
    raw = path.read_text(encoding="utf-8")
    new = migrate(raw)
    changed = new != raw

    if write and changed:
        if backup:
            shutil.copy(path, path.with_suffix(path.suffix + ".v4.bak"))
        path.write_text(new, encoding="utf-8")

    return changed, new


def migrate_tree(roots: list[Path], write: bool, backup: bool) -> int:
    total = 0
    changed = 0
    for root in roots:
        if not root.exists():
            print(f"skip: {root} does not exist", file=sys.stderr)
            continue
        for p in root.rglob("*.ssl"):
            total += 1
            try:
                c, _ = migrate_file(p, write=write, backup=backup)
                if c:
                    changed += 1
                    print(f"{'MIGRATED' if write else 'WOULD MIGRATE'}: {p}")
                else:
                    print(f"already v5: {p}")
            except Exception as e:
                print(f"FAILED {p}: {e}", file=sys.stderr)
    print(f"\n{changed} of {total} files {'migrated' if write else 'would be migrated'}")
    return 0


def _cli() -> int:
    ap = argparse.ArgumentParser(prog="migrate_v4_to_v5")
    ap.add_argument("paths", nargs="+", help="SSL file or directory")
    ap.add_argument("--write", action="store_true", help="Write changes in place (default: dry run)")
    ap.add_argument("--backup", action="store_true", help="Save .v4.bak alongside changed files")
    ap.add_argument("--all", action="store_true", help="Recurse directories")
    args = ap.parse_args()

    if args.all:
        return migrate_tree([Path(p) for p in args.paths], write=args.write, backup=args.backup)

    for raw_path in args.paths:
        p = Path(raw_path)
        if p.is_dir():
            return migrate_tree([p], write=args.write, backup=args.backup)
        c, out = migrate_file(p, write=args.write, backup=args.backup)
        if args.write:
            print(f"{'migrated' if c else 'unchanged'}: {p}")
        else:
            print(out)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
