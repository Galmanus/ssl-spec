# Soul Specification Language (SSL)

**A structured specification language for per-tenant AI agent calibration.**

Generic AI content tools expose a single prompt slot and ask the user to *"describe your brand voice"*. The output drifts to the statistical mean of the internet within three sentences because a single natural-language paragraph cannot carry the calibration weight of a real agent.

SSL is the format that replaces that paragraph with a declarative, layered, composable structure. It was forged at [Bluewave AI](https://bluewaveai.online) to give per-tenant AI agents a voice nobody else can replicate.

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

A compliant loader compiles the four layers into one system prompt at runtime.

---

## Quick start

```bash
# Install the reference parser
pip install bluewave-ssl  # (coming soon)

# Parse + validate
python3 -m ssl_parser path/to/agent.ssl

# Lint for quality
python3 -m ssl_linter path/to/agent.ssl

# Render the compiled system prompt
python3 -m ssl_parser path/to/agent.ssl --compile
```

See [`docs/`](./docs) for the full language reference.

---

## Example

```
// Minimal SSL
SSL_VERSION := 5.0
agent_name := "SampleAgent"
surface := "x"
language := "en"

@identity {
  You are SampleAgent, a content agent for SampleCorp.
}

@voice {
  - English by default
  - Short sentences dominate
  - Zero emojis
  - Banned: synergy, leverage, disrupt, stakeholder
  - One historical reference per response, maximum
}
```

Full canonical examples in [`examples/`](./examples).

---

## Status

- **v5.0** (2026-04-24): First formal specification. Parser, linter, registry reference implementation.
- **v4.x**: Pre-spec informal format (supported by the parser in compatibility mode).

SSL v5.0 specification is published under **CC BY 4.0**. Reference implementation is **MIT**.

Built by [Manuel Guilherme Galmanus](https://br.linkedin.com/in/galmanus) at Bluewave AI.

---

## Documentation

- [Language Reference (full spec)](./docs/index.md)
- [Grammar (EBNF)](./docs/grammar.md)
- [Examples](./examples/)
- [Reference Implementation](./ref/)
