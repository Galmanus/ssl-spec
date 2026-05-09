"""SSL Parser · v6.0 · with v5/v4 compatibility

Canonical parser for Soul Specification Language (SSL).

v6 enforced features (when SSL_VERSION := 6.0):
  - typed attributes with parse-time validation
  - weights required on every block (~float in [0.0, 1.0])
  - weight-ordered compilation (descending; constitutional first)
  - context pressure: drop low-weight blocks when over MAX_PROMPT_TOKENS
  - canonical block weight floors (vow=1.0, identity=0.90, ...)
  - surface-conditional blocks @block[surface=twitter,linkedin]
  - conditional blocks @block[when=expr]
  - variable interpolation {attr_name} in block bodies
  - @runtime declaration zone for runtime-injected variables
  - @test blocks stripped from compiled output
  - same-name block collapse (max weight, body concatenation for @merge)

v5 (SSL_VERSION := 5.0): brace-delimited blocks, weights optional (default 0.7
warning), no parse-time type enforcement, surface filter inactive unless surface
qualifiers present, interpolation only if {x} syntax present.

v4 (SSL_VERSION := 4.0/4.1): indentation-based, untyped attrs inside blocks,
$...$ vars dropped, >>> rules converted to bullets — all preserved.

Library:
    from ssl_parser import parse, compile_prompt, SSLError
    ast = parse("path/to/agent.ssl")
    out = compile_prompt(load_chain(path), runtime={"surface": "twitter", ...})
"""
from __future__ import annotations

import argparse
import ast as _pyast
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ─── Constants ──────────────────────────────────────────────────────────────

SPEC_VERSION = "6.0"
SUPPORTED_VERSIONS = {"4.0", "4.1", "5.0", "6.0"}

VALID_SURFACES = {
    "x", "twitter", "linkedin", "telegram", "reels", "tiktok", "shorts",
    "briefing", "chat", "multi", "api", "email", "slack",
}

CANONICAL_BLOCK_ORDER = [
    "identity", "doctrine", "principles", "voice", "knowledge",
    "response_modes", "commitments", "limits", "context_snapshot",
    "examples", "rhythm", "tools", "vow",
    # v6 additions (not strictly ordered — fall back to weight order)
    "behavior", "fitness", "memory", "events", "decision_audit",
    "safeguards", "metacognition", "chain_of_thought", "adversarial",
    "first_principles", "put_auto", "synthesis", "compression", "proactive",
    "learning", "tests",
]

# v6: canonical blocks have hard weight floors. Used for:
#   1. Parse-time validation in v6 mode (declaring vow ~0.5 → error)
#   2. Context-pressure protection (a vow can never be dropped)
BLOCK_WEIGHT_FLOORS: dict[str, float] = {
    "vow": 1.0,
    "identity": 0.90,
    "safeguards": 0.85,
    "voice": 0.80,
    "limits": 0.80,
}

# v6: blocks at or above this weight are NEVER dropped under context pressure.
PROTECTED_FLOOR = 0.80

DEFAULT_MAX_PROMPT_TOKENS = 6000  # ~24000 chars · §3.2 spec default
CHARS_PER_TOKEN_ESTIMATE = 4       # rough; we don't ship tiktoken here

# ─── AST ────────────────────────────────────────────────────────────────────

@dataclass
class Block:
    name: str
    body: str = ""              # post-interpolation
    body_raw: str = ""          # pre-interpolation (debug + re-render)
    weight: float = 0.7         # default for v5/v4 compat (warning emitted)
    merge: bool = False
    surface: list[str] = field(default_factory=list)  # [] = no filter
    condition: str | None = None
    is_test: bool = False
    line: int = 0


@dataclass
class Attribute:
    key: str
    value: Any
    type_declared: str | None = None
    line: int = 0


@dataclass
class SSLFile:
    path: str
    version: str = ""
    extends: str | None = None
    mixins: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    attribute_types: dict[str, str] = field(default_factory=dict)
    runtime_decls: dict[str, str] = field(default_factory=dict)
    blocks: list[Block] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw: str = ""

    def get_block(self, name: str) -> Block | None:
        for b in self.blocks:
            if b.name == name and not b.merge and not b.is_test:
                return b
        return None

    def as_dict(self) -> dict:
        d = asdict(self)
        del d["raw"]
        return d

    @property
    def is_v4(self) -> bool:
        return self.version.startswith("4.")

    @property
    def is_v5(self) -> bool:
        return self.version.startswith("5.")

    @property
    def is_v6(self) -> bool:
        return self.version.startswith("6.")

    @property
    def is_abstract(self) -> bool:
        if self.attributes.get("abstract") is True:
            return True
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


