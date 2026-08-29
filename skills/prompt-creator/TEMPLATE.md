# Prompt template

Copy the block below into `prompts/<name>.md` or `prompts/<name>/PROMPT.md`
and fill it in. Delete any section that has nothing real to say — an empty
heading is worse than no heading.

---8<--- start of template ---8<---

---
name: <kebab-case-name>
description: <one line, under ~80 chars, starts with a verb, shown in /prompts>
---

# <Title Case Name>

<One or two sentences: what this prompt makes the model do, and to what input.
Name where the input comes from — pasted, named as a path, or already in the
conversation.>

## How to work

<Numbered steps, only if order matters. Otherwise cut this section.>

1. <First thing. If a file must be read with a tool, say so here.>
2. <Second thing.>
3. <Third thing.>

## Output

<The shape of the response. Name the sections and their order. State the
length. If some sections are conditional, say when to drop them.>

- **<Section>** — <what goes in it>
- **<Section>** — <what goes in it>

## Rules

- <A prohibition. Something the model does by default that is wrong here.>
- <What to do when the input is missing, empty, or not what was expected.>
- <A hard limit: max number of items, max length, one answer not a menu.>

---8<--- end of template ---8<---

## Notes on each part

**Frontmatter.** Both keys are optional but always write them. Without `name`
the prompt is named after its file or directory. Without `description` the
catalog shows `(no description)`, which makes `/prompts` useless. Keep it to
flat `key: value` — the parser does not understand nested YAML or lists.

**Title.** Cosmetic. It is part of the body and the model sees it.

**How to work.** Include only when the order of operations is load-bearing, for
example "read the file before commenting on it". Otherwise it is filler.

**Output.** The section that does the most work. Vague output instructions are
the main reason a prompt changes nothing.

**Rules.** Prohibitions and edge cases. "Never invent findings", "if the input
is empty, ask for it rather than guessing", "one message, not a menu of
options".
