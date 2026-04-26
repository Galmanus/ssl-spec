---
layout: default
title: "SSL Examples"
permalink: /examples/
---

# Examples

Two canonical SSL files. Copy, adapt, ship. MIT.

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