class SSLParseError(SSLError): pass
class SSLTypeError(SSLError): pass
class SSLRefError(SSLError): pass
class SSLWeightError(SSLError): pass
class SSLConditionError(SSLError): pass


# ─── Regexes ────────────────────────────────────────────────────────────────

_RE_LINE_COMMENT = re.compile(r"//.*$", re.M)
_RE_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)

_RE_VERSION = re.compile(r"^\s*SSL_VERSION\s*:=\s*([\d.]+)\s*$")
_RE_EXTENDS = re.compile(r"^\s*@extends\s+([a-zA-Z_][\w]*)(?:\.ssl)?\s*$")
_RE_MIXIN = re.compile(r"^\s*@mixin\s+([a-zA-Z_][\w]*)(?:\.ssl)?\s*$")
_RE_ATTR_V5 = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*:=\s*(.+?)\s*$")
_RE_ATTR_TYPED = re.compile(
    r"^\s*([a-z_][a-z0-9_]*)\s*:\s*"
    r"(string|id|surface|semver|float|int|bool|list\[\w+\]|enum\[[^\]]+\]|tool|path|url|json)"
    r"\s*=\s*(.+?)\s*$"
)
_RE_RESERVED_ATTR = re.compile(r"^\s*([A-Z_][A-Z0-9_]*)\s*:=\s*(.+?)\s*$")

# v6/v5 block headers (brace-delimited)
# matches: [@merge] @name [[qualifiers]] [~weight] {
_RE_BLOCK_OPEN = re.compile(
    r"^\s*(@merge\s+)?@([a-z_][a-z0-9_]*)"
    r"(?:\[([^\]]+)\])?"
    r"\s*(?:~([\d.]+))?"
    r"\s*\{\s*$"
)
_RE_BLOCK_INLINE = re.compile(
    r"^\s*(@merge\s+)?@([a-z_][a-z0-9_]*)"
    r"(?:\[([^\]]+)\])?"
    r"\s*(?:~([\d.]+))?"
    r"\s*\{(.*)\}\s*$"
)
# v6 @test blocks: @test "description" ~weight { ... }
_RE_TEST_OPEN = re.compile(
    r'^\s*@test\s+"([^"]+)"\s*(?:~([\d.]+))?\s*\{\s*$'
)
_RE_TEST_INLINE = re.compile(
    r'^\s*@test\s+"([^"]+)"\s*(?:~([\d.]+))?\s*\{(.*)\}\s*$'
)
# v6 @runtime { ... } declaration zone
_RE_RUNTIME_OPEN = re.compile(r'^\s*@runtime\s*\{\s*$')
_RE_RUNTIME_DECL = re.compile(
    r"^\s*([a-z_][a-z0-9_]*)\s*:\s*"
    r"(string|id|surface|semver|float|int|bool|tool|path|url|json|list\[\w+\])"
    r"\s*$"
)

# v4 (indentation-based) — kept for backward compat
_RE_BLOCK_V4_HEADER = re.compile(r"^@([a-z_][a-z0-9_]*)\s*(?:~[\d.]+)?\s*$")
_RE_INLINE_VAR_V4 = re.compile(r"^\s*\$\s*(.+?)\s*\$\s*$")

# Variable interpolation: {name} or {name.sub} (escaped: \{ \})
_RE_INTERP = re.compile(r"(?<!\\)\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}")


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


# ─── Type validation (v6) ───────────────────────────────────────────────────

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_URL_RE = re.compile(r"^https?://[^\s]+$")


