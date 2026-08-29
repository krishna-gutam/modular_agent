# What the loader actually enforces

Everything here is behaviour of `prompts.py` in this repo. Check a new prompt
against it before claiming the prompt works. Most failures are silent.

## Where prompts live

`PROMPTS_DIR` is resolved from the location of `prompts.py`, not the current
working directory. Prompts sit beside the app and follow the user across
workspaces. Never write a prompt into the user's project directory.

## Which files are discovered

Entries directly inside `prompts/` are scanned in sorted order:

| Entry | Result |
|---|---|
| `prompts/<name>.md` | a prompt, named after the file |
| `prompts/<name>/PROMPT.md` | a prompt, named after the directory |
| `prompts/<name>/anything-else` | a bundled file of that prompt |
| `prompts/<name>/` with no `PROMPT.md` | ignored entirely |
| any entry starting with `.` or `__` | ignored |
| a top-level file that is not `.md` | ignored |

The filename must be exactly `PROMPT.md`. `prompt.md` or `Prompt.md` inside a
directory is not found, and the directory is skipped without a message.

A loose `.md` at the top level is a prompt in its own right — it cannot be a
bundled resource for anything. This is why bundled files must live inside a
directory. (`skills/checklist.md` in this repo is the mistake to avoid: it
shows up in `/skills` as a skill named `checklist`.)

## Frontmatter

Optional, but always write it. The parser is not YAML:

- The file must **start** with `---`, at position zero, no blank line before it.
- The block ends at the first line that is exactly `---`, found as `\n---`.
- Each line is split on the **first** colon. Key is lowercased and stripped.
  Value is stripped, then stripped of surrounding quotes.
- Lines with no colon are skipped. Lines starting with `#` are skipped.
- Nested structures, lists, and multi-line values are **not** supported. A
  value containing a colon is fine — only the first one splits.

Recognised keys are `name` and `description`. Anything else is parsed and
ignored.

**Missing closing fence.** If there is no closing `---`, the parser does not
error. It treats the whole file as body, so the `---` and the `name:` /
`description:` lines are sent to the model as instructions, and the prompt is
named after its file with no description. If a prompt appears in `/prompts`
with `(no description)` and you wrote one, this is why.

## The two silent failures

1. **Empty body.** After frontmatter is stripped, a body that is empty or
   whitespace-only means the prompt is skipped with no message. A file that is
   nothing but frontmatter does not exist as far as the loader is concerned.
2. **Duplicate name.** Prompts are keyed on `name.lower()`. Two prompts
   resolving to the same name means the later one in sorted order silently
   wins. The `name` in frontmatter overrides the file or directory name, so a
   directory called `review` whose frontmatter says `name: code-review` will
   collide with `prompts/code-review.md`.

## Name resolution

`resolve()` tries, in order: exact match, prefix match, substring match, then
fuzzy match at a 0.6 cutoff. At each stage, one hit wins and more than one hit
returns an "ambiguous" error listing the candidates.

The consequence for naming: **do not make one prompt name a prefix or substring
of another.** With both `test` and `test-plan` installed, `/prompt test` still
resolves (exact match wins), but `/prompt te` is ambiguous and `/prompt plan`
only works because it hits one substring. Prefer names that diverge in their
first few characters.

Directory names may contain spaces (`skills/grill me/` works), but the space
breaks `/prompt <name> <task>` parsing, which splits the argument on the first
space. Always set `name` in frontmatter to a space-free value.

## Bundled files

For a directory prompt, every file under it is collected recursively, except:

- `PROMPT.md` itself, but only the one at the top of the directory — a
  `PROMPT.md` in a subdirectory is listed as a bundled file
- files whose name starts with `.`
- everything under a subdirectory starting with `.` or `__`

Paths are recorded relative to the repo root, e.g.
`prompts/code-review/checklist.md`, and sorted.

They are **listed, not inlined.** The rendered prompt tells the model the paths
exist and to read them with `run_powershell` only if the instructions call for
it. So a prompt that depends on a bundled file must say so explicitly in its
body, by path. Bundling a file and never mentioning it means it is never read.

## What the model actually receives

`render()` builds a single user turn:

```
[prompt: <name>]

The instructions below were loaded from <path> at the user's explicit request.
Follow them for this task and for the rest of this conversation, unless the
user says otherwise.

--- BEGIN PROMPT ---
<body>
--- END PROMPT ---

Files bundled with this prompt (...):
  - <path>

Task: <task>
```

Two things follow from this:

- The body is a **user turn**, not a system prompt, and it persists for the
  rest of the conversation. Write instructions that make sense arriving
  mid-chat.
- When `/prompt <name>` is used with no task, the trailing line instead asks
  the model to confirm in one short line that the prompt is loaded and state
  what it needs. Do not write a body that duplicates that acknowledgement.

Avoid emitting the literal string `--- END PROMPT ---` inside a body.

## Caching

`discover_prompts()` caches in a module-level `_CACHE` for the life of the
process. A new or edited prompt is not picked up until `discover_prompts(force=True)`
runs, which is what `/prompts reload` and the 🔄 button in the Streamlit
sidebar call. Always tell the user to reload after a write.
