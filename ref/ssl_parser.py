"""SSL Parser · v5.0 · with v4 compatibility mode

Canonical parser for Soul Specification Language (SSL).

Strict v5 syntax preferred. Tolerant of v4 syntax when SSL_VERSION is 4.x:
  - @block ~weight    (v4 indentation-based block header)
  - >>> rule          (v4 rule inside indented block)
  - $ var := x $      (v4 inline variable declaration)
  - key : type = val  (v4 typed attribute)
  - @extends name.ssl (v4 extends with suffix)

Library:
    from ssl_parser import parse, SSLError
    ast = parse("path/to/agent.ssl")
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ─── Constants ──────────────────────────────────────────────────────────────

SPEC_VERSION = "5.0"
SUPPORTED_VERSIONS = {"4.0", "4.1", "5.0"}

VALID_SURFACES = {
    "x", "twitter", "linkedin", "telegram", "reels", "tiktok", "shorts",
    "briefing", "chat", "multi",
}

CANONICAL_BLOCK_ORDER = [
    "identity", "doctrine", "principles", "voice", "knowledge",
    "response_modes", "commitments", "limits", "context_snapshot",
    "examples", "rhythm", "tools", "vow",
]


# ─── AST ────────────────────────────────────────────────────────────────────

@dataclass
class Block:
    name: str
    body: str
    merge: bool = False
    line: int = 0


@dataclass
class SSLFile:
    path: str
    version: str = ""
    extends: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    blocks: list[Block] = field(default_factory=list)
    raw: str = ""

    def get_block(self, name: str) -> Block | None:
        for b in self.blocks:
            if b.name == name and not b.merge:
                return b
        return None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["blocks"] = [{"name": b.name, "body": b.body, "merge": b.merge, "line": b.line}
                       for b in self.blocks]
        del d["raw"]
        return d

    @property
    def is_v4(self) -> bool:
        return self.version.startswith("4.")

    @property
    def is_abstract(self) -> bool:
        """Base templates (no agent_name, intended to be extended)."""
        stem = Path(self.path).stem
        return stem.startswith("base_") and not self.attributes.get("agent_name")


# ─── Errors ─────────────────────────────────────────────────────────────────

class SSLError(Exception):
    def __init__(self, msg: str, line: int = 0, path: str = ""):
        self.msg = msg
        self.line = line
        self.path = path
        super().__init__(self.render())

    def render(self) -> str:
        loc = f"{self.path}:{self.line}" if self.path else f"line {self.line}"
        return f"SSL error at {loc}: {self.msg}"


# ─── Regexes ────────────────────────────────────────────────────────────────

_RE_LINE_COMMENT = re.compile(r"//.*$", re.M)
_RE_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)

_RE_VERSION = re.compile(r"^\s*SSL_VERSION\s*:=\s*([\d.]+)\s*$")
_RE_EXTENDS = re.compile(r"^\s*@extends\s+([a-zA-Z_][\w]*)(?:\.ssl)?\s*$")
_RE_ATTR_V5 = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*:=\s*(.+?)\s*$")
_RE_ATTR_V4_TYPED = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*:\s*(string|int|float|bool|list|dict)\s*=\s*(.+?)\s*$")
_RE_RESERVED_ATTR = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*:=\s*(.+?)\s*$")

_RE_BLOCK_V5_OPEN = re.compile(r"^\s*(@merge\s+)?@([a-z_][a-z0-9_]*)\s*\{\s*$")
_RE_BLOCK_V5_INLINE = re.compile(r"^\s*(@merge\s+)?@([a-z_][a-z0-9_]*)\s*\{(.*)\}\s*$")
_RE_BLOCK_V4_HEADER = re.compile(r"^@([a-z_][a-z0-9_]*)\s*(?:~[\d.]+)?\s*$")
_RE_INLINE_VAR_V4 = re.compile(r"^\s*\$\s*(.+?)\s*\$\s*$")


def _strip_block_comments(src: str) -> str:
    return _RE_BLOCK_COMMENT.sub("", src)


def _strip_line_comments(line: str) -> str:
    return _RE_LINE_COMMENT.sub("", line)


# ─── Value parsing ──────────────────────────────────────────────────────────

def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw == "null":
        return None
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        inner = raw[1:-1]
        return (inner.replace("\\n", "\n").replace("\\t", "\t")
                     .replace('\\"', '"').replace("\\\\", "\\"))
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_parse_value(p) for p in _split_array_items(inner)]
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        pass
    if re.match(r"^[a-zA-Z_][\w.-]*$", raw):
        return raw
    return raw


def _split_array_items(inner: str) -> list[str]:
    parts, buf, depth, in_str = [], [], 0, False
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == '"' and (i == 0 or inner[i - 1] != "\\"):
            in_str = not in_str
            buf.append(ch)
        elif ch in "[{" and not in_str:
            depth += 1
            buf.append(ch)
        elif ch in "]}" and not in_str:
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0 and not in_str:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        parts.append("".join(buf).strip())
    return parts


# ─── Main parser ────────────────────────────────────────────────────────────

def parse(path: str | Path) -> SSLFile:
    path = Path(path)
    if not path.exists():
        raise SSLError(f"file not found: {path}", path=str(path))
    return parse_string(path.read_text(encoding="utf-8"), str(path))


def parse_string(raw: str, path: str = "<string>") -> SSLFile:
    ssl = SSLFile(path=path, raw=raw)
    src = _strip_block_comments(raw)
    lines = src.split("\n")

    # First, detect version to pick parser mode
    for ln in lines:
        m = _RE_VERSION.match(ln)
        if m:
            ssl.version = m.group(1)
            break

    is_v4_mode = ssl.version.startswith("4.") if ssl.version else False

    i = 0
    while i < len(lines):
        raw_line = lines[i]
        # strip trailing line comments only (preserve content before //)
        line = _strip_line_comments(raw_line)
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        # version
        m = _RE_VERSION.match(line)
        if m:
            ssl.version = m.group(1)
            if ssl.version not in SUPPORTED_VERSIONS:
                raise SSLError(f"unsupported SSL_VERSION {ssl.version}", i + 1, path)
            i += 1
            continue

        # @extends
        m = _RE_EXTENDS.match(line)
        if m:
            if ssl.extends:
                raise SSLError("duplicate @extends declaration", i + 1, path)
            ssl.extends = m.group(1)
            i += 1
            continue

        # v5 inline block
        m = _RE_BLOCK_V5_INLINE.match(line)
        if m:
            merge = bool(m.group(1))
            name = m.group(2)
            body = m.group(3).strip()
            ssl.blocks.append(Block(name=name, body=body, merge=merge, line=i + 1))
            i += 1
            continue

        # v5 block open (multi-line)
        m = _RE_BLOCK_V5_OPEN.match(line)
        if m:
            merge = bool(m.group(1))
            name = m.group(2)
            open_line = i + 1
            i += 1
            body_lines: list[str] = []
            depth = 1
            terminated = False
            while i < len(lines):
                cur = lines[i]
                cur_stripped = cur.strip()
                if cur_stripped == "}":
                    depth -= 1
                    if depth == 0:
                        terminated = True
                        break
                    body_lines.append(cur)
                else:
                    if "{" in cur and "}" not in cur:
                        depth += 1
                    body_lines.append(cur)
                i += 1
            if not terminated:
                raise SSLError(
                    f"unterminated block @{name} (opened on line {open_line})",
                    open_line, path,
                )
            body = "\n".join(body_lines).strip()
            ssl.blocks.append(Block(name=name, body=body, merge=merge, line=open_line))
            i += 1
            continue

        # v4 block header (no braces, indentation-based)
        m = _RE_BLOCK_V4_HEADER.match(line)
        if m and is_v4_mode:
            name = m.group(1)
            open_line = i + 1
            i += 1
            body_lines: list[str] = []
            while i < len(lines):
                cur = lines[i]
                cur_stripped = cur.strip()
                if not cur_stripped:
                    body_lines.append("")
                    i += 1
                    continue
                # line starts with whitespace? continues block
                if cur.startswith((" ", "\t")):
                    content = cur_stripped
                    # convert `>>> rule` to bullet
                    if content.startswith(">>>"):
                        content = "- " + content[3:].lstrip()
                    # `$ var := x $` stays as-is (legacy var)
                    body_lines.append(content)
                    i += 1
                    continue
                # top-level line → close block
                break
            while body_lines and not body_lines[-1].strip():
                body_lines.pop()
            body = "\n".join(body_lines).strip()
            ssl.blocks.append(Block(name=name, body=body, merge=False, line=open_line))
            continue

        # v5 attribute
        m = _RE_ATTR_V5.match(line)
        if m:
            key, raw_val = m.group(1), m.group(2)
            ssl.attributes[key] = _parse_value(raw_val)
            i += 1
            continue

        # v4 typed attribute
        m = _RE_ATTR_V4_TYPED.match(line)
        if m and is_v4_mode:
            key, tp, raw_val = m.group(1), m.group(2), m.group(3)
            val = _parse_value(raw_val)
            if tp == "string" and isinstance(val, str) and not val.startswith('"'):
                # already string
                pass
            ssl.attributes[key] = val
            i += 1
            continue

        # uppercase reserved
        m = _RE_RESERVED_ATTR.match(line)
        if m:
            ssl.attributes[m.group(1)] = _parse_value(m.group(2))
            i += 1
            continue

        # v4 inline var `$ x := y $`
        m = _RE_INLINE_VAR_V4.match(line)
        if m and is_v4_mode:
            # preserve as comment-like note in a synthetic block
            i += 1
            continue

        # v4 tolerant fallback: skip unknown lines silently when in v4 mode
        if is_v4_mode:
            i += 1
            continue

        raise SSLError(f"unexpected line: {line.rstrip()!r}", i + 1, path)

    return ssl


# ─── Validation ─────────────────────────────────────────────────────────────

def validate(ssl: SSLFile, chain: list[SSLFile] | None = None) -> list[str]:
    errors: list[str] = []
    chain = chain or []

    if not ssl.version:
        errors.append("missing SSL_VERSION declaration")
    elif ssl.version not in SUPPORTED_VERSIONS:
        errors.append(f"unsupported SSL_VERSION {ssl.version}")

    # Abstract bases + v4 files are exempt from strict top-level attrs
    if not ssl.is_abstract and not ssl.is_v4:
        merged_attrs: dict[str, Any] = {}
        for f in chain + [ssl]:
            merged_attrs.update(f.attributes)

        name = merged_attrs.get("agent_name")
        if not name or not isinstance(name, str):
            errors.append("missing required attribute: agent_name (string)")

        surface = merged_attrs.get("surface")
        if not surface:
            errors.append("missing required attribute: surface")
        elif surface not in VALID_SURFACES:
            errors.append(f"invalid surface {surface!r}; must be one of {sorted(VALID_SURFACES)}")

    # duplicate block check
    seen: set[str] = set()
    for b in ssl.blocks:
        if b.merge:
            continue
        if b.name in seen:
            errors.append(f"duplicate non-@merge block @{b.name} (line {b.line})")
        seen.add(b.name)

    # identity required always; voice required for v5 only (v4 used @style/@craft/other names)
    if not ssl.is_abstract:
        full_chain = chain + [ssl]
        if not _chain_has_block(full_chain, "identity"):
            errors.append("missing @identity block (required by spec §7.1)")
        if not ssl.is_v4 and not _chain_has_block(full_chain, "voice"):
            errors.append("missing @voice block (required by spec §7.2)")

    return errors


def _chain_has_block(chain: list[SSLFile], block: str) -> bool:
    return any(f.get_block(block) for f in chain)


# ─── Loader ─────────────────────────────────────────────────────────────────

def load_chain(path: str | Path, search_paths: list[Path] | None = None) -> list[SSLFile]:
    path = Path(path)
    search_paths = search_paths or []
    # Always include the parent dir + AGENTS_DIR default
    search_paths = list(search_paths)
    search_paths.insert(0, path.parent)
    # Add the shared agents dir as fallback
    for default in [Path("/root/bluewave/braaineer/agents"), Path(__file__).parent]:
        if default.exists() and default not in search_paths:
            search_paths.append(default)

    chain: list[SSLFile] = []
    visited: set[str] = set()

    def _load(p: Path) -> None:
        key = str(p.resolve())
        if key in visited:
            raise SSLError(f"cyclic @extends involving {p}", path=str(p))
        visited.add(key)
        ssl = parse(p)
        if ssl.extends:
            parent = _resolve(ssl.extends, search_paths)
            if parent is None:
                raise SSLError(
                    f"cannot resolve @extends {ssl.extends!r} "
                    f"(searched: {[str(s) for s in search_paths]})",
                    path=str(p),
                )
            _load(parent)
        chain.append(ssl)

    _load(path)
    return chain


def _resolve(name: str, search_paths: list[Path]) -> Path | None:
    for base in search_paths:
        for cand in (f"{name}.ssl", f"{name}_v5.ssl", f"{name}_v4.ssl"):
            p = base / cand
            if p.exists():
                return p
    return None


# ─── Compilation ────────────────────────────────────────────────────────────

def compile_prompt(chain: list[SSLFile], runtime: dict[str, Any] | None = None) -> str:
    runtime = runtime or {}
    merged = _merge_chain(chain)
    out: list[str] = []

    agent_name = merged.attributes.get("agent_name", "Agent")
    principal = runtime.get("principal") or merged.attributes.get("principal", "the operator")
    out.append(f"You are {agent_name}, operating on behalf of {principal}.\n")

    if runtime.get("tenant_context"):
        out.append("@tenant_context\n" + runtime["tenant_context"].strip() + "\n")
    if runtime.get("knowledge_base"):
        out.append("@knowledge_base\n<kb>\n" + runtime["knowledge_base"].strip() + "\n</kb>\n")

    rendered: set[str] = set()
    for name in CANONICAL_BLOCK_ORDER:
        body = _collect_block(chain, name)
        if body:
            out.append(f"@{name}\n{body}\n")
            rendered.add(name)

    for f in chain:
        for b in f.blocks:
            if b.name in rendered or b.name in CANONICAL_BLOCK_ORDER:
                continue
            body = _collect_block(chain, b.name)
            if body:
                out.append(f"@{b.name}\n{body}\n")
                rendered.add(b.name)

    return "\n".join(out)


def _merge_chain(chain: list[SSLFile]) -> SSLFile:
    merged = SSLFile(path="<merged>")
    merged.version = chain[-1].version if chain else SPEC_VERSION
    for f in chain:
        merged.attributes.update(f.attributes)
    return merged


def _collect_block(chain: list[SSLFile], name: str) -> str:
    body = ""
    for f in chain:
        for b in f.blocks:
            if b.name != name:
                continue
            if b.merge:
                body = (body + "\n\n" + b.body).strip() if body else b.body
            else:
                body = b.body
    return body


# ─── CLI ────────────────────────────────────────────────────────────────────

def _cli() -> int:
    ap = argparse.ArgumentParser(prog="ssl_parser")
    ap.add_argument("path")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--compile", action="store_true")
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--search", action="append", default=[])
    args = ap.parse_args()

    try:
        chain = load_chain(args.path, search_paths=[Path(s) for s in args.search])
        child = chain[-1]
    except SSLError as e:
        print(f"PARSE ERROR: {e}", file=sys.stderr)
        return 2

    if not args.no_validate:
        errors = validate(child, chain[:-1])
        if errors:
            print(f"VALIDATION FAILED ({len(errors)}):", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 3

    if args.compile:
        print(compile_prompt(chain))
        return 0
    if args.json:
        print(json.dumps(child.as_dict(), indent=2, ensure_ascii=False))
        return 0

    print(f"SSL v{child.version} · {args.path}")
    print(f"  agent_name: {child.attributes.get('agent_name', '(inherited)')}")
    print(f"  surface: {child.attributes.get('surface', '(inherited)')}")
    print(f"  extends: {child.extends or '(none)'}")
    print(f"  chain depth: {len(chain)}")
    print(f"  abstract: {child.is_abstract}")
    print(f"  blocks ({len(child.blocks)}):")
    for b in child.blocks:
        mark = " [merge]" if b.merge else ""
        preview = b.body[:60].replace("\n", " ") + ("…" if len(b.body) > 60 else "")
        print(f"    @{b.name}{mark} — {preview}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