def _validate_typed_value(key: str, type_decl: str, value: Any, line: int, path: str) -> Any:
    """Validate value against declared type. Return coerced value or raise."""
    t = type_decl
    if t == "string":
        if not isinstance(value, str):
            raise SSLTypeError(f"{key}: expected string, got {type(value).__name__}", line, path)
        return value
    if t == "id":
        if not isinstance(value, str) or not _ID_RE.match(value):
            raise SSLTypeError(f"{key}: id must match [a-z][a-z0-9_-]{{0,63}}, got {value!r}", line, path)
        return value
    if t == "surface":
        if value not in VALID_SURFACES:
            raise SSLTypeError(
                f"{key}: surface must be one of {sorted(VALID_SURFACES)}, got {value!r}",
                line, path,
            )
        return value
    if t == "semver":
        if not isinstance(value, str) or not _SEMVER_RE.match(value):
            raise SSLTypeError(f"{key}: semver must be X.Y.Z, got {value!r}", line, path)
        return value
    if t == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            raise SSLTypeError(f"{key}: float expected, got {value!r}", line, path)
    if t == "int":
        try:
            v = int(value)
            if isinstance(value, float) and not value.is_integer():
                raise ValueError()
            return v
        except (TypeError, ValueError):
            raise SSLTypeError(f"{key}: int expected, got {value!r}", line, path)
    if t == "bool":
        if not isinstance(value, bool):
            raise SSLTypeError(f"{key}: bool expected, got {value!r}", line, path)
        return value
    if t.startswith("list["):
        inner = t[5:-1].strip()
        if not isinstance(value, list):
            raise SSLTypeError(f"{key}: list expected, got {type(value).__name__}", line, path)
        return [_validate_typed_value(f"{key}[]", inner, v, line, path) for v in value]
    if t.startswith("enum["):
        allowed = [s.strip() for s in t[5:-1].split(",")]
        if value not in allowed:
            raise SSLTypeError(f"{key}: enum value must be one of {allowed}, got {value!r}", line, path)
        return value
    if t == "tool":
        # Validation against tool registry happens later (registry is runtime concern)
        if not isinstance(value, str):
            raise SSLTypeError(f"{key}: tool name must be string, got {value!r}", line, path)
        return value
    if t == "path":
        if not isinstance(value, str) or not value.startswith("/"):
            raise SSLTypeError(f"{key}: path must be absolute, got {value!r}", line, path)
        return value
    if t == "url":
        if not isinstance(value, str) or not _URL_RE.match(value):
            raise SSLTypeError(f"{key}: url must match http(s)://..., got {value!r}", line, path)
        return value
    if t == "json":
        # Accept any JSON-serializable value
        try:
            json.dumps(value)
            return value
        except TypeError:
            raise SSLTypeError(f"{key}: not JSON-serializable", line, path)
    raise SSLTypeError(f"{key}: unknown type {t!r}", line, path)


# ─── @when expression evaluator ─────────────────────────────────────────────

def _eval_when(expr: str, scope: dict) -> bool:
    """Safe AST eval of a when= expression against attribute+runtime scope.

    Allowed: literals, identifier lookups (via runtime/attrs), comparison
    operators, boolean operators, !/not. Anything else → ConditionError.
    """
    expr = expr.strip()
    if not expr:
        return True
    if expr.lower() == "true":
        return True
    if expr.lower() == "false":
        return False

    # Replace identifiers with repr of their resolved scope value.
    # Identifiers preserved: True, False, None, and, or, not, in.
    PRESERVE = {"True", "False", "None", "and", "or", "not", "in"}

    def _resolve(name: str) -> Any:
        if "." in name:
            cur: Any = scope
            for part in name.split("."):
                if isinstance(cur, dict):
                    cur = cur.get(part)
                else:
                    return None
            return cur
        return scope.get(name)

    def _sub(m: re.Match) -> str:
        token = m.group(0)
        if token in PRESERVE:
            return token
        v = _resolve(token)
        return repr(v)

    # Convert ! / && / || to Python ops first
    py_expr = expr.replace("&&", " and ").replace("||", " or ")
    py_expr = re.sub(r"!\s*=", "__NEQ__", py_expr)  # protect !=
    py_expr = re.sub(r"!", " not ", py_expr)
    py_expr = py_expr.replace("__NEQ__", "!=")
    # Substitute identifiers
    py_expr = re.sub(r"\b[a-zA-Z_][a-zA-Z0-9_.]*\b", _sub, py_expr)

    try:
        tree = _pyast.parse(py_expr, mode="eval")
    except SyntaxError as e:
        raise SSLConditionError(f"malformed when= expression {expr!r}: {e}")

    allowed_nodes = (
        _pyast.Expression, _pyast.Compare, _pyast.BoolOp, _pyast.UnaryOp,
        _pyast.And, _pyast.Or, _pyast.Not, _pyast.Eq, _pyast.NotEq,
        _pyast.Lt, _pyast.Gt, _pyast.LtE, _pyast.GtE, _pyast.In, _pyast.NotIn,
        _pyast.Constant, _pyast.Tuple, _pyast.List, _pyast.Load, _pyast.Name,
    )
    for node in _pyast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise SSLConditionError(
                f"unsafe ast node {type(node).__name__} in when= expression {expr!r}"
            )

    return bool(eval(
        compile(tree, "<when>", mode="eval"),
        {"__builtins__": {}},
        {"True": True, "False": False, "None": None},
    ))


