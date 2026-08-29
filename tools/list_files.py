import os
from .decorator import tool

@tool("""List files and directories in a directory.

    Args:
        path: Path to the directory, relative to the workspace root. Defaults to "." (workspace root).
    """)
def list_files(path: str = ".") -> str:
    """List files and directories in a directory.

    Args:
        path: Path to the directory, relative to the workspace root. Defaults to "." (workspace root).
    """
    root = os.path.abspath(os.getcwd())
    full = os.path.abspath(os.path.join(root, path))
    
    # Ensure the path is within the workspace
    if not full.startswith(root + os.sep) and full != root:
        return f"Error: {path} is outside the workspace."

    if not os.path.isdir(full):
        return f"Error: {path} is not a directory or does not exist."

    try:
        entries = os.listdir(full)
    except OSError as e:
        return f"Error reading directory {path}: {e}"

    # Sort entries alphabetically (case-insensitive)
    entries.sort(key=lambda s: s.lower())

    # Build result with directories marked by a trailing slash
    result_lines = []
    for entry in entries:
        entry_path = os.path.join(full, entry)
        if os.path.isdir(entry_path):
            result_lines.append(entry + "/")
        else:
            result_lines.append(entry)

    result = "\n".join(result_lines)
    result += f"\n\n--- Total items: {len(entries)} ---"
    
    return result