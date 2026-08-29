"""Template for a new tool. Copy to tools/<name>.py and edit.

This file lives in skills/, not in tools/, so it is never loaded as a tool.
It is a working example: read it, then write the real thing.
"""

import os

from .decorator import tool

# Guard rails. Pick numbers that suit the tool and say so in the output when
# you hit them, rather than silently returning a partial result.
MAX_CHARS = 4000


@tool("""Read a UTF-8 text file from the active workspace.

    Args:
        path: Path to the file, relative to the workspace root.
        max_chars: Stop after this many characters. Defaults to 4000.
    """)
def read_workspace_file(path: str, max_chars: int = MAX_CHARS) -> str:
    """Read a UTF-8 text file from the active workspace.

    Args:
        path: Path to the file, relative to the workspace root.
        max_chars: Stop after this many characters. Defaults to 4000.
    """
    # The cwd is the active workspace. Refuse anything that climbs out of it,
    # rather than trusting the model to only ask for paths inside.
    root = os.path.abspath(os.getcwd())
    full = os.path.abspath(os.path.join(root, path))
    if full != root and not full.startswith(root + os.sep):
        return f"Error: {path} is outside the workspace."

    if not os.path.isfile(full):
        return f"Error: {path} does not exist. List the directory first."

    # Catch what you expect. Anything that escapes reaches execute_tool, which
    # turns it into {"error": "..."} and tells the model nothing it can act on.
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(max_chars + 1)
    except OSError as e:
        return f"Error reading {path}: {e}"

    # Truncate loudly. A silent cut looks like a short file.
    if len(text) > max_chars:
        return (
            text[:max_chars]
            + f"\n\n[truncated at {max_chars} chars — call again with a larger "
              "max_chars, or read a specific section]"
        )

    return text or f"{path} is empty."