# ─── Variable interpolation ─────────────────────────────────────────────────

def _interpolate(template: str, scope: dict, *, strict: bool, line: int, path: str) -> str:
    """Substitute {name} / {name.sub} from scope. Strict=True raises on missing."""
    def _resolve(name: str) -> str | None:
        cur: Any = scope
        for part in name.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
            if cur is None:
                return None
        return cur

    def _sub(m: re.Match) -> str:
        name = m.group(1)
        v = _resolve(name)
        if v is None:
            if strict:
                raise SSLRefError(f"unknown interpolation reference {{{name}}}", line, path)
            return m.group(0)  # leave as-is in non-strict mode
        return str(v)

    out = _RE_INTERP.sub(_sub, template)
    # un-escape \{ \}
    out = out.replace("\\{", "{").replace("\\}", "}")
    return out


# ─── Qualifier parser ───────────────────────────────────────────────────────

def _parse_qualifiers(qstr: str | None) -> tuple[list[str], str | None]:
    """Parse `[surface=twitter,linkedin when=foo==bar]` style qualifiers.

    Returns (surface_list, when_condition). Empty surface_list = no filter.
    """
    if not qstr:
        return [], None
    surfaces: list[str] = []
    when: str | None = None
    # Split on whitespace, but preserve when= which may contain spaces
    # Heuristic: surface=... is always comma-separated single tokens; when= grabs the rest
    # Walk tokens
    tokens: list[str] = []
    buf = ""
    in_eq = False
    for ch in qstr:
        if ch == " " and not in_eq:
            if buf:
                tokens.append(buf)
                buf = ""
            continue
        if ch == "=":
            in_eq = True
        buf += ch
    if buf:
        tokens.append(buf)

    # Re-join in case `when=a == b` got split: combine tokens until next `key=`
    # Simpler: re-find via regex on original.
    # Match surface=... once
    sm = re.search(r"surface\s*=\s*([a-z_,\s]+?)(?=\s+when=|\s*$)", qstr)
    if sm:
        surfaces = [s.strip() for s in sm.group(1).split(",") if s.strip()]
        for s in surfaces:
            if s not in VALID_SURFACES:
                raise SSLParseError(
                    f"invalid surface {s!r} in qualifier; must be one of {sorted(VALID_SURFACES)}"
                )
    wm = re.search(r"when\s*=\s*(.+?)(?:\s+surface=|\s*$)", qstr)
    if wm:
        when = wm.group(1).strip()
    return surfaces, when


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

    # Detect version first
    for ln in lines:
        m = _RE_VERSION.match(ln)
        if m:
            ssl.version = m.group(1)
            break

    is_v4 = ssl.version.startswith("4.") if ssl.version else False
    is_v6 = ssl.version.startswith("6.") if ssl.version else False

    i = 0
    while i < len(lines):
        raw_line = lines[i]
        line = _strip_line_comments(raw_line)
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        # version (already set, but consume)
        m = _RE_VERSION.match(line)
        if m:
            ssl.version = m.group(1)
            if ssl.version not in SUPPORTED_VERSIONS:
                raise SSLParseError(
                    f"unsupported SSL_VERSION {ssl.version} (supported: {sorted(SUPPORTED_VERSIONS)})",
                    i + 1, path,
                )
            i += 1
            continue

        # @extends
        m = _RE_EXTENDS.match(line)
        if m:
            if ssl.extends:
                raise SSLParseError("duplicate @extends declaration", i + 1, path)
            ssl.extends = m.group(1)
            i += 1
            continue

        # @mixin (v6)
        m = _RE_MIXIN.match(line)
        if m:
            ssl.mixins.append(m.group(1))
            i += 1
            continue

        # @runtime { ... } declaration zone (v6)
        if _RE_RUNTIME_OPEN.match(line):
            i += 1
            while i < len(lines):
                rl = _strip_line_comments(lines[i]).strip()
                if rl == "}":
                    i += 1
                    break
                if not rl:
                    i += 1
                    continue
                rm = _RE_RUNTIME_DECL.match(rl)
                if not rm:
                    raise SSLParseError(
                        f"invalid @runtime declaration {rl!r}", i + 1, path,
                    )
                ssl.runtime_decls[rm.group(1)] = rm.group(2)
                i += 1
            continue

        # @test inline
        m = _RE_TEST_INLINE.match(line)
        if m:
            desc = m.group(1)
            w = float(m.group(2)) if m.group(2) else 0.7
            body = m.group(3).strip()
            ssl.blocks.append(Block(
                name=f"test:{desc}", body=body, body_raw=body,
                weight=w, is_test=True, line=i + 1,
            ))
            i += 1
            continue

        # @test multi-line
        m = _RE_TEST_OPEN.match(line)
        if m:
            desc = m.group(1)
            w = float(m.group(2)) if m.group(2) else 0.7
            open_line = i + 1
            i += 1
            body_lines, depth, terminated = [], 1, False
            while i < len(lines):
                cur = lines[i]
                cs = cur.strip()
                if cs == "}":
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
                raise SSLParseError(
                    f"unterminated @test block (opened on line {open_line})",
                    open_line, path,
                )
            body = "\n".join(body_lines).strip()
            ssl.blocks.append(Block(
                name=f"test:{desc}", body=body, body_raw=body,
                weight=w, is_test=True, line=open_line,
            ))
            i += 1
            continue

        # v6/v5 inline block
        m = _RE_BLOCK_INLINE.match(line)
        if m:
            merge = bool(m.group(1))
            name = m.group(2)
            qual = m.group(3)
            wstr = m.group(4)
            body = m.group(5).strip()
            surfaces, when_cond = _parse_qualifiers(qual)
            weight = _resolve_weight(name, wstr, is_v6, ssl, i + 1, path)
            ssl.blocks.append(Block(
                name=name, body=body, body_raw=body, weight=weight,
                merge=merge, surface=surfaces, condition=when_cond, line=i + 1,
            ))
            i += 1
            continue

        # v6/v5 multi-line block
        m = _RE_BLOCK_OPEN.match(line)
        if m:
            merge = bool(m.group(1))
            name = m.group(2)
            qual = m.group(3)
            wstr = m.group(4)
            open_line = i + 1
            i += 1
            body_lines, depth, terminated = [], 1, False
            while i < len(lines):
                cur = lines[i]
                cs = cur.strip()
                if cs == "}":
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
                raise SSLParseError(
                    f"unterminated block @{name} (opened on line {open_line})",
                    open_line, path,
                )
            body = "\n".join(body_lines).strip()
            surfaces, when_cond = _parse_qualifiers(qual)
            weight = _resolve_weight(name, wstr, is_v6, ssl, open_line, path)
            ssl.blocks.append(Block(
                name=name, body=body, body_raw=body, weight=weight,
                merge=merge, surface=surfaces, condition=when_cond, line=open_line,
            ))
            i += 1
            continue

        # v4 block header (no braces)
        m = _RE_BLOCK_V4_HEADER.match(line)
        if m and is_v4:
            name = m.group(1)
            # capture weight if present
            wm = re.search(r"~([\d.]+)", line)
            weight = float(wm.group(1)) if wm else 0.7
            open_line = i + 1
            i += 1
            body_lines = []
            while i < len(lines):
                cur = lines[i]
                cs = cur.strip()
                if not cs:
                    body_lines.append("")
                    i += 1
                    continue
                if cur.startswith((" ", "\t")):
                    content = cs
                    if content.startswith(">>>"):
                        content = "- " + content[3:].lstrip()
                    body_lines.append(content)
                    i += 1
                    continue
                break
            while body_lines and not body_lines[-1].strip():
                body_lines.pop()
            body = "\n".join(body_lines).strip()
            ssl.blocks.append(Block(
                name=name, body=body, body_raw=body, weight=weight,
                merge=False, line=open_line,
            ))
            continue

        # typed attribute (v4/v5/v6 — but v6 enforces type)
        m = _RE_ATTR_TYPED.match(line)
        if m:
            key, tp, raw_val = m.group(1), m.group(2), m.group(3)
            val = _parse_value(raw_val)
            if is_v6:
                val = _validate_typed_value(key, tp, val, i + 1, path)
            ssl.attributes[key] = val
            ssl.attribute_types[key] = tp
            i += 1
            continue

        # untyped v5 attribute
        m = _RE_ATTR_V5.match(line)
        if m:
            key, raw_val = m.group(1), m.group(2)
            ssl.attributes[key] = _parse_value(raw_val)
            i += 1
            continue

        # uppercase reserved attribute (preserved as-is)
        m = _RE_RESERVED_ATTR.match(line)
        if m:
            ssl.attributes[m.group(1)] = _parse_value(m.group(2))
            i += 1
            continue

        # v4 inline var
        if _RE_INLINE_VAR_V4.match(line) and is_v4:
            i += 1
            continue

        # v4 tolerant fallback
        if is_v4:
            i += 1
            continue

        raise SSLParseError(f"unexpected line: {line.rstrip()!r}", i + 1, path)

    return ssl


