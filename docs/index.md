---
layout: default
title: "SSL Language Reference"
permalink: /docs/
---

# Soul Specification Language (SSL)
## Language Reference · v5.0 (historical)

> **This is the v5.0 reference, kept as historical record.** The current specification is **[SSL v6.0](./v6/)** — weights are now load-bearing, types are validated at parse time, surface and `@when` qualifiers filter the compiled output, `@test` blocks strip from the prompt, and the parser is honest about which features are formally enforced versus which are prose the model reads as natural language.

**Status:** historical · superseded by v6.0 on 2026-05-09 · originally released 2026-04-24
**Audience:** engineers maintaining v5 agents, anyone migrating to v6
**File extension:** `.ssl`
**Encoding:** UTF-8, LF line endings

---

## 0. Motivation

Generic AI content tools expose a single prompt slot and ask the user to "describe your brand voice". The output drifts to the statistical mean of the internet within three sentences because a single natural-language paragraph cannot carry the calibration weight of a real agent.

SSL is a structured specification language for per-tenant AI agent calibration. An SSL file defines identity, voice, operational rules, and runtime behavior in declarative blocks that a loader compiles into a system prompt.

SSL is not a programming language. It has no runtime semantics, no evaluation, no control flow. It is a configuration format with inheritance, designed so the loader can compose multi-layer calibration deterministically.

---

## 1. File structure

An SSL file is a sequence of top-level statements. Each statement is one of:

- **Comment** (starts with `//` or `/* ... */`)
- **Version declaration** (`SSL_VERSION := <number>`)
- **Extends declaration** (`@extends <parent_name>`)
- **Attribute** (`<identifier> := <value>`)
- **Block** (`@<name> { <body> }`)

Example (minimal valid SSL):

```
// Minimal SSL
SSL_VERSION := 5.0
agent_name := "SampleAgent"
surface := "x"
language := "en"

@identity {
  You are SampleAgent, a content agent for SampleCorp.
}
```

---

## 2. Comments

```
// single-line comment (to end of line)
/* multi-line comment
   spans multiple lines */
```

Comments are stripped at parse time. They carry no semantics. They must not appear inside attribute values or block bodies where they would be ambiguous with content.

---

## 3. Version declaration

Every SSL file must contain exactly one version declaration as its first non-comment statement.

```
SSL_VERSION := 5.0
```

Valid versions: `4.0`, `4.1`, `5.0`. The loader uses this to select the correct parser and compatibility shims.

---

## 4. Extends declaration

An SSL file may optionally extend a parent SSL via:

```
@extends base_v5
```

The parent is resolved by name (no `.ssl` suffix). Resolution order:

1. Same directory as the child file
2. `$AGENTS_DIR` (shared base SSLs)
3. Standard library location

Inheritance is single (no multiple inheritance). Cycles are an error.

---

## 5. Attributes

Attributes are typed key-value pairs at the top level.

```
<identifier> := <value>
```

### 5.1 Identifiers

Attribute names are lowercase ASCII with underscores: `[a-z][a-z0-9_]*`. Examples: `agent_name`, `surface`, `max_tokens`.

### 5.2 Value types

| Type | Example | Notes |
|---|---|---|
| `string` | `"hello world"` | Double-quoted. Escapes: `\n`, `\t`, `\"`, `\\` |
| `number` | `0.85` · `100` | Integer or decimal. No scientific notation. |
| `bool` | `true` · `false` | Lowercase only |
| `array` | `["a", "b", "c"]` | Homogeneous. Elements separated by `,` |
| `identifier` | `bluewave` | Unquoted. Used for type-like values (model names, tone names) |
| `null` | `null` | Explicit absence |

### 5.3 Reserved attributes

These attributes have canonical meaning and the loader may consume them directly:

| Attribute | Type | Required | Purpose |
|---|---|---|---|
| `SSL_VERSION` | number | yes | Spec version |
| `agent_name` | string | yes | Human-readable agent name |
| `agent_id` | string | no | Machine ID (slug). Default: `slugify(agent_name)` |
| `surface` | string | yes | One of: `x`, `linkedin`, `telegram`, `reels`, `briefing`, `chat`, `multi` |
| `language` | string | no | ISO 639-1 code. Default: `en` |
| `fallback_language` | string | no | Fallback for mixed-language threads |
| `timezone` | string | no | IANA zone. Default: `UTC` |
| `principal` | string | no | Name of the tenant/operator the agent serves |
| `model` | identifier | no | Preferred LLM. Default: loader decides |
| `temperature` | number | no | `0.0`–`1.5`. Default: `0.7` |
| `max_tokens` | number | no | Default: loader decides |
| `persona_archetype` | string | no | Free-form archetype label |

