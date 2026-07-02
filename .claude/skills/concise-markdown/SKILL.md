---
name: concise-markdown
description: Use whenever writing or rewriting any Markdown doc in this repo (README, other .md files, PR/commit descriptions in markdown, design notes). Keep it short and to the point — only what a reader actually needs.
---

# Concise Markdown

Markdown docs in this repo should be short. Include only what's needed to
understand or use the thing being documented — cut everything else.

## Rules

- Include only what the reader actually needs for the doc's purpose (e.g.
  for a README: what the project is, setup, common dev commands, structure
  if non-obvious). Nothing else unless asked.
- One sentence per idea. No filler, no marketing language ("seamlessly",
  "powerful", "robust", "leverage").
- Prefer a command block or code snippet over a paragraph explaining it.
- Don't restate what's obvious from the code or from standard tooling (e.g.
  don't explain what `pytest` is).
- No speculative sections ("Roadmap", "Contributing", "License", "FAQ")
  unless the user asks for them or they already exist.
- If a section would only have one line of real content, fold it into
  another section instead of giving it its own heading.
- When updating an existing doc, don't just grow it — if you're adding
  something, look for something stale or redundant to cut first.