def _resolve_weight(
    name: str, wstr: str | None, is_v6: bool, ssl: SSLFile,
    line: int, path: str,
) -> float:
    """Determine weight for a block, applying v6 rules (required + floors)."""
    floor = BLOCK_WEIGHT_FLOORS.get(name, 0.0)
    if wstr:
        w = float(wstr)
        if not (0.0 <= w <= 1.0):
            raise SSLWeightError(
                f"@{name} weight {w} out of range [0.0, 1.0]", line, path,
            )
        if is_v6 and w < floor:
            raise SSLWeightError(
                f"@{name} weight {w} below canonical floor {floor}", line, path,
            )
        return w
    # No weight declared
    if is_v6:
        raise SSLWeightError(
            f"@{name} requires explicit ~weight in v6 mode", line, path,
        )
    # v5/v4: emit warning, default 0.7 (or canonical floor if higher)
    default = max(0.7, floor)
    ssl.warnings.append(
        f"@{name} (line {line}) has no ~weight; defaulting to {default} "
        f"(v6 will require explicit declaration)"
    )
    return default


# ─── Validation ─────────────────────────────────────────────────────────────

def validate(ssl: SSLFile, chain: list[SSLFile] | None = None) -> list[str]:
    errors: list[str] = []
    chain = chain or []

    if not ssl.version:
        errors.append("missing SSL_VERSION declaration")
    elif ssl.version not in SUPPORTED_VERSIONS:
        errors.append(f"unsupported SSL_VERSION {ssl.version}")

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

    seen: set[str] = set()
    for b in ssl.blocks:
        if b.merge or b.is_test:
            continue
        # Same-name non-merge blocks are allowed only when distinguished by qualifier
        # (e.g. @voice[surface=twitter] vs @voice[surface=linkedin])
        key = f"{b.name}|{','.join(sorted(b.surface))}|{b.condition or ''}"
        if key in seen:
            errors.append(f"duplicate non-@merge block @{b.name} (line {b.line})")
        seen.add(key)

    if not ssl.is_abstract:
        full_chain = chain + [ssl]
        if not _chain_has_block(full_chain, "identity"):
            errors.append("missing @identity block (required by spec §3.7)")
        if not ssl.is_v4 and not _chain_has_block(full_chain, "voice"):
            errors.append("missing @voice block (required by spec §3.7)")

    return errors


