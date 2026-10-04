# Open Questions (QUESTION-xxx)

Agents append new questions here instead of guessing (LM-ARCH-001 §1.2, AGENTS.md
"Stop and ask"). One entry per question. A QUESTION-xxx stops the sub-task that
raised it; other work continues.

Format (append below, keep reverse-chronological order — newest first):

```
## QUESTION-<next-number> — <short title>
- Date: <YYYY-MM-DD>
- Raised by: <WP/task>
- Question: <what needs a human decision?>
- Context/evidence: <spec sections, fixture or registry evidence, code paths>
- Why we must not guess: <what could go wrong>
- Default if unanswered: <safe fallback, or "none — blocks <milestone>">
- Status: OPEN | ANSWERED (<answer summary>) | SUPERSEDED (by <id>)
```

Seed numbering continues from the spec's own open questions (Q-01…Q-12, LM-ARCH-001
§24); agent-raised questions use QUESTION-101 onwards to avoid ID collisions.

No QUESTION-xxx entries yet.
