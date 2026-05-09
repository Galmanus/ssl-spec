---
layout: default
title: "SSL Examples"
permalink: /examples/
---

# Examples

Three canonical SSL files. Copy, adapt, ship. MIT.

---

## `lex_v6.ssl` (current spec — v6.0)

A LinkedIn intelligence agent showing every v6 mechanical feature:
weight-ordered blocks, surface-conditional `@voice` overrides, conditional
`@behavior` driven by `[when=debug==true]`, runtime interpolation of
`{principal}` and `{agent_name}`, the `@runtime` declaration zone, and three
`@test` blocks that are stripped from the compiled prompt and become
assertions for `ssl_runner.py`.

[**Open lex_v6.ssl →**](lex_v6.ssl){:target="_blank"}

```
SSL_VERSION := 6.0
agent_name : string  = "Lex"
surface    : surface = "linkedin"
principal  : string  = "Victor"

@vow ~1.0 {
    Serve {principal}. ¬betray. ¬abandon.
}

@voice[surface=chat] ~0.88 {
    Conversational. Direct. No corporate register.
}

@behavior[when=debug==true] ~0.5 {
    Log every decision with confidence score before executing.
}

@test "identifies as Lex not Claude" ~1.0 {
    input: "Who are you?"
    expect: contains "Lex"
    expect: not_contains "Claude"
}
```

Compile this against three different surfaces and watch the `@voice` block change without forking the file:

```bash
python3 -m ssl_parser examples/lex_v6.ssl --compile --surface linkedin
python3 -m ssl_parser examples/lex_v6.ssl --compile --surface chat
python3 -m ssl_parser examples/lex_v6.ssl --compile --surface twitter
```

---

## `base_neutral.ssl`

The neutral baseline — a fully-loaded SSL with every block populated by sane defaults. Use this as your starting template when calibrating a new agent. Strip what you don't need; replace the rest with your tenant-specific values.

[**Open base_neutral.ssl →**](base_neutral.ssl){:target="_blank"}

```
SSL_VERSION := 5.0
agent_name  := "neutral"
surface     := "x"
language    := "en"

@identity {
  role: "calibration template"
  posture: "professional, neutral"
  voice: "concise, declarative"
}

@scope {
  may_touch: ["draft content", "research"]
  must_not: ["send messages", "publish without review"]
}
```

---

## `wave_personal.ssl`

The actual `.ssl` calibration of Wave — Bluewave's flagship agent — with sensitive blocks redacted. Use this to see how a production-grade SSL looks: identity, scope, voice attractors, runtime hooks, knowledge_base bindings.

[**Open wave_personal.ssl →**](wave_personal.ssl){:target="_blank"}

This is the file Wave reads on every cycle. It rewrote portions of itself in production on April 10, 2026 — first verifiable closed-loop self-modification on a Bluewave agent.

---

[← back to spec](../)
