---
name: understand-plan
description: Clarify a user's plan or feature requirements via a short series of targeted questions (3–5 max). Use only when the user explicitly asks to clarify a plan, gather requirements, or mentions "understand-plan" / "уточни план".
---

Clarify the user's plan, identify key dependencies, and resolve critical ambiguities without endless questioning.

## When NOT to use
- Simple bug fixes, typos, or routine refactoring with clear instructions.
- Tasks where the user explicitly asks to implement code right away.
- Deep architectural stress-testing (use `grill-me` for that).

## How to ask questions
- Use the **question** tool for every question you ask. Never pose questions as plain text.
- Ask **one question at a time** and wait for the answer.
- Provide 2–4 concrete multiple-choice options representing realistic choices (the user can always type a custom answer).
- Keep it concise: aim for 3–5 high-impact questions total, focusing only on blockers and key architectural choices.

## Flow
1. First, explore the relevant codebase and `SPEC/` files yourself to avoid asking questions already answered in the repo.
2. When a critical ambiguity remains, ask one targeted question via `question`.
3. After receiving an answer, briefly acknowledge the choice (1 sentence max) and either ask the next question or finish.
4. Once key requirements are clear, output a structured summary using this format:

### Краткое резюме
- **Цель:** [1 sentence]
- **Принятые решения:** [bullet points of answers]
- **Границы задачи (Scope):** [what is included / excluded]