Unknown attributes are permitted but ignored by the canonical loader. They may be consumed by third-party tools.

---

## 6. Blocks

A block is a named section with free-form body.

```
@<block_name> {
  <body>
}
```

### 6.1 Block names

Block names are lowercase ASCII with underscores, prefixed with `@`. Reserved blocks have canonical meaning (section 7). Unknown blocks are permitted but may be ignored by validators.

### 6.2 Block bodies

A block body is free-form text between `{` and `}`, trimmed of leading/trailing whitespace. The body may contain:

- Prose (used directly in the compiled prompt)
- Nested key-value lists (syntax: `key: value` per line)
- Bullet lists (syntax: `- text` per line)
- Numbered lists (syntax: `1. text` per line)

The loader passes block bodies into the compiled system prompt verbatim, preserving structure. SSL does not evaluate them.

### 6.3 Block merging

When a child SSL extends a parent and redeclares a block with the same name, the child's body **replaces** the parent's by default.

To **append** to the parent's body, prefix with `@merge`:

```
@merge voice {
  - additional voice rule for this child
}
```

The compiled output concatenates parent body + merge body with a blank line separator.

### 6.4 Duplicate blocks

Declaring the same block name twice in the same file without `@merge` is an error.

---

## 7. Canonical blocks

These blocks have defined meaning. Using them correctly makes your SSL loadable by any compliant tool.

### 7.1 `@identity`

**Required.** Who the agent is. First-person or second-person prose describing the agent's role, telos, and relationship to its principal.

```
@identity {
  You are Wave, Manuel's personal strategist. Not an assistant. You are
  the counsel he does not have — the partner a solo operator needs at 2am.
}
```

Length guidance: 80-400 words.

### 7.2 `@voice`

**Required.** How the agent speaks. Declarative bullets.

```
@voice {
  - English default, PT-BR when principal writes PT first
  - Short sentences predominate
  - Zero emojis
  - Zero buzzwords: synergy, leverage, disrupt
  - One historical reference per response, maximum
}
```

### 7.3 `@doctrine` or `@principles`

Axioms the agent applies as first principles. Numbered list preferred.

### 7.4 `@response_modes`

How the agent structures output by context. Common modes:

- `conversation` — direct, 1-3 paragraphs
- `counsel` — structured 5-block strategic counsel
- `briefing` — daily digest format
- `draft` — content-production mode

### 7.5 `@commitments`

Operational rules the agent follows every response.

### 7.6 `@limits`

Hard behavioral limits. Framed as strategy, not as refusal. These preserve long-term value.

```
@limits {
  - No content that exposes the principal to legal risk
  - No targeting of identified individuals for harm
  - No deepfakes, non-consensual sexual content, CBRN instructions
  - No lying to the principal
}
```

### 7.7 `@knowledge`

Declaration of external knowledge sources the agent reads at runtime.

```
@knowledge {
  read: /root/bluewave/tenants/<tid>/knowledge_base.md
  scope: full
  refresh: per_request
}
```

### 7.8 `@context_snapshot`

Point-in-time context about the principal or tenant. Updated periodically.

### 7.9 `@tools`

Tools available to the agent (for tool-use capable models).

```
@tools {
  web_search: true
  code_exec: false
  image_gen: false
}
```

### 7.10 `@examples`

Few-shot examples showing good/bad outputs.

```
@examples {
  GOOD (morning briefing):
    "radar · 06:30 · 3 signals
     1. BTC +4% overnight, broke 680k on BR volume
     2. ..."

  BAD:
    "Good morning! Here is your daily briefing!"
}
```

### 7.11 `@rhythm`

Time-based behaviors (daily briefing at 06:30, weekly report Monday, etc).

---

## 8. Compiler output

The SSL loader compiles an SSL file into a system prompt through this sequence:

1. Parse file → AST
2. Resolve `@extends` chain, merge parent → AST'
3. Validate AST' against spec (section 9)
4. Inject runtime context (tenant profile, knowledge base, principal name from JWT) → compiled AST
5. Render compiled AST as prompt text:
   - Top-level prose header from `@identity`
   - Block bodies concatenated in canonical order:
     `@identity` → `@doctrine` → `@voice` → `@knowledge` → `@response_modes` → `@commitments` → `@limits` → `@context_snapshot` → `@examples` → `@rhythm` → unknown blocks
   - Runtime context injected as `@tenant_context` block before `@identity`

