---
layout: default
title: "SSL Reference Implementation"
permalink: /ref/
---

# Reference Implementation

Production Python reference. The same code paths run inside Bluewave's tenants. MIT.

These files are sanitised public mirrors of the in-repo modules — domain-specific labels (PT-BR copy, internal logger names, branded fallback voice) are translated to English so the implementation reads as a neutral reference, not a Bluewave-only artefact.

---

## `ssl_parser.py`

Parser for the SSL grammar (v5). Tokenises a `.ssl` file into typed blocks, validates against the spec rules in `docs/`, raises typed `SSLError` on violation. Pure Python, no third-party deps.

[**Open ssl_parser.py →**](ssl_parser.py){:target="_blank"}

---

## `ssl_runtime.py`

The system-prompt builder. Takes `(agent_ssl_name, tenant_id, principal)` and returns a fully-composed system prompt by:

1. Resolving the tenant-override SSL → neutral fallback → legacy fallback chain
2. Loading the tenant runtime context (`onboarding.json`, `knowledge_base.md`)
3. Sanitising tenant-supplied fields against prompt injection (path traversal + control chars + `@blockname` impersonation all neutralised)
4. Composing into the final compiled prompt

This is the canonical entry point. Most consumers only call `build_agent_prompt()` from this module.

[**Open ssl_runtime.py →**](ssl_runtime.py){:target="_blank"}

---

## `ssl_linter.py`

Static analysis for `.ssl` files. Catches missing required blocks, undefined references, voice-attractor distribution out of range, scope rules referencing undeclared resources, etc. Run before deploying any new SSL to production.

[**Open ssl_linter.py →**](ssl_linter.py){:target="_blank"}

---

## `ssl_registry.py`

The discovery layer. Walks `tenants/<uuid>/agents/*.ssl` plus the shared neutral directory, returns a typed registry of available agents per tenant with their resolution path. Used at boot to validate the SSL fleet is well-formed before any traffic hits the runtime.

[**Open ssl_registry.py →**](ssl_registry.py){:target="_blank"}

---

## `migrate_v4_to_v5.py`

One-shot migration script for SSL files written against the v4 grammar. Converts indentation-based blocks to v5 brace syntax, lifts `@extends` declarations, normalises voice attractor scales. Idempotent — runs cleanly on already-v5 files (no-op).

[**Open migrate_v4_to_v5.py →**](migrate_v4_to_v5.py){:target="_blank"}

---

[← back to spec](../)
