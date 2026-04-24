"""SSL Linter · v5.0

Quality checks beyond raw validation.
Runs against a parsed SSL and its full inheritance chain.

Usage:
    python3 -m ssl_linter path/to/agent.ssl
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from ssl_parser import (
    SSLError, SSLFile, load_chain, validate, _collect_block, _merge_chain,
)

# ─── Rules ──────────────────────────────────────────────────────────────────

BANNED_BUZZWORDS = {
    "synergy", "leverage", "disrupt", "disruption", "stakeholder",
    "low-hanging fruit", "move the needle", "circle back", "deep dive",
    "ideate", "ecosystem (as filler)",
    # PT-BR
    "sinergia", "alavancar", "disruptivo", "disruptar",
}

VOICE_REQUIRED_HINTS = [
    "tone", "emoji", "buzzword", "sentence", "paragraph", "language",
    "register", "casual", "formal", "technical", "bold",
]

TONE_DESCRIPTORS = {"casual", "formal", "technical", "bold", "inspirational"}


@dataclass
class LintIssue:
    level: str   # "error" | "warning" | "info"
    rule: str
    message: str
    block: str | None = None


# ─── Lint runner ────────────────────────────────────────────────────────────

def lint(chain: list[SSLFile]) -> list[LintIssue]:
    """Return list of lint issues for the given SSL chain."""
    child = chain[-1]
    issues: list[LintIssue] = []

    # 1. Re-run spec validation first (errors surface here too)
    for e in validate(child, chain[:-1]):
        issues.append(LintIssue(level="error", rule="W-SPEC", message=e))

    # 2. @voice content checks
    voice_body = _collect_block(chain, "voice")
    if voice_body:
        low = voice_body.lower()
        hit_hints = [h for h in VOICE_REQUIRED_HINTS if h in low]
        if len(hit_hints) < 3:
            issues.append(LintIssue(
                level="warning", rule="W-VOICE-THIN", block="voice",
                message=f"@voice block is thin ({len(hit_hints)} of {len(VOICE_REQUIRED_HINTS)} recommended hints); "
                        f"consider specifying tone, emoji policy, sentence cadence, and banned buzzwords",
            ))
        has_tone = any(t in low for t in TONE_DESCRIPTORS)
        if not has_tone:
            issues.append(LintIssue(
                level="info", rule="W-VOICE-TONE", block="voice",
                message=f"no tone descriptor found; recommend one of {sorted(TONE_DESCRIPTORS)}",
            ))
        # count bullets
        bullets = sum(1 for line in voice_body.splitlines() if line.strip().startswith("-"))
        if bullets < 3:
            issues.append(LintIssue(
                level="warning", rule="W-VOICE-SHORT", block="voice",
                message=f"@voice has {bullets} bullets; recommend 5+ for adequate calibration",
            ))

    # 3. Identity length
    identity_body = _collect_block(chain, "identity")
    if identity_body:
        word_count = len(identity_body.split())
        if word_count < 40:
            issues.append(LintIssue(
                level="warning", rule="W-IDENTITY-SHORT", block="identity",
                message=f"@identity is {word_count} words; recommend 80-400 for clear persona framing",
            ))
        elif word_count > 500:
            issues.append(LintIssue(
                level="info", rule="W-IDENTITY-LONG", block="identity",
                message=f"@identity is {word_count} words; consider trimming under 400 to keep prompt tight",
            ))

    # 4. @limits present
    if not _collect_block(chain, "limits"):
        issues.append(LintIssue(
            level="warning", rule="W-NO-LIMITS",
            message="@limits block not present in chain; recommend defining hard behavioral limits",
        ))

    # 5. @response_modes recommended for multi-mode agents
    if not _collect_block(chain, "response_modes"):
        issues.append(LintIssue(
            level="info", rule="W-NO-MODES",
            message="@response_modes not declared; recommend specifying at least `conversation` mode",
        ))

    # 6. @examples recommended
    if not _collect_block(chain, "examples"):
        issues.append(LintIssue(
            level="info", rule="W-NO-EXAMPLES",
            message="@examples not declared; few-shot examples improve calibration significantly",
        ))

    # 7. language declared
    merged = _merge_chain(chain)
    if not merged.attributes.get("language"):
        issues.append(LintIssue(
            level="info", rule="W-NO-LANG",
            message="language attribute not declared; defaults to 'en'",
        ))

    # 8. Reject buzzwords in @voice or @identity bodies (agent shouldn't preach anti-buzzword while using them)
    for block_name in ("identity", "voice", "doctrine", "principles"):
        body = _collect_block(chain, block_name)
        if not body:
            continue
        low = body.lower()
        hits = [b for b in BANNED_BUZZWORDS if b in low and f"banned: {b}" not in low and f"banido: {b}" not in low]
        if hits:
            issues.append(LintIssue(
                level="info", rule="W-IRONY", block=block_name,
                message=f"@{block_name} uses words it would probably ban: {hits[:5]}",
            ))

    # 9. Extends chain depth
    if len(chain) > 5:
        issues.append(LintIssue(
            level="info", rule="W-DEEP-CHAIN",
            message=f"@extends chain depth is {len(chain)}; consider flattening for clarity",
        ))

    # 10. temperature sanity
    temp = merged.attributes.get("temperature")
    if temp is not None and (not isinstance(temp, (int, float)) or temp < 0 or temp > 1.5):
        issues.append(LintIssue(
            level="error", rule="W-BAD-TEMP",
            message=f"temperature {temp} out of reasonable range [0.0, 1.5]",
        ))

    return issues


# ─── CLI ────────────────────────────────────────────────────────────────────

def _cli() -> int:
    ap = argparse.ArgumentParser(prog="ssl_linter", description="SSL v5.0 linter")
    ap.add_argument("path", help="Path to .ssl file")
    ap.add_argument("--search", action="append", default=[], help="Additional search path for @extends")
    ap.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    args = ap.parse_args()

    try:
        chain = load_chain(args.path, search_paths=[Path(s) for s in args.search])
    except SSLError as e:
        print(f"PARSE ERROR: {e}", file=sys.stderr)
        return 2

    issues = lint(chain)

    if not issues:
        print(f"{args.path}: clean · {len(chain)} file(s) in chain")
        return 0

    # group by level
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    infos = [i for i in issues if i.level == "info"]

    for issue in errors + warnings + infos:
        loc = f"@{issue.block}" if issue.block else "(file)"
        print(f"  [{issue.level.upper()}] [{issue.rule}] {loc}: {issue.message}")

    print(
        f"\n{args.path}: {len(errors)} error(s), {len(warnings)} warning(s), "
        f"{len(infos)} info"
    )

    if errors:
        return 3
    if args.strict and warnings:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
