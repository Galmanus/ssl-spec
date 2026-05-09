# Contributing to SSL Spec

Welcome. SSL v7 is a working spec, not finished one. The bus factor is currently **1** (Manuel Galmanus) — that's a structural risk explicitly named in the v7 versioning page. The fastest way to make this spec category-defining is independent implementation and adversarial review.

## What's load-bearing right now

Three primitives shipped 2026-05-09: `@scope` (deterministic pre-flight), `@adversarial_battery` (CI-enforced test discipline), `@audit_chain` (SHA-256 forensic log). Reference parser at [`ref/ssl_parser.py`](ref/ssl_parser.py) — 36/36 pytest passing, 19/19 production `.ssl` files parsing without regression.

The full v7.0 specification is at [`docs/v7/`](docs/v7/) (~2700 lines, EBNF grammar, threat model, runtime API, error catalog, migration guide).

## Where contributions are most valuable

In rough priority order:

1. **Independent reference implementation** — port the parser to Rust / Go / TypeScript. The grammar in §2 is canonical; if your impl produces different compiled output for the same input, that's a bug in the spec, not your impl. Open a PR to fix the spec.

2. **Held-out adversarial sets** — the current `@adversarial_battery` is N=1000 (curated by the spec author; risk of overfitting). Submitting prompts that should refuse but don't, OR legitimate prompts that wrongly refuse (false-positive cases), is high-value. Tag PRs with `battery:hold-out` or `battery:false-positive`.

3. **Multi-vendor model coverage** — current eval runs on Anthropic models. PRs adding clean reproducible eval against GPT-4o, Gemini, Llama, Mistral, Cohere etc. close a real gap.

4. **Embedding-similarity layer for `@scope`** — the regex matcher is fragile against paraphrase attacks. Adding optional embedding-similarity check (still deterministic, still pre-flight, just semantic instead of lexical) is on the v7.1 roadmap. PRs welcome.

5. **CI hook for `block_deploy`** — `@adversarial_battery.fail_action: block_deploy` is declarative in v7.0 but not yet enforced in CI. PRs adding GitHub Actions / GitLab CI integration that fails the build on rate-regression are useful.

6. **Comparative position vs Colang / NeMo Guardrails** — the two are complementary but the boundaries deserve a side-by-side comparison page. PRs that ship that doc page, with examples and disanalogies, are valuable.

7. **Translations** — the spec is in English. PT/ES/JA/ZH translations welcome; canonical reference stays in English but translated copies linked from the homepage.

## How to propose changes

- For typos / clarifications: PR directly.
- For new primitives or grammar changes: open an issue first describing the change, the use case, and the failure mode the change closes. Spec discipline says: every primitive must have a mechanical consequence; if your proposal is descriptive-only, it gets the `descriptive-only` tag and goes to the v7.1 roadmap discussion, not the spec.
- For battery additions: PR with the JSONL diff. CI will re-run battery against current parser to verify it still passes the new prompts.
- For adversarial findings (jailbreaks that bypass `@scope`): tag as `security` and DO NOT publish exploit details until the spec maintainer has acknowledged. Coordinated disclosure norms apply.

## Authority

Spec ratification is currently single-maintainer (Manuel Galmanus) until the v8 transition planned for Q3 2026, when authority will fork into:
- A spec-design committee (3+ maintainers, votes on new primitives)
- A reference-impl maintainer (governs `ref/ssl_parser.py`)
- A battery curator (governs the adversarial set)

Until that transition, all spec changes go through Manuel. PRs that align with v7's design rules ("every declaration has a mechanical consequence", layered safety, falsifiable predictions) get reviewed within 7 days. Drive-by aesthetic refactors get closed.

## Bus factor

Yes — this is a single-maintainer project today. **Recruit pitch**: if you've shipped declarative-system or spec-language work before (Bazel, Nix, Pulumi, Cue, OpenAPI authors — looking at you), and you find SSL v7 either right or wrong in interesting ways, open an issue introducing yourself. The fastest path from "interesting solo project" to "category-defining spec" is a second independent maintainer with their own reference implementation.

Email: manuel@bluewaveai.online
GitHub: [@Galmanus](https://github.com/Galmanus)

## License

Apache 2.0. Use freely. Attribution appreciated.
