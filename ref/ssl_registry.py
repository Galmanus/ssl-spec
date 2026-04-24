"""SSL Registry · v5.0

Central index of all SSLs in the Bluewave system.
Scans the agents directory tree + per-tenant overrides.
Validates every SSL against the spec.

Usage:
    python3 -m ssl_registry list                    # all SSLs
    python3 -m ssl_registry list --tenant <tid>     # one tenant
    python3 -m ssl_registry show <agent_name>       # inspect one
    python3 -m ssl_registry compile <agent_name>    # render compiled prompt
    python3 -m ssl_registry audit                   # lint the whole system
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ssl_parser import (
    SSLError, SSLFile, compile_prompt, load_chain, parse, validate,
)
from ssl_linter import lint, LintIssue

# ─── Locations ──────────────────────────────────────────────────────────────

DEFAULT_SHARED = Path(os.environ.get("SSL_SHARED_DIR", "/root/bluewave/braaineer/agents"))
DEFAULT_TENANTS = Path(os.environ.get("SSL_TENANTS_DIR", "/root/bluewave/tenants"))


# ─── Registry entry ─────────────────────────────────────────────────────────

@dataclass
class RegistryEntry:
    name: str
    path: Path
    scope: str           # "shared" | "tenant"
    tenant_id: str | None = None
    version: str = ""
    agent_name: str = ""
    surface: str = ""
    extends: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "scope": self.scope,
            "tenant_id": self.tenant_id,
            "version": self.version,
            "agent_name": self.agent_name,
            "surface": self.surface,
            "extends": self.extends,
            "errors": self.errors,
            "warnings": self.warnings,
        }


# ─── Discovery ──────────────────────────────────────────────────────────────

def discover(shared_dir: Path = DEFAULT_SHARED,
             tenants_dir: Path = DEFAULT_TENANTS) -> list[RegistryEntry]:
    entries: list[RegistryEntry] = []

    # shared SSLs
    if shared_dir.exists():
        for p in sorted(shared_dir.glob("*.ssl")):
            entries.append(_entry_from_path(p, scope="shared"))

    # tenant overrides
    if tenants_dir.exists():
        for tdir in sorted(tenants_dir.iterdir()):
            if not tdir.is_dir():
                continue
            agents_dir = tdir / "agents"
            if not agents_dir.exists():
                continue
            for p in sorted(agents_dir.glob("*.ssl")):
                entries.append(_entry_from_path(p, scope="tenant", tenant_id=tdir.name))

    return entries


def _entry_from_path(p: Path, scope: str, tenant_id: str | None = None) -> RegistryEntry:
    entry = RegistryEntry(name=p.stem, path=p, scope=scope, tenant_id=tenant_id)
    try:
        ssl = parse(p)
        entry.version = ssl.version or "?"
        entry.agent_name = ssl.attributes.get("agent_name", "")
        entry.surface = ssl.attributes.get("surface", "")
        entry.extends = ssl.extends

        # Try full chain validation (may fail if parent isn't resolvable)
        try:
            chain = load_chain(p, search_paths=[DEFAULT_SHARED])
            errors = validate(chain[-1], chain[:-1])
            entry.errors = errors
            issues = lint(chain)
            entry.warnings = [i.message for i in issues if i.level == "warning"]
        except SSLError as e:
            entry.errors = [f"chain load failed: {e.msg}"]

    except SSLError as e:
        entry.errors = [f"parse failed: {e.msg}"]

    return entry


# ─── CLI ────────────────────────────────────────────────────────────────────

def _cmd_list(args) -> int:
    entries = discover()
    if args.tenant:
        entries = [e for e in entries if e.tenant_id == args.tenant]
    if args.scope:
        entries = [e for e in entries if e.scope == args.scope]

    if args.json:
        print(json.dumps([e.as_dict() for e in entries], indent=2, ensure_ascii=False))
        return 0

    if not entries:
        print("(no SSLs found)")
        return 0

    # table
    print(f"{'NAME':<30} {'SCOPE':<8} {'TENANT':<38} {'VER':<5} {'SURFACE':<12} {'STATUS'}")
    print("─" * 120)
    for e in entries:
        status = "OK" if not e.errors else f"ERR({len(e.errors)})"
        if not e.errors and e.warnings:
            status = f"WARN({len(e.warnings)})"
        tenant_short = (e.tenant_id[:8] + "…") if e.tenant_id and len(e.tenant_id) > 8 else (e.tenant_id or "")
        print(
            f"{e.name:<30} {e.scope:<8} {tenant_short:<38} "
            f"{e.version:<5} {e.surface:<12} {status}"
        )
    return 0


def _cmd_show(args) -> int:
    entries = discover()
    candidates = [e for e in entries if e.name == args.name]
    if args.tenant:
        candidates = [e for e in candidates if e.tenant_id == args.tenant]
    if not candidates:
        print(f"no SSL named {args.name!r}", file=sys.stderr)
        return 2
    if len(candidates) > 1:
        print(f"ambiguous: {args.name!r} has multiple matches (use --tenant to disambiguate):", file=sys.stderr)
        for c in candidates:
            print(f"  {c.scope} / {c.tenant_id or '-'}", file=sys.stderr)
        return 2

    entry = candidates[0]
    chain = load_chain(entry.path, search_paths=[DEFAULT_SHARED])
    child = chain[-1]

    print(f"SSL: {entry.name}")
    print(f"path: {entry.path}")
    print(f"scope: {entry.scope}")
    print(f"tenant: {entry.tenant_id or '-'}")
    print(f"version: {child.version}")
    print(f"extends chain: {[f.attributes.get('agent_name') or Path(f.path).stem for f in chain]}")
    print(f"agent_name: {child.attributes.get('agent_name')}")
    print(f"surface: {child.attributes.get('surface')}")
    print(f"language: {child.attributes.get('language', 'en (default)')}")
    print(f"blocks in this file:")
    for b in child.blocks:
        merge = " [merge]" if b.merge else ""
        preview = b.body[:80].replace("\n", " ") + ("…" if len(b.body) > 80 else "")
        print(f"  @{b.name}{merge}  {preview}")
    if entry.errors:
        print(f"\nERRORS ({len(entry.errors)}):")
        for e in entry.errors:
            print(f"  - {e}")
    if entry.warnings:
        print(f"\nWARNINGS ({len(entry.warnings)}):")
        for w in entry.warnings:
            print(f"  - {w}")
    return 0


def _cmd_compile(args) -> int:
    entries = discover()
    candidates = [e for e in entries if e.name == args.name]
    if args.tenant:
        candidates = [e for e in candidates if e.tenant_id == args.tenant]
    if not candidates:
        print(f"no SSL named {args.name!r}", file=sys.stderr)
        return 2
    if len(candidates) > 1:
        print("ambiguous; use --tenant", file=sys.stderr)
        return 2
    entry = candidates[0]
    chain = load_chain(entry.path, search_paths=[DEFAULT_SHARED])
    print(compile_prompt(chain))
    return 0


def _cmd_audit(args) -> int:
    entries = discover()
    total = len(entries)
    clean = sum(1 for e in entries if not e.errors and not e.warnings)
    warn_only = sum(1 for e in entries if not e.errors and e.warnings)
    error_count = sum(1 for e in entries if e.errors)

    print(f"SSL system audit · {total} file(s) total")
    print(f"  clean: {clean}")
    print(f"  warnings only: {warn_only}")
    print(f"  errors: {error_count}")
    print()

    bad = [e for e in entries if e.errors]
    if bad:
        print("ERRORS:")
        for e in bad:
            print(f"  {e.path}")
            for err in e.errors:
                print(f"    - {err}")

    warned = [e for e in entries if not e.errors and e.warnings]
    if warned and args.verbose:
        print("\nWARNINGS:")
        for e in warned:
            print(f"  {e.path}")
            for w in e.warnings:
                print(f"    - {w}")

    return 3 if error_count else 0


def _cli() -> int:
    ap = argparse.ArgumentParser(prog="ssl_registry", description="SSL v5.0 registry")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List all SSLs in the system")
    p_list.add_argument("--tenant", help="Filter to one tenant_id")
    p_list.add_argument("--scope", choices=["shared", "tenant"])
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", help="Inspect one SSL by name")
    p_show.add_argument("name")
    p_show.add_argument("--tenant")
    p_show.set_defaults(func=_cmd_show)

    p_compile = sub.add_parser("compile", help="Render compiled prompt for one SSL")
    p_compile.add_argument("name")
    p_compile.add_argument("--tenant")
    p_compile.set_defaults(func=_cmd_compile)

    p_audit = sub.add_parser("audit", help="Lint the whole system")
    p_audit.add_argument("-v", "--verbose", action="store_true")
    p_audit.set_defaults(func=_cmd_audit)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(_cli())
