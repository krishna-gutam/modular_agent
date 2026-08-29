---
name: project-planner
description: Turn a project idea into a flat implementation plan — every class and function that needs to exist, written as one-line signatures with full type hints, grouped by file — then refine that plan across turns as the user adds requirements, corrects names, or changes scope. Use this whenever someone describes something they want to build and wants structure before code, e.g. "plan out this project", "what functions do I need", "sketch the architecture", "give me the skeleton", "break this down into modules", "what classes should I write". Also use it on every follow-up message once a plan exists — "add auth", "drop the CLI", "expand the parser", "make it async" are all plan refinements, not new plans. Prefer this over writing implementation code when the user is still deciding what to build.
---

# Project Planner

Produce one artifact: a signature-level map of the whole project. No bodies, no
pseudocode, no prose explaining each piece. The value is that a person can read
the entire system in thirty seconds and see where every responsibility lives.

The plan lives in a file and is **edited in place** on every follow-up. It is a
living document, not a series of fresh answers.

## The output format

Write to `PLAN.md` (in the outputs directory) and present it. Exact structure:

````markdown
# <Project name>

<One sentence: what it does. One line: language, runtime, key libraries.>

## src/config.py
```python
@dataclass
class Settings:
    api_key: str
    timeout: float = 30.0
def load_settings(path: Path | None = None) -> Settings
```

## src/models.py
```python
@dataclass
class Article:
    url: str
    title: str
    published: datetime | None
class ParseError(Exception): ...
```

## src/fetcher.py
```python
class Fetcher:
    def __init__(self, settings: Settings, session: ClientSession) -> None
    async def fetch(self, url: str) -> str
    async def fetch_many(self, urls: Sequence[str]) -> list[str]
    async def close(self) -> None
def build_fetcher(settings: Settings) -> Fetcher
```

## Open questions
- Store results in SQLite or flat JSON?
- Retry policy on 429 — backoff or fail fast?
````

Rules that make it readable:

- **One line per callable.** Signature only. No `pass`, no `...` after functions,
  no docstrings, no bodies. Dataclass and named-tuple fields are the exception:
  those get a line each, since the field types *are* the design.
- **No inline commentary.** If a name needs explaining, the name is wrong — fix
  the name instead. Add a trailing `# comment` only where a type genuinely can't
  express the constraint (units, invariants: `def seek(self, ms: int) -> None`).
- **Full type hints everywhere**, including `-> None`. Concrete types over `Any`.
  Prefer protocol/interface types on parameters (`Sequence`, `Iterable`, `IO[str]`)
  and concrete types on returns.
- **Group by file, ordered by dependency** — types and config first, then the
  layers that consume them, then entry points. A reader should never hit a name
  before its definition.
- **Path headers, not module names**: `## src/api/routes.py`, so the plan doubles
  as a directory layout.
- **Keep `Open questions` short and real** (3-6 items max). Every question should
  be one the user can actually answer, and answering it should change the plan.
  Delete each one as it gets resolved. Drop the section when it empties.

## Scale the plan to the project

Twelve functions for a scraper, not eighty. Aim for the smallest set of
signatures that still covers every requirement the user stated. If a helper only
exists because you imagined it might be handy, cut it.

Include private helpers (`_normalize_url`) only where they carry real design
weight. Skip trivial ones.

That said, a first pass shouldn't be thin. Sweep these before presenting, and
include the ones that genuinely apply:

- Entry point / CLI / server bootstrap
- Configuration and secrets loading
- Core domain types (dataclasses, enums, protocols)
- The main pipeline, decomposed into named steps
- Persistence and external I/O boundaries
- Error types the caller is expected to catch
- Test seams — where would a fake get injected?

## Refining across turns

Every message after the first plan is a mutation. Handle it like this:

1. **Classify the change** — add, remove, rename, retype, split one function into
   several, merge several into one, or expand one region into more detail.
2. **Propagate it.** A rename updates every call site's parameter types. Making
   one function `async` colors its callers. A new dependency changes the
   constructor that receives it. Half-applied changes are the main failure mode
   here — the plan stops being trustworthy the moment two parts disagree.
3. **Edit `PLAN.md` in place** with targeted replacements. Preserve the ordering
   of everything untouched so the user can diff by eye.
4. **Re-present the file, then list what changed** — a few lines, below the file:

   ```
   + src/auth.py — Token, TokenStore, verify_token()
   ~ Fetcher.__init__ now takes a TokenStore
   - dropped run_sync(); everything is async now
   ? does the token refresh in-band or on a timer?
   ```

Never silently drop a signature the user asked for. If something must go because
it now conflicts, say so in the change list with the reason.

When the user's request is ambiguous in a way that changes the shape of the plan
(one big `Client` class vs. free functions; sync vs. async; library vs. CLI),
make the call that fits what they've said so far, write it into the plan, and put
the alternative in `Open questions`. Guessing and flagging beats stalling on a
question.

## Other languages

Python is the default when nothing suggests otherwise. Match the language's own
declaration syntax — the format is "one declaration line per callable, grouped by
file," not "Python specifically."

```typescript
// src/fetcher.ts
export interface Settings { apiKey: string; timeoutMs: number }
export class Fetcher {
  constructor(settings: Settings, client: HttpClient)
  fetch(url: string): Promise<string>
}
export function buildFetcher(settings: Settings): Fetcher
```

Go: `func (f *Fetcher) Fetch(ctx context.Context, url string) (string, error)`.
Rust: `pub fn fetch(&self, url: &str) -> Result<String, FetchError>`. Same idea.

## When not to use this

If the user asks for working code, write working code. If they ask for one
function, write that function. This skill is for the moment before
implementation, when the question is still "what pieces exist" — and for keeping
that map current while the answer changes.
