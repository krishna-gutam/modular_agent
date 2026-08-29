---
name: skill-creator
description: Write a new skill for this repo, or fix an existing one.
---

# Skill creator

Turn a request like "make me a skill that does X" into a working skill file on
disk in `skills/`, then tell the user how to load it.

A skill in this project is **a Markdown file of instructions that the user loads
on purpose** with `/skill <name>`. Nothing here auto-triggers. That single fact
drives every rule below: you are writing an instruction sheet for a model that
has already been told to follow it, not a pitch competing for attention.

## Before writing anything

Ask only what you cannot infer. Usually one or two of these:

1. **What is the repeated task?** A one-off request is just a request — say so
   and do the task instead of writing a skill.
2. **What does "done" look like?** A commit message, a review with findings, a
   refactored file. If you cannot name the artifact, the skill has no spine.
3. **What does the model get wrong without it?** This is the real content. A
   skill that only says "be helpful and thorough" is dead weight.

If the user already gave you all three, skip the questions and write.

## Layout

Single file, no bundled resources:

```
skills/<name>.md
```

Directory, when the skill ships a checklist, template, or reference:

```
skills/<name>/
    SKILL.md          <- required, this is the entry point
    checklist.md      <- optional, any name
```

Start single-file. Promote to a directory only when a chunk of content is
reference material the model should consult *conditionally*. Anything needed on
*every* run belongs inline in `SKILL.md`.

Name the directory exactly what you put in `name:` — a mismatch like
`skills/grill me/` against `name: grill-me` makes resolution unpredictable. Note
that a loose `skills/foo.md` meant as a bundled resource will be picked up as a
skill in its own right; put shared resources inside a skill directory.

## Frontmatter

```
---
name: commit-message
description: Turn a diff or a description of changes into a conventional commit message.
---
```

- `name` — lowercase, hyphenated, no spaces. This is what the user types.
  Prefix-matching means `/skill commit` should reach it unambiguously; check the
  existing skills for a collision before you settle on a name.
- `description` — one line, under ~90 chars, verb first. It is printed in a
  padded column by `/skills`, so it must read as a menu entry. Write what the
  skill *produces*, not what it is about. "Review a file or diff for bugs and
  risky changes" beats "A skill for code review."

Both are optional to the parser and mandatory in practice: a skill without a
description shows up as `(no description)` and will never be chosen.

## Body

Write in the imperative, addressed to the model. Not "this skill will help you
review code" — "Read the file, then report findings worst-first."

Structure that works:

```markdown
# <Title>

<One sentence: what this produces.>

## Steps          <- or ## Format, if the output shape is the hard part

1. ...
2. ...

## Rules

- <The corrections. This is the section with actual value.>

## Output

<Exactly what to emit, and what not to emit.>
```

Rules for the rules:

- **Encode corrections, not manners.** Every line should be something a
  competent model gets wrong by default. "Be concise" is noise. "One message,
  not a menu of options, unless the user asks for alternatives" kills a real
  failure.
- **Be decidable.** "Subject under 60 chars, imperative, no trailing period"
  can be checked. "Write a good subject line" cannot.
- **Say what not to do.** Models pad, hedge, and offer options. If you don't
  forbid it, you get it.
- **Handle the ambiguous input** — the diff that does two things, the missing
  file. One line each. This is where most skills fail in practice.
- **Stay in scope.** A commit-message skill does not also review the code.

Aim for 20–80 lines of body. Under 20 and it probably isn't a skill. Over ~150
and you are writing documentation — move the bulk into a bundled file.

## Bundled files

Files next to `SKILL.md` are listed to the model automatically when the skill
loads, with their paths relative to the project root. They are *listed*, not
inlined — the body must say when to open one:

```markdown
Consult `skills/code-review/checklist.md` before reporting, and only for
files over ~100 lines.
```

Read them with `run_powershell` (`Get-Content <path>`). Note that the loader's
own preamble mentions a `read_file_tool`; that tool is not registered in
`tools/`, so do not instruct the model to call it.

## Writing the file

Create the file with `run_powershell`, and say what you're doing in the
justification. Heredoc-style content survives PowerShell best as a here-string:

```powershell
New-Item -ItemType Directory -Force -Path skills\<name> | Out-Null
@'
---
name: <name>
description: <one line>
---

<body>
'@ | Set-Content -Path skills\<name>\SKILL.md -Encoding utf8
```

Single-quoted here-strings (`@'` … `'@`) do not interpolate — necessary, since
skill bodies are full of `$`, backticks, and braces. The closing `'@` must sit
at column zero.

To modify an existing skill, use `apply_patch` on the section that changes.
Never rewrite a whole file to change three lines.

## After writing

1. Print the finished skill body back to the user in a code block.
2. Tell them to run `/skills reload`, then `/skill <name>`. The catalog is
   cached in `skills.py`; without a reload the new skill is invisible.
3. Name one thing you were unsure about, if there was one. Skills are cheap to
   revise and expensive to use when wrong.

## Do not

- Write a body that *describes* the skill. The body **is** the instructions.
- Add a `## When to use this skill` section — the user already chose it by
  typing the command, so it is pure token cost.
- Invent tools. Only `run_powershell` and `apply_patch` are registered.