---

## 9. Validation rules (normative)

A valid SSL v5.0 file must satisfy all of:

1. Exactly one `SSL_VERSION := 5.0` declaration, before any other non-comment statement.
2. `agent_name` attribute present, non-empty string.
3. `surface` attribute present, value is one of the enumerated surfaces.
4. At least one `@identity` block (in the file or inherited from parent).
5. At least one `@voice` block (in the file or inherited from parent).
6. No cyclic `@extends` chain.
7. No duplicate non-`@merge` blocks.
8. All reserved attribute values conform to their declared types.

A **well-formed** SSL additionally satisfies:

9. `@limits` block is present somewhere in the extends chain.
10. `@voice` contains at least 3 bullets or 50 words of guidance.
11. `language` attribute declared (defaults to `en` otherwise).

Validators should treat (1-8) as errors and (9-11) as warnings.

---

## 10. Linting recommendations (informative)

A well-calibrated SSL typically:

- Names at least 5 prohibited buzzwords in `@voice`
- States tone descriptor (casual/formal/technical/bold) explicitly
- Defines at least 2 `@response_modes`
- Provides 1+ `@examples` (GOOD and BAD)
- Lists at least 3 `@limits`
- Keeps `@identity` between 80 and 400 words
- Total compiled prompt: 2k-8k tokens

---

## 11. Composition pattern (canonical)

A production SSL stack composes as follows:

```
base_v5.ssl                    # universal craft rules
  ↓ @extends
agent_<type>_v5.ssl            # surface-specific craft (e.g. twitter, radar)
  ↓ @extends
tenants/<tid>/agents/<name>.ssl  # tenant-specific override (optional)
  + runtime injection:
    @tenant_context             # from onboarding.json
    @knowledge (body)           # from knowledge_base.md
    @principal (header)         # from JWT name claim
```

This gives four layers of calibration, as described in the Voice Engineering section of bluewaveai.online.

---

## 12. Version history

- **v5.0** (2026-04-24): Formalized spec. Canonical blocks defined. Parser/linter/registry released.
- **v4.1** (2026-04-18): Added `@machiavellian` extension, no-emoji rule, PT-BR diacritics enforcement (Lex).
- **v4.0** (2026-03-15): First multi-block SSL architecture. Pre-spec informal format.

Migration from v4.x to v5.0 is lossless. Unknown-in-v4 blocks are preserved; unrecognized attributes are migrated as-is.

---

## 13. Grammar (EBNF)

```ebnf
ssl_file       = { comment | statement } ;
statement      = version_decl
               | extends_decl
               | attribute
               | block
               ;

comment        = line_comment | block_comment ;
line_comment   = "//" { any_char - newline } newline ;
block_comment  = "/*" { any_char } "*/" ;

version_decl   = "SSL_VERSION" ":=" number ;
extends_decl   = "@extends" identifier ;

attribute      = identifier ":=" value ;
value          = string | number | bool | array | identifier | "null" ;

string         = '"' { string_char } '"' ;
string_char    = any_char - ('"' | '\\') | escape ;
escape         = "\\" ('n' | 't' | '"' | '\\') ;

number         = ["-"] digit+ ["." digit+] ;
bool           = "true" | "false" ;
array          = "[" [ value { "," value } ] "]" ;
identifier     = letter { letter | digit | "_" } ;

block          = [ "@merge" ] "@" identifier "{" block_body "}" ;
block_body     = { any_char - "}" } ;

letter         = "a".."z" | "A".."Z" ;
digit          = "0".."9" ;
```

---

## 14. Reference implementation

The canonical parser, linter, and registry are published at:

```
/root/bluewave/ssl/ssl_parser.py      # parse + validate
/root/bluewave/ssl/ssl_linter.py      # quality checks
/root/bluewave/ssl/ssl_registry.py    # index of SSLs in system
/root/bluewave/ssl/base_v5.ssl        # canonical base
/root/bluewave/ssl/migrate_v4_to_v5.py  # upgrade script
```

Use:

```bash
python3 -m ssl_parser path/to/agent.ssl         # validate + print AST
python3 -m ssl_linter path/to/agent.ssl         # quality checks
python3 -m ssl_registry list                    # list all SSLs
python3 -m ssl_registry show <name>             # show compiled prompt
```

---

## 15. License

SSL v5.0 spec is published under CC BY 4.0. Reference implementation is MIT. Use it, extend it, build tools that adopt it. Credit Bluewave when material.

---

*End of specification.*
