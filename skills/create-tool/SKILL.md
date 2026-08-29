---
name: create-tool
description: Add a new agent-callable tool to the tools/ package, wired to the @tool decorator.
---

# Create a tool

Write one new tool for this agent. A tool is a plain Python function in the
`tools/` package, decorated with `@tool(...)`, that the model can call by name.

Read `tools/decorator.py` and `tools/__init__.py` before writing anything. The
loader has behaviour you cannot guess from the outside, and the notes below
depend on it.

## Before you write

Ask for whatever is missing, one question at a time. Do not invent answers to:

- **What should it do**, in one sentence.
- **What comes in.** Every parameter, its type, and whether it is optional.
- **What goes out.** What the model is meant to read in the result.
- **What it touches.** Files, network, subprocesses, anything outside the
  process. This decides how careful the failure handling has to be.

If an existing tool already covers it, say so and stop. `run_powershell` is a
shell; do not wrap a one-line shell command in a new tool.

## The shape

One tool per file, at `tools/<name>.py`. Start from
`skills/create-tool/template.py` — read it, do not retype it from memory.

```python
from .decorator import tool

@tool("""One line on what it does.

    Args:
        path: What this is, and what a valid value looks like.
    """)
def read_config(path: str) -> str:
    """Same text as above."""
    ...
```

The decorator argument is what the model sees. The docstring is a fallback for
humans reading the source. Keep both, and keep them identical.

## Rules the loader enforces

These are not style preferences. Break one and the tool misbehaves or silently
disappears.

1. **Import the decorator relatively:** `from .decorator import tool`.
2. **The function name is the tool name.** It must be unique across the whole
   `tools/` package — `_DECORATED_TOOLS` is a dict keyed on `__name__`, so a
   collision silently overwrites the earlier tool. Check the existing names
   first.
3. **Annotate every parameter.** The JSON schema is built from
   `inspect.signature`. Only `str`, `int`, `float`, `bool`, `list` and `dict`
   map to real types; anything else, including a missing annotation, becomes
   `"string"`. `Optional[X]` is unwrapped to `X`.
4. **A parameter with no default is required.** That is the only thing that
   makes it required. If it is optional, give it a default.
5. **Return a string.** `execute_tool` returns strings as-is and `json.dumps`
   anything else. A hand-formatted string reads better to the model than a
   serialised dict.
6. **Never let an exception escape as the happy path.** `execute_tool` catches
   everything and returns `{"error": "..."}`, which tells the model nothing
   useful. Catch what you expect and return an error string that says what
   failed and what to try instead.
7. **No import-time side effects and no imports that can fail.** `load_tools`
   wraps each module import in a bare `except Exception: pass`. A typo or a
   missing dependency does not raise — the tool just never appears in the list.
8. **Do not import `tools/__init__.py` from your module.** It imports you.

## Arguments

- Take the smallest number of parameters that does the job. Every optional
  parameter is another thing the model can get wrong.
- Name them for what they are, not what they are for: `path`, not `input_arg`.
- If the tool does something destructive or expensive, add a required
  `justification: str` parameter, the way `run_powershell` does. It costs
  nothing and it shows up in the approval dialog in `app.py`.
- Paths are relative to the active workspace, which is the process cwd. If the
  tool takes a path, use `workspace.resolve()` to reject anything that escapes
  the project, and return an error rather than reading outside it.

## Output

Write for a reader with no other context.

- Say what happened, concretely. `"Wrote 34 lines to config.toml"` beats
  `"Success"`.
- On failure, name the cause and the next move.
- Cap anything unbounded. A tool that can return a whole file should truncate
  and say that it truncated, or the context window absorbs the difference.

## Finishing

1. Create `tools/<name>.py`.
2. Confirm it registered:

   ```
   python -c "from tools import TOOLS; print([t['function']['name'] for t in TOOLS])"
   ```

   If the name is missing, the module raised on import and the loader swallowed
   it. Import it directly to see the real traceback:
   `python -c "import tools.<name>"`.
3. Check the generated schema, since the types come from your annotations and
   not from what you meant:

   ```
   python -c "from tools import TOOLS; import json; print(json.dumps([t for t in TOOLS if t['function']['name']=='<name>'], indent=2))"
   ```

4. Call it once through the real path, so the error handling gets exercised:

   ```
   python -c "from tools import execute_tool; print(execute_tool('<name>', {...}))"
   ```

5. Tell the user to restart. `load_tools()` runs once at import, so a running
   CLI or Streamlit session will not see the new tool until it restarts.

Report what you created, the exact tool name, its parameters, and anything you
deliberately left out.