def _chain_has_block(chain: list[SSLFile], block: str) -> bool:
    for f in chain:
        for b in f.blocks:
            if b.name == block and not b.is_test:
                return True
    return False


# ─── Loader ─────────────────────────────────────────────────────────────────

def load_chain(path: str | Path, search_paths: list[Path] | None = None) -> list[SSLFile]:
    path = Path(path)
    search_paths = list(search_paths or [])
    search_paths.insert(0, path.parent)
    for default in [Path("/root/bluewave/braaineer/agents"), Path(__file__).parent]:
        if default.exists() and default not in search_paths:
            search_paths.append(default)

    chain: list[SSLFile] = []
    visited: set[str] = set()

    def _load(p: Path) -> None:
        key = str(p.resolve())
        if key in visited:
            raise SSLError(f"cyclic @extends/@mixin involving {p}", path=str(p))
        visited.add(key)
        ssl = parse(p)
        # mixins resolve before extends (horizontal composition first)
        for mixin_name in ssl.mixins:
            mp = _resolve(mixin_name, search_paths)
            if mp is None:
                raise SSLError(
                    f"cannot resolve @mixin {mixin_name!r} "
                    f"(searched: {[str(s) for s in search_paths]})",
                    path=str(p),
                )
            _load(mp)
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

def compile_prompt(
    chain: list[SSLFile],
    runtime: dict[str, Any] | None = None,
    *,
    max_tokens: int = DEFAULT_MAX_PROMPT_TOKENS,
    mode: str = "prose",
) -> str:
    """Compile a chain of SSL files into a system prompt.

    Args:
        chain: ordered chain (base first, leaf last) from load_chain
        runtime: dict of runtime-injected variables (principal, surface,
                 tenant_context, knowledge_base, ...). All values used for
                 interpolation, surface filter, @when evaluation.
        max_tokens: soft ceiling — blocks below PROTECTED_FLOOR are dropped
                    bottom-up (lowest weight first) until estimated token
                    count fits. Set to 0 to disable.
        mode: 'prose' (default, no headers) or 'structured' (### headers).
    """
    runtime = runtime or {}
    merged = _merge_chain(chain)
    surface = runtime.get("surface") or merged.attributes.get("surface", "multi")

    # Interpolation scope: attributes ∪ runtime (runtime wins on collisions)
    scope: dict[str, Any] = dict(merged.attributes)
    scope.update(runtime)

    # v6 runtime declarations: warn if declared but not provided at compile time
    for f in chain:
        for k, t in f.runtime_decls.items():
            if k not in scope:
                f.warnings.append(f"@runtime declared {k}:{t} but not provided at compile time")

    # Pre-compute v6 set for interpolation strictness check
    v6_block_ids: set[int] = set()
    for f in chain:
        if f.is_v6:
            for b in f.blocks:
                v6_block_ids.add(id(b))

    # Build preamble + optional runtime-data blocks (tenant_context, knowledge_base)
    agent_name = merged.attributes.get("agent_name", "Agent")
    principal = scope.get("principal") or "the operator"
    preamble = f"You are {agent_name}, operating on behalf of {principal}."

    runtime_parts: list[str] = []
    if runtime.get("tenant_context"):
        runtime_parts.append(_render_block("tenant_context", runtime["tenant_context"], mode))
    if runtime.get("knowledge_base"):
        kb = runtime["knowledge_base"].strip()
        runtime_parts.append(_render_block("knowledge_base", f"<kb>\n{kb}\n</kb>", mode))

    # Collect blocks (surface + when filtering, same-name resolution)
    blocks = _collect_blocks_v6(chain, surface, scope)
    blocks.sort(key=lambda b: (-b.weight, b.line))

    # Apply context pressure (drop low-weight non-protected blocks if over budget)
    if max_tokens > 0:
        blocks = _drop_for_pressure(
            blocks, preamble, runtime_parts, scope, v6_block_ids, mode, max_tokens,
        )

    # Final emission with interpolation
    out_parts: list[str] = [preamble] + runtime_parts
    for b in blocks:
        body = _resolve_body(b, scope, v6_block_ids)
        if not body.strip():
            continue
        out_parts.append(_render_block(b.name, body, mode))
    return "\n\n".join(out_parts)


