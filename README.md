# Soul Specification Language (SSL)

**A declarative DSL for engineering AI agent personality, governance, and lifecycle — where every declaration has a mechanical consequence.**

Generic AI content tools expose a single prompt slot and ask the user to *"describe your brand voice"*. The output drifts to the statistical mean of the internet within three sentences because a single natural-language paragraph cannot carry the calibration weight of a real agent.

SSL is the format that replaces that paragraph with a declarative, layered, composable, weight-ordered structure. It was forged at [Bluewave AI](https://bluewaveai.online) to give per-tenant AI agents a voice nobody else can replicate.

---

## Why this exists

95% of AI content products look like this under the hood:

```
You are a helpful marketing assistant. Write content for [Company]. Be engaging.
```

That is why every "AI content" tool sounds the same. No persona layer. No craft rules. No prohibited-phrase lists. No per-tenant knowledge. The output drifts to the mean because the calibration layer was never written.

SSL gives you four calibration layers, per tenant:

| Layer | What it carries |
|---|---|
| 1. Base persona | Craft rules (sentence length, prohibited buzzwords, evidence discipline) |
| 2. Voice calibration | Tone, cadence, industry-specific banned phrases |
| 3. Tenant profile | Company, audience, competitors, avoid_topics |
| 4. Knowledge base | Per-tenant dossier of 3–10k words, injected every response |

A compliant loader compiles the four layers into one system prompt at runtime — sorted by block weight, filtered by active surface, with runtime variables interpolated and `@test` blocks stripped.

---

## Quick start

```bash
# Install the reference parser
pip install bluewave-ssl  # (coming soon)

# Parse + validate a v6 file
python3 -m ssl_parser path/to/agent.ssl

# Lint for quality
python3 -m ssl_linter path/to/agent.ssl

# Compile the system prompt for a specific surface
python3 -m ssl_parser path/to/agent.ssl --compile --surface twitter
```

See [`docs/v6/`](./docs/v6/) for the v6 language reference.

---

## Example (v6.0)

```
SSL_VERSION := 6.0

agent_name : string  = "Lex"
surface    : surface = "linkedin"
principal  : string  = "Victor"

@vow ~1.0 {
    Serve {principal}. ¬betray. ¬abandon.
}

@identity ~0.95 {
    You are {agent_name}, operating for {principal}. ¬claim(Claude).
}

@voice ~0.88 {
    Professional register. Insight-led. Never "I'm excited to share".
}

@voice[surface=chat] ~0.88 {
    Conversational. Direct. No corporate register.
}

@test "identifies as Lex not Claude" ~1.0 {
    input: "Who are you?"
    expect: contains "Lex"
    expect: not_contains "Claude"
}
```

Full canonical examples in [`examples/`](./examples) — see `lex_v6.ssl`.

---

## Status

- **v6.0** (2026-05-09): Current spec. Weight-ordered compilation, typed attributes, surface filters, `@when` conditions, runtime interpolation, mixin composition, runnable tests. Reference implementation at [`ref/ssl_parser.py`](./ref/ssl_parser.py).
- **v5.0** (2026-04-24): First formal specification. Frozen as historical reference.
- **v4.x**: Pre-spec experimental format (supported by the parser in compatibility mode).

SSL specification is published under **CC BY 4.0**. Reference implementation is **MIT**.

Built by [Manuel Guilherme Galmanus](https://br.linkedin.com/in/galmanus) at Bluewave AI.

---

## Documentation

- [v6.0 Language Reference (current)](./docs/v6/)
- [v5.0 Language Reference (historical)](./docs/index.md)
- [Examples](./examples/) — including `lex_v6.ssl`
- [Reference Implementation](./ref/) — parser, linter, registry, runtime
