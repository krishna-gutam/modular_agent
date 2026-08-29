---
name: prompt-creator
description: Write a new prompt into prompts/, or improve an existing one, and verify the loader picks it up.
---

# Prompt creator

Author a prompt in this repo's `prompts/` directory. A prompt is a Markdown
file the user loads on demand with `/prompt <name> [task]`; `prompts.py`
discovers it, parses its frontmatter, and injects the body into the
conversation as a user turn.

Before writing anything, read `skills/prompt-creator/loader-rules.md`. It lists
the constraints the loader actually enforces, including the ones that make a
prompt silently fail to appear. `skills/prompt-creator/TEMPLATE.md` is the
starting shape.

## 1. Find out what the prompt is for

Do not start writing on a one-line request. Ask, one question at a time, and
propose your own answer to each so the user can just say "yes":

- What task should this prompt handle, and what does the user type when they
  reach for it?
- What does a good response look like? Get a concrete example if you can — the
  shape of the output matters more than the topic.
- What does the model currently get wrong on this task without the prompt?
  This is the most valuable question. A prompt exists to correct a default.
- Are there rules that are non-obvious — a format, a house style, something to
  never do?

Stop asking once you can write the "Output" section without guessing. Three or
four exchanges is usually enough.

## 2. Choose the layout

Single file, `prompts/<name>.md`, is the default. Use the directory form,
`prompts/<name>/PROMPT.md`, only when the prompt needs to ship a resource
alongside it — a checklist, a style guide, a schema, an example file. Loose
files at the top level of `prompts/` are read as prompts in their own right, so
a bundled resource must live inside a directory.

## 3. Pick the name

Kebab-case, lowercase, verb-first where it reads naturally: `code-review`,
`explain-code`, `write-tests`. Then check it against what already exists:

```
python -c "import prompts, skills; print(sorted(prompts.discover_prompts())); print(sorted(skills.discover_skills()))"
```

Reject a name that duplicates an existing one, or that is a strict prefix of
another (`test` alongside `test-plan` makes `/prompt test` ambiguous).

## 4. Write it

Follow `TEMPLATE.md`. What separates a prompt that works from one that does
nothing:

- **Correct a default, don't describe the task.** "Review this code" changes
  nothing. "Report only findings you can point at with a line number" does.
- **Be concrete about output.** Name the sections, the order, the length. If
  the user showed you an example, encode its shape.
- **Write rules as prohibitions where you can.** "No praise, no summary of what
  the code does" is enforceable. "Be concise" is not.
- **Keep it short.** Under 60 lines. Every line the user does not need is a
  line that dilutes the ones they do.
- **Do not restate the model's general instructions.** No "be helpful", no "be
  accurate". Assume a competent model and correct only this task's failure mode.
- **Write for a user turn, not a system prompt.** The body arrives mid-
  conversation, wrapped in BEGIN/END markers, and may be followed by
  `Task: <thing>`. Say "the user names or pastes" rather than assuming the
  input is already present.
- **Reference bundled files by their repo-relative path**, e.g.
  `prompts/code-review/checklist.md`, and say when to read them. They are
  listed to the model, not inlined.

## 5. Write to disk

Use `apply_patch` to edit an existing prompt. Use `run_powershell` to create a
new file or directory. Write the file, then read it back and show the user the
frontmatter block and the first few lines — a mangled `---` fence is the most
common failure and it fails silently.

## 6. Verify

Always run this before telling the user you are done:

```
python -c "import prompts; c=prompts.discover_prompts(force=True); p=c['<name>']; print(p['name'], '|', p['description']); print('files:', p['files']); print(prompts.render(p, 'sample task')[:400])"
```

Confirm three things: the prompt appears, the description is non-empty, and any
bundled files are listed. If it does not appear, the body is empty or the
frontmatter fence is malformed — check `loader-rules.md` before editing blind.

Finish by telling the user to run `/prompts reload`, since the catalog is
cached for the life of the process.

## Rules

- One prompt per request unless the user asks for a set.
- Never write a prompt whose body is a restatement of its own description.
- If the user's request is already covered by an existing prompt, say so and
  offer to improve that one instead of adding a near-duplicate.
- If the task really needs a tool rather than instructions, say so. A prompt
  cannot do what the model has no tool for.
