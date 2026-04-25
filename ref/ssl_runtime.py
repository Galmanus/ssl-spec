"""SSL Runtime · canonical system-prompt builder.

Turns (agent_ssl_name, tenant_id) into a fully-composed system prompt by
loading the relevant .ssl chain, injecting tenant runtime context (principal,
profile, knowledge base), and compiling the result.

Usage:
    from bwssl.ssl_runtime import build_agent_prompt
    prompt = build_agent_prompt(
        agent_ssl_name="wave",
        tenant_id="<tenant uuid>",
        principal="Manuel",
    )

Resolution order:
  1. <TENANTS_DIR>/<tid>/agents/<agent_ssl_name>.ssl   (tenant override)
  2. <SHARED_DIR>/<agent_ssl_name>_neutral.ssl         (neutral default)
  3. <SHARED_DIR>/<agent_ssl_name>.ssl                 (legacy fallback)

Runtime context injected:
  - principal: human-readable operator name (e.g. from a JWT name claim)
  - tenant_context: rendered from <TENANTS_DIR>/<tid>/onboarding.json
  - knowledge_base: contents of <TENANTS_DIR>/<tid>/knowledge_base.md, if present
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .ssl_parser import (
    SSLError, load_chain, compile_prompt, SSLFile,
)

logger = logging.getLogger("ssl_runtime")

TENANTS_DIR = Path(os.environ.get("SSL_TENANTS_DIR", "/root/bluewave/tenants"))
# Try multiple paths — host path first, then container mount
_SHARED_CANDIDATES = [
    os.environ.get("SSL_SHARED_DIR", ""),
    "/root/bluewave/braaineer/agents",     # host path
    "/opt/bluewave/braaineer/agents",      # container mount
]
SHARED_DIR = next((Path(p) for p in _SHARED_CANDIDATES if p and Path(p).exists()), Path("/opt/bluewave/braaineer/agents"))

def _resolve_ssl_path(agent_ssl_name: str, tenant_id: str) -> Path | None:
    """Two-tier resolution:

    1. Tenant-specific override at <TENANTS_DIR>/<tid>/agents/<name>.ssl
    2. Shared neutral fallback at <SHARED_DIR>/<name>_neutral.ssl
       (or <name>.ssl as a final fallback for shared utilities)
    """
    if tenant_id:
        tenant_ssl = TENANTS_DIR / tenant_id / "agents" / f"{agent_ssl_name}.ssl"
        if tenant_ssl.exists():
            return tenant_ssl

    for candidate in (f"{agent_ssl_name}_neutral.ssl", f"{agent_ssl_name}.ssl"):
        p = SHARED_DIR / candidate
        if p.exists():
            return p

    return None


def _load_tenant_profile(tenant_id: str) -> dict[str, Any]:
    """Read onboarding.json for the tenant. Returns empty dict if absent."""
    defaults = {
        "company_name": "",
        "industry": "",
        "target_audience": "",
        "tone": "",
        "main_topics": "",
        "competitors": "",
        "twitter_handle": "",
        "avoid_topics": "",
    }
    try:
        p = TENANTS_DIR / tenant_id / "onboarding.json"
        if not p.exists():
            return defaults
        data = json.loads(p.read_text(encoding="utf-8"))
        out = dict(defaults)
        for key in out:
            if data.get(key):
                out[key] = data[key]
        return out
    except Exception as e:
        logger.warning("failed to load tenant profile %s: %s", tenant_id, e)
        return defaults


def _load_tenant_kb(tenant_id: str) -> str:
    """Read knowledge_base.md for the tenant. Empty string if absent."""
    try:
        p = TENANTS_DIR / tenant_id / "knowledge_base.md"
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("failed to load KB %s: %s", tenant_id, e)
    return ""


def _render_tenant_context(profile: dict[str, Any], principal: str) -> str:
    """Render tenant profile as @tenant_context block body."""
    lines = []
    if principal:
        lines.append(f"Principal: {principal}")
    if profile.get("company_name"):
        lines.append(f"Company: {profile['company_name']}")
    if profile.get("industry"):
        lines.append(f"Industry: {profile['industry']}")
    if profile.get("target_audience"):
        lines.append(f"Audience: {profile['target_audience']}")
    if profile.get("main_topics"):
        lines.append(f"Topics: {profile['main_topics']}")
    if profile.get("competitors"):
        lines.append(f"Competitors: {profile['competitors']}")
    if profile.get("tone"):
        lines.append(f"Tone: {profile['tone']}")
    if profile.get("twitter_handle"):
        lines.append(f"X handle: {profile['twitter_handle']}")
    if profile.get("avoid_topics"):
        lines.append(f"Avoid: {profile['avoid_topics']}")
    return "\n".join(lines)


def build_agent_prompt(
    agent_ssl_name: str,
    tenant_id: str,
    principal: str = "",
    include_kb: bool = True,
    extra_context: str = "",
) -> str:
    """Build a full system prompt for the given agent + tenant.

    Args:
        agent_ssl_name: SSL file stem (e.g. 'wave', 'vellora_twitter')
        tenant_id: UUID string of the tenant
        principal: Human-readable name of the operator (e.g. 'Manuel', 'Guilherme')
        include_kb: Inject knowledge_base.md if present (default True)
        extra_context: Additional context appended to @tenant_context block

    Returns:
        Compiled system prompt string, ready to pass as system_prompt_override.

    Falls back gracefully if SSL cannot be loaded — returns a minimal prompt
    based on available runtime data. Never raises.
    """
    profile = _load_tenant_profile(tenant_id)
    kb = _load_tenant_kb(tenant_id) if include_kb else ""
    tenant_context = _render_tenant_context(profile, principal)
    if extra_context:
        tenant_context = f"{tenant_context}\n\n{extra_context}" if tenant_context else extra_context

    runtime = {
        "principal": principal or "the operator",
        "tenant_context": tenant_context,
        "knowledge_base": kb if include_kb else "",
    }

    ssl_path = _resolve_ssl_path(agent_ssl_name, tenant_id)
    if ssl_path is None:
        logger.warning(
            "SSL not found for agent=%s tenant=%s; falling back to minimal prompt",
            agent_ssl_name, tenant_id,
        )
        return _minimal_fallback(agent_ssl_name, runtime, profile)

    try:
        chain = load_chain(ssl_path, search_paths=[SHARED_DIR])
        return compile_prompt(chain, runtime=runtime)
    except SSLError as e:
        logger.error("SSL parse/validate failed for %s: %s", ssl_path, e)
        return _minimal_fallback(agent_ssl_name, runtime, profile)
    except Exception as e:
        logger.error("SSL compile failed for %s: %s", ssl_path, e)
        return _minimal_fallback(agent_ssl_name, runtime, profile)


def _minimal_fallback(agent_ssl_name: str, runtime: dict[str, Any], profile: dict[str, Any]) -> str:
    """Emergency fallback when SSL can't be loaded — build a thin prompt from runtime alone."""
    parts = [
        f"You are {agent_ssl_name}, an SSL-calibrated agent operating for {runtime.get('principal')}.",
        "",
    ]
    if runtime.get("tenant_context"):
        parts.append("@tenant_context\n" + runtime["tenant_context"] + "\n")
    if runtime.get("knowledge_base"):
        parts.append("@knowledge_base\n<kb>\n" + runtime["knowledge_base"] + "\n</kb>\n")
    parts.append(
        "@voice\n"
        "- Match the operator's language\n"
        "- No emojis\n"
        "- Short sentences predominate\n"
        "- No buzzwords (synergy, leverage, disrupt)\n"
        "- Honest assessment over encouragement\n"
    )
    return "\n".join(parts)


def principal_from_jwt(authorization_header: str) -> str:
    """Extract principal first-name from a Bearer JWT. Empty string on failure."""
    if not authorization_header:
        return ""
    import jwt as _jwt
    try:
        token = authorization_header.replace("Bearer ", "", 1)
        secret = os.environ.get("JWT_SECRET", "")
        if not secret:
            return ""
        payload = _jwt.decode(
            token, secret,
            algorithms=[os.environ.get("JWT_ALGORITHM", "HS256")],
        )
        raw = payload.get("name") or payload.get("email", "").split("@")[0]
        if raw:
            return str(raw).split(" ")[0].strip()
    except Exception:
        pass
    return ""