def _resolve_body(b: Block, scope: dict, v6_block_ids: set[int]) -> str:
    """Interpolate {var} references in a block body."""
    if "{" not in b.body:
        return b.body
    is_v6 = id(b) in v6_block_ids
    try:
        return _interpolate(b.body, scope, strict=is_v6, line=b.line, path="<chain>")
    except SSLRefError:
        if is_v6:
            raise
        return b.body


def _render_block(name: str, body: str, mode: str) -> str:
    if mode == "structured":
        return f"### {name}\n{body}"
    return f"@{name}\n{body}"


def _collect_blocks_v6(
    chain: list[SSLFile], surface: str, scope: dict,
) -> list[Block]:
    """Walk chain, return list of blocks that survive surface + when filters.

    Resolution semantics:
    - Block with empty surface list: passes filter (general-purpose)
    - Block with non-empty surface list: passes filter if surface ∈ list, OR active surface == 'multi'
    - Block with @when condition: passes filter if condition evaluates True (errors → exclude)
    - @merge blocks: always emitted (one per occurrence) at their own weight position
    - Non-merge same-name resolution: prefer surface-qualified > unqualified;
      among same-specificity, latest in chain wins (override semantics)
    """
    surviving: list[Block] = []
    for f in chain:
        for b in f.blocks:
            if b.is_test:
                continue
            if b.surface and surface != "multi" and surface not in b.surface:
                continue
            if b.condition:
                try:
                    if not _eval_when(b.condition, scope):
                        continue
                except SSLConditionError:
                    continue
            surviving.append(b)

    # Pick the "best" non-merge block per name. Specificity: surface-qualified > unqualified.
    # Among equal specificity, later in chain overrides earlier.
    by_name_specific: dict[str, Block] = {}
    by_name_general: dict[str, Block] = {}
    for b in surviving:
        if b.merge:
            continue
        if b.surface:
            by_name_specific[b.name] = b  # later overrides earlier in iter order
        else:
            by_name_general[b.name] = b

    chosen: dict[str, Block] = {}
    for name in set(by_name_specific) | set(by_name_general):
        chosen[name] = by_name_specific.get(name) or by_name_general[name]

    # Build final list preserving chain order. Emit chosen non-merge once per name + all merges.
    final: list[Block] = []
    emitted_names: set[str] = set()
    for b in surviving:
        if b.merge:
            final.append(b)
            continue
        if b.name in emitted_names:
            continue
        if chosen.get(b.name) is b:
            final.append(b)
            emitted_names.add(b.name)
    return final


