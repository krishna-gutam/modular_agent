# Skeleton

Copy, fill, delete what doesn't apply.

```markdown
---
name: <lowercase-hyphenated>
description: <Verb-first, one line, under 90 chars, names the artifact.>
---

# <Title>

<One sentence stating what this produces.>

## Steps

1. <First action. Concrete.>
2. <...>

## Rules

- <A correction the model would otherwise get wrong.>
- <What to do when the input is ambiguous or malformed.>
- <What NOT to emit.>

## Output

<The exact shape of the result. Code block? Prose? How long?>
```

# Pre-ship checklist

Read the draft as if you were the model receiving it with no other context.

Frontmatter
- `name` is lowercase-hyphenated and matches the directory/filename
- No existing skill shares a prefix with it
- `description` names the artifact and fits one padded catalog line

Body
- Written in the imperative, addressed to the model
- Every rule is decidable — you could check compliance without judgement calls
- At least one rule kills a specific default failure (padding, hedging,
  offering a menu of options, restating the question)
- Ambiguous or malformed input is handled in at least one line
- Output section says both what to emit and what to stop after
- Nothing in the body merely describes the skill

Scope
- Does one job; does not overlap an existing skill
- 20–150 lines; longer content moved to a bundled file
- Bundled files, if any, are referenced from the body with a condition for
  opening them

Mechanics
- No reference to unregistered tools (only `run_powershell`, `apply_patch`)
- File actually written under `skills/`
- User told to run `/skills reload`

# Smells

| Symptom | Fix |
|---|---|
| Body opens with "This skill helps you…" | Delete it. Start with the first instruction. |
| Rules are adverbs ("carefully", "thoroughly") | Replace with a checkable constraint. |
| A `## When to use` section | Delete. Invocation is explicit. |
| Every run reads the bundled file | Inline it. |
| Two unrelated jobs in one skill | Split into two skills. |
| Skill is 8 lines of vibes | Not a skill. Just do the task. |
