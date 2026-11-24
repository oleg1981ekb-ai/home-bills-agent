---
name: llm-council
description: Convene a council of independent agents that answer a hard question separately, blind-review and rank each other's answers, then synthesize one vetted answer.
---

# LLM Council

Convene an expert council to pressure-test a question or decision. Each member answers independently (blind), then they blind-review and rank each other's answers, then the Chairman (main loop) synthesizes one vetted answer.

## Modes

- **Default (Claude council):** 5 sub-agents with different lenses (Pragmatist, Red-teamer, Domain rigorist, First-principles, Generalist). Fast, free, no external calls.
- **Cross-vendor (faithful council):** Real different providers via OpenRouter (Gemma, Nemotron, Dots). Costs money, opt-in only. Use when you say "cross-vendor", "real models", "use openrouter", or pass `--cross-vendor`.

## How to run

1. Identify the question to stress-test.
2. Pick mode: default (unless user explicitly asks for cross-vendor).
3. **Stage 1:** Spawn 5 sub-agents in parallel, each with the same question + its lens.
4. **Stage 2:** Label answers A–E, strip identity. Spawn 5 reviewers in parallel to rank them.
5. **Stage 3:** Synthesize as Chairman — build final answer from strongest reasoning, note splits, take a position.

## Output

- **The answer** — synthesized recommendation, stated directly.
- **Council notes** — 3–5 lines: agreements, disagreements, aggregate ranking, overrides.

## Cross-vendor mode

Only when opted in. Run:
```
python3 scripts/council_openrouter.py "the question"
```

Default models: `google/gemma-4-31b-it:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`, `dots-studio/dots-3-note-preview:free`.

Requires `OPENROUTER_API_KEY` in `.env`.