def _drop_for_pressure(
    blocks: list[Block],
    preamble: str,
    runtime_parts: list[str],
    scope: dict,
    v6_block_ids: set[int],
    mode: str,
    max_tokens: int,
) -> list[Block]:
    """Drop low-weight non-protected blocks until estimated token count fits.

    Protection rules (in order):
    1. Blocks with name in BLOCK_WEIGHT_FLOORS (vow, identity, voice, safeguards, limits)
       are NEVER dropped, regardless of weight.
    2. Blocks with weight >= PROTECTED_FLOOR (0.80) are NEVER dropped.
    3. Among droppable blocks, lowest-weight first (ties broken by latest line).
    """
    def _emit(bs: list[Block]) -> str:
        parts = [preamble] + runtime_parts
        for b in bs:
            body = _resolve_body(b, scope, v6_block_ids)
            if body.strip():
                parts.append(_render_block(b.name, body, mode))
        return "\n\n".join(parts)

    current = list(blocks)
    while _estimate_tokens(_emit(current)) > max_tokens:
        droppable = [
            (idx, b) for idx, b in enumerate(current)
            if b.weight < PROTECTED_FLOOR and b.name not in BLOCK_WEIGHT_FLOORS
        ]
        if not droppable:
            break
        droppable.sort(key=lambda x: (x[1].weight, -x[1].line))
        drop_idx = droppable[0][0]
        current.pop(drop_idx)
    return current


def _estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN_ESTIMATE


def _merge_chain(chain: list[SSLFile]) -> SSLFile:
    merged = SSLFile(path="<merged>")
    merged.version = chain[-1].version if chain else SPEC_VERSION
    for f in chain:
        merged.attributes.update(f.attributes)
        merged.attribute_types.update(f.attribute_types)
    return merged


# ─── CLI ────────────────────────────────────────────────────────────────────

def _cli() -> int:
    ap = argparse.ArgumentParser(prog="ssl_parser")
    ap.add_argument("path")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--compile", action="store_true")
    ap.add_argument("--surface", default=None, help="active surface for compile")
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--search", action="append", default=[])
    ap.add_argument("--mode", choices=["prose", "structured"], default="prose")
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_PROMPT_TOKENS)
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

    # Print warnings (parsing-time only; non-fatal)
    for f in chain:
        for w in f.warnings:
            print(f"WARN [{f.path}]: {w}", file=sys.stderr)

    if args.compile:
        runtime = {"surface": args.surface} if args.surface else {}
        print(compile_prompt(chain, runtime=runtime, max_tokens=args.max_tokens, mode=args.mode))
        return 0
    if args.json:
        print(json.dumps(child.as_dict(), indent=2, ensure_ascii=False, default=str))
        return 0

    print(f"SSL v{child.version} · {args.path}")
    print(f"  agent_name: {child.attributes.get('agent_name', '(inherited)')}")
    print(f"  surface: {child.attributes.get('surface', '(inherited)')}")
    print(f"  extends: {child.extends or '(none)'}")
    print(f"  mixins: {child.mixins or '(none)'}")
    print(f"  runtime decls: {list(child.runtime_decls.keys()) or '(none)'}")
    print(f"  chain depth: {len(chain)}")
    print(f"  abstract: {child.is_abstract}")
    print(f"  blocks ({len(child.blocks)}):")
    for b in child.blocks:
        marks = []
        if b.merge: marks.append("merge")
        if b.is_test: marks.append("test")
        if b.surface: marks.append(f"surface={','.join(b.surface)}")
        if b.condition: marks.append(f"when={b.condition}")
        marks_str = " [" + ", ".join(marks) + "]" if marks else ""
        preview = b.body[:60].replace("\n", " ") + ("…" if len(b.body) > 60 else "")
        print(f"    @{b.name} ~{b.weight}{marks_str} — {preview}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
