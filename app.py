"""
app.py
------
The Streamlit frontend for modular_agent. It renders widgets and calls into
`chat_session.ChatSession`, `skills`, `prompts` and `authoring`; it holds no
agent logic of its own, so swapping it for a TUI means rewriting this file only.

Run it with:  streamlit run app.py

The CLI (`python chatbot.py`) still works untouched — this is a second frontend
over the same core, not a replacement.

Extras beyond the CLI:  pip install streamlit streamlit-ace pillow
"""

import base64
import io
import json
import os
import subprocess
import sys
import time
import uuid

import streamlit as st

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

import authoring
import prompts as prompts_mod
import skills as skills_mod
from chat_session import ChatSession, sanitize_content, tool_name_for

try:                                   # pip install streamlit-ace for the real editor
    from streamlit_ace import st_ace
except ImportError:
    st_ace = None


# --- FILE UPLOAD HELPERS ----------------------------------------------------

MAX_IMAGE_DIMENSION = 1024          # downscale long edge to this many px before sending
MAX_TEXT_FILE_CHARS = 200_000_000       # truncate text/code file contents beyond this length

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

TEXT_EXTENSION_LANGS = {
    "txt": "", "md": "markdown", "csv": "", "tsv": "", "mmd": "",
    "py": "python", "js": "javascript", "jsx": "jsx", "ts": "typescript", "tsx": "tsx",
    "java": "java", "kt": "kotlin", "swift": "swift", "go": "go", "rs": "rust",
    "c": "c", "h": "c", "cpp": "cpp", "cc": "cpp", "hpp": "cpp", "cs": "csharp",
    "rb": "ruby", "php": "php", "pl": "perl", "lua": "lua", "r": "r", "m": "matlab",
    "html": "html", "css": "css", "scss": "scss",
    "json": "json", "yaml": "yaml", "yml": "yaml", "xml": "xml", "toml": "toml", "ini": "ini",
    "sql": "sql", "sh": "bash", "bash": "bash", "ps1": "powershell", "env": "",
}
TEXT_EXTENSIONS = set(TEXT_EXTENSION_LANGS)

# Ace uses its own mode names; anything unmapped falls back to plain text.
ACE_LANGS = {
    "python": "python", "javascript": "javascript", "jsx": "jsx", "typescript": "typescript",
    "tsx": "tsx", "java": "java", "kotlin": "kotlin", "swift": "swift", "golang": "golang",
    "go": "golang", "rust": "rust", "c": "c_cpp", "cpp": "c_cpp", "csharp": "csharp",
    "ruby": "ruby", "php": "php", "perl": "perl", "lua": "lua", "r": "r",
    "html": "html", "css": "css", "scss": "scss", "markdown": "markdown", "json": "json",
    "yaml": "yaml", "xml": "xml", "toml": "toml", "ini": "ini", "sql": "sql",
    "bash": "sh", "powershell": "powershell",
}


def file_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def is_image_file(filename: str) -> bool:
    return file_extension(filename) in IMAGE_EXTENSIONS


def read_text_file(uploaded_file) -> tuple[str, bool]:
    """Decode an uploaded text/code file. Returns (text, was_truncated)."""
    raw = uploaded_file.getvalue()
    text = raw.decode("utf-8", errors="replace")
    truncated = len(text) > MAX_TEXT_FILE_CHARS
    if truncated:
        text = text[:MAX_TEXT_FILE_CHARS]
    return text, truncated


def format_text_file_block(filename: str, text: str, truncated: bool) -> str:
    lang = TEXT_EXTENSION_LANGS.get(file_extension(filename), "")
    note = "\n*(truncated — file exceeds the size limit)*" if truncated else ""
    return f"**📄 {filename}**\n```{lang}\n{text}\n```{note}"


def encode_image_to_data_url(uploaded_file) -> str:
    raw = uploaded_file.getvalue()

    if not HAS_PIL:
        mime = uploaded_file.type or "image/png"
        b64 = base64.b64encode(raw).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    image = Image.open(io.BytesIO(raw))
    image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION))

    buffer = io.BytesIO()
    if image.mode == "RGBA":
        image.save(buffer, format="PNG")
        mime = "image/png"
    else:
        image.convert("RGB").save(buffer, format="JPEG", quality=85)
        mime = "image/jpeg"

    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def data_url_to_bytes(data_url: str) -> bytes:
    _, b64data = data_url.split(",", 1)
    return base64.b64decode(b64data)


# --- WORKSPACE FILE HELPERS -------------------------------------------------
# The core has no file-browsing module, so the editor and notes panels do their
# own I/O here — always confined to the active workspace root.

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".state", ".idea",
    ".vscode", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".next", ".chatbot",
}
MAX_LISTED_FILES = 2000


def workspace_root(session: ChatSession) -> str:
    return session.root


def _inside(root: str, path: str) -> bool:
    root = os.path.realpath(root)
    target = os.path.realpath(path)
    return target == root or target.startswith(root + os.sep)


def list_project_files(root: str) -> list[str]:
    """Editable files under the workspace, as paths relative to it."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            if file_extension(filename) not in TEXT_EXTENSIONS:
                continue
            found.append(os.path.relpath(os.path.join(dirpath, filename), root))
            if len(found) >= MAX_LISTED_FILES:
                return sorted(found)
    return sorted(found)


def read_file(root: str, rel_path: str) -> str:
    full = os.path.join(root, rel_path)
    if not _inside(root, full):
        return "Error: that path is outside the workspace."
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError as error:
        return f"Error: {error}"


def write_file(root: str, rel_path: str, content: str) -> str:
    full = os.path.join(root, rel_path)
    if not _inside(root, full):
        return "Error: that path is outside the workspace."
    try:
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
    except OSError as error:
        return f"Error: {error}"
    return f"Saved {rel_path}"


def language_for(rel_path: str) -> str:
    return TEXT_EXTENSION_LANGS.get(file_extension(rel_path), "") or "text"


def ace_language(rel_path: str) -> str:
    return ACE_LANGS.get(language_for(rel_path), "plain_text")


def run_shell(root: str, command: str) -> str:
    """Run a command in the workspace and return its combined output."""
    try:
        done = subprocess.run(
            command, shell=True, cwd=root, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        return "(timed out after 120s)"
    except Exception as error:                        # noqa: BLE001
        return f"({type(error).__name__}: {error})"
    output = (done.stdout or "") + (done.stderr or "")
    if done.returncode != 0:
        output += f"\n(exit code {done.returncode})"
    return output.strip() or "(no output)"


# --- SESSION WIRING ---------------------------------------------------------


def get_session() -> ChatSession:
    """One ChatSession for the whole app, kept across reruns.

    ChatSession owns the WorkspaceManager and SessionManager, so it is built
    once and then mutated in place — rebuilding it on every rerun would fight
    the registries for who is 'active'.
    """
    session = st.session_state.get("session")
    if session is None:
        session = ChatSession()
        st.session_state.session = session

        # The registry is checked into the repo, so a fresh clone can resume a
        # workspace that only existed on someone else's machine.
        if not os.path.isdir(session.root):
            dead = session.root
            session.create_workspace(os.getcwd())
            flash(f"Workspace `{dead}` is gone. Opened `{session.root}` instead.")

    # WorkspaceManager.resolve_workspace() doesn't chdir, so a fresh process
    # can come up pointing at the wrong directory. The tools resolve paths
    # against cwd, so keep them in step.
    if os.path.isdir(session.root) and os.path.abspath(os.getcwd()) != session.root:
        os.chdir(session.root)
    return session


def reset_workspace_widgets() -> None:
    """Drop every workspace-scoped widget value after a workspace change."""
    for key in ("edit_content", "edit_path", "editor_key", "flash", "sidebar_notes"):
        st.session_state.pop(key, None)


def flash(note: str | None) -> None:
    if note:
        st.session_state.flash = note


def reload_catalog(kind: str) -> None:
    (skills_mod.discover_skills if kind == "skill" else prompts_mod.discover_prompts)(force=True)


def skill_catalog() -> list[dict]:
    found = skills_mod.discover_skills()
    return [found[key] for key in sorted(found)]


def prompt_catalog() -> list[dict]:
    found = prompts_mod.discover_prompts()
    return [found[key] for key in sorted(found)]


# --- SIDEBAR ----------------------------------------------------------------


def _pick_folder_native() -> tuple[str | None, str | None]:
    """
    Open the operating system's native 'choose a directory' dialog.

    Order of preference:
      1. The desktop's own picker on Linux/BSD — zenity (GNOME & friends) or
         kdialog (KDE). These are what Linux users expect and need no Python
         GUI toolkit installed.
      2. A tkinter dialog in a throwaway child process (Tk insists on owning
         the main thread, which Streamlit's script runner is not).

    Returns (path, problem); at most one is truthy. `path` is None when the
    user cancels. `problem` explains why no dialog could open at all (missing
    tkinter/zenity, headless host, …) so the caller can tell the user to type
    the path manually.
    """
    # --- 1. desktop-native pickers (Linux/BSD) -----------------------------
    if os.name != "nt" and sys.platform != "darwin":
        for argv in (
            ["zenity", "--file-selection", "--directory"],
            ["kdialog", "--getexistingdirectory", os.path.expanduser("~")],
        ):
            try:
                done = subprocess.run(argv, capture_output=True, text=True, timeout=300)
            except (FileNotFoundError, PermissionError):
                continue                        # tool not installed, try the next
            except Exception as e:              # noqa: BLE001
                return None, f"`{argv[0]}` failed to run ({e})."
            if done.returncode == 0 and done.stdout.strip():
                return done.stdout.strip(), None
            if done.returncode != 0:
                return None, None               # user closed the dialog

    # --- 2. tkinter in a child process -------------------------------------
    code = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "root.attributes('-topmost', True)\n"   # don't hide behind the browser
        "print(filedialog.askdirectory())\n"
        "root.destroy()\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except Exception as e:                      # noqa: BLE001
        return None, f"Couldn't open a folder dialog ({e})."

    if done.stdout.strip():
        return done.stdout.strip(), None
    if "No module named 'tkinter'" in done.stderr:
        return None, ("No folder picker found — install `python3-tk`, `zenity`, "
                      "or `kdialog` (or type the path below).")
    return None, None                           # user cancelled


def render_workspace_panel(session: ChatSession) -> None:
    with st.container(border=True):
        st.markdown("**📂 Workspace**")

        known = session.list_workspaces()
        ids = [ws.id for ws in known]
        labels = {ws.id: f"{ws.name}  ·  {ws.path}" for ws in known}
        index = ids.index(session.workspace.id) if session.workspace.id in ids else 0

        selected = st.selectbox(
            "Switch Workspace", ids, index=index, format_func=lambda i: labels.get(i, i),
            key="workspace_picker",
        )

        if st.button("➕ Create / Open Directory", key="new_ws_btn", use_container_width=True):
            st.session_state.show_new_workspace_input = True

        if st.session_state.get("show_new_workspace_input", False):
            if st.button("📁 Browse…", use_container_width=True,
                         help="Open your operating system's folder picker"):
                with st.spinner("Waiting for the folder dialog…"):
                    picked, problem = _pick_folder_native()
                if problem:
                    st.warning(problem)
                if picked:
                    st.session_state.new_ws_base = picked
                    # Bump the key so the Location widget below remounts with
                    # the picked value instead of ignoring `value=`.
                    st.session_state.new_ws_key = str(uuid.uuid4())
                    st.rerun()

            st.session_state.setdefault("new_ws_key", "initial")
            base = st.text_input(
                "Location", value=st.session_state.get("new_ws_base", ""),
                key=f"new_ws_base_{st.session_state.new_ws_key}",
                placeholder="Click 📁 Browse…, or paste a full path",
            )
            folder_name = st.text_input(
                "New folder name (blank = use the location above):",
                key="new_ws_name_input", placeholder="my-new-project",
            )
            target = (
                os.path.join(base.strip(), folder_name.strip())
                if base.strip() and folder_name.strip() else base.strip()
            )
            if target:
                st.caption(f"Will create / open: `{target}`")

            col1, col2 = st.columns(2)
            if col1.button("Create Workspace", type="primary", disabled=not base.strip()):
                error = session.create_workspace(target)
                if error:
                    st.error(error)
                else:
                    st.session_state.show_new_workspace_input = False
                    reset_workspace_widgets()
                    st.rerun()
            if col2.button("Cancel"):
                st.session_state.show_new_workspace_input = False
                st.rerun()

        if selected != session.workspace.id:
            error = session.switch_workspace(selected)
            if error:
                st.error(error)
            else:
                reset_workspace_widgets()
                st.rerun()

        st.caption(f"**Active:** `{session.root}`")


def render_session_panel(session: ChatSession) -> None:
    with st.container(border=True):
        st.markdown("**💬 Session**")

        sessions = session.list_sessions()
        ids = [s.id for s in sessions]
        labels = {s.id: (s.name or s.id)[:28] for s in sessions}
        index = ids.index(session.session.id) if session.session.id in ids else 0

        selected = st.selectbox(
            "Switch Session", ids, index=index, format_func=lambda i: labels.get(i, i),
            key="session_picker",
        )
        if selected != session.session.id:
            error = session.switch_session(selected)
            if error:
                st.error(error)
            else:
                st.rerun()

        if st.button("➕ New Session", key="new_sess_btn", use_container_width=True):
            st.session_state.show_new_session_input = True

        if st.session_state.get("show_new_session_input", False):
            custom_name = st.text_input("Session name (optional):", key="custom_session_input")
            col1, col2 = st.columns(2)
            if col1.button("Create"):
                error = session.new_session(custom_name or None)
                if error:
                    st.error(error)
                else:
                    st.session_state.show_new_session_input = False
                    st.rerun()
            if col2.button("Cancel Session"):
                st.session_state.show_new_session_input = False
                st.rerun()

        st.caption(f"{len(sessions)} session(s) in this workspace · status `{session.session.status}`")


def render_active_model(session: ChatSession) -> None:
    """Read-only status block. Choosing a model happens in the Models tab."""
    with st.container(border=True):
        st.markdown("**🧠 Model**")
        if session.model:
            st.caption(f"`{session.model}`")
            st.caption(f"via {session.provider}")
            if not session.provider_ready(session.provider):
                st.error(f"{session.env_var_for(session.provider)} is not set.")
        else:
            st.caption("None selected — open the **🧠 Models** tab.")

        temperature = st.slider(
            "Temperature", 0.0, 2.0, float(session.temperature), 0.05, key="temperature_slider"
        )
        if abs(temperature - session.temperature) > 1e-9:
            session.set_temperature(temperature)


def render_system_prompt_panel(session: ChatSession) -> None:
    with st.container(border=True):
        with st.expander("⚙️ System prompt", expanded=False):
            text = st.text_area(
                "Sent as the first message of every request", value=session.system_prompt,
                height=140, key="system_prompt_box", label_visibility="collapsed",
            )
            if st.button("Save system prompt", use_container_width=True):
                session.set_system_prompt(text)
                st.success("System prompt updated.")
                st.rerun()


def render_skills_panel(session: ChatSession) -> None:
    with st.container(border=True):
        st.markdown("**🧩 Skills**")

        catalog = skill_catalog()
        if not catalog:
            st.caption("No skills found. Add one at `skills/<name>/SKILL.md`.")
            if st.button("🔄 Rescan skills", use_container_width=True):
                reload_catalog("skill")
                st.rerun()
            return

        names = [s["name"] for s in catalog]
        chosen = st.selectbox("Skill", names, key="skill_picker")
        description = next(s["description"] for s in catalog if s["name"] == chosen)
        if description:
            st.caption(description)

        task = st.text_area(
            "Task (optional)", height=80, placeholder="e.g. review chat_session.py",
            key="skill_task",
        )

        col1, col2 = st.columns([0.75, 0.25])
        if col1.button("▶️ Load skill", use_container_width=True):
            skill, _candidates = skills_mod.resolve(chosen)
            if skill:
                session.submit(skills_mod.render(skill, task.strip()))
                st.rerun()
            st.error(f"Couldn't resolve `{chosen}`.")
        if col2.button("🔄", key="rescan_skills_btn", use_container_width=True,
                       help="Rescan skills directory"):
            reload_catalog("skill")
            st.rerun()


def render_prompts_panel(session: ChatSession) -> None:
    with st.container(border=True):
        st.markdown("**📜 Prompts**")

        catalog = prompt_catalog()
        if not catalog:
            st.caption("No prompts found. Add one at `prompts/<name>/PROMPT.md`.")
            if st.button("🔄 Rescan prompts", use_container_width=True):
                reload_catalog("prompt")
                st.rerun()
            return

        names = [p["name"] for p in catalog]
        chosen = st.selectbox("Prompt", names, key="prompt_picker")
        description = next(p["description"] for p in catalog if p["name"] == chosen)
        if description:
            st.caption(description)

        task = st.text_area(
            "Task (optional)", height=80, placeholder="e.g. explain workspace_manager.py",
            key="prompt_task",
        )

        col1, col2 = st.columns([0.75, 0.25])
        if col1.button("▶️ Load prompt", use_container_width=True):
            prompt, _candidates = prompts_mod.resolve(chosen)
            if prompt:
                session.submit(prompts_mod.render(prompt, task.strip()))
                st.rerun()
            st.error(f"Couldn't resolve `{chosen}`.")
        if col2.button("🔄", key="rescan_prompts_btn", use_container_width=True,
                       help="Rescan prompts directory"):
            reload_catalog("prompt")
            st.rerun()



def render_sidebar(session: ChatSession) -> bool:
    """Draw the sidebar. Returns whether tools should be auto-approved."""
    with st.sidebar:
        render_workspace_panel(session)
        render_session_panel(session)
        render_active_model(session)
        render_system_prompt_panel(session)
        render_skills_panel(session)
        render_prompts_panel(session)

        with st.container(border=True):
            st.metric(label="Conversation Tokens (est.)", value=session.token_count)

            session.tools_enabled = st.checkbox("Enable Tools", value=session.tools_enabled)
            auto_approve = st.checkbox("Auto-Approve Tools", value=False)

            if st.button("⏮️ Undo First Turn", use_container_width=True):
                if session.undo_first_turn():
                    st.rerun()

            if st.button("↩️ Undo Last Turn", use_container_width=True):
                if session.undo_last_turn():
                    st.rerun()

            if st.button("🗑️ Clear Chat History", use_container_width=True):
                session.clear_history()
                st.rerun()

        with st.container(border=True):
            st.markdown("**🖥️ Shell**")
            command = st.text_input("Command", key="shell_cmd", placeholder="git status")
            col1, col2 = st.columns(2)
            if col1.button("Run + share", use_container_width=True,
                           help="Output goes into the conversation"):
                if command.strip():
                    output = run_shell(session.root, command.strip())
                    session.messages.append({"role": "user", "content": f"`{command.strip()}` output:\n\n```\n{output}\n```"})
                    session.busy = False
                    st.rerun()
            if col2.button("Run quietly", use_container_width=True,
                           help="Output stays out of the conversation"):
                if command.strip():
                    flash(run_shell(session.root, command.strip()))
                    st.rerun()


    return auto_approve


# --- TABS -------------------------------------------------------------------


def render_history_tab(session: ChatSession) -> None:
    st.subheader("Sessions in this workspace")
    st.caption(f"Workspace `{session.workspace.name}` · registry `.state/sessions.json`")

    for entry in session.list_sessions():
        summary = session.session_summary(entry)
        col1, col2, col3, col4 = st.columns([0.80, 0.04, 0.12, 0.04])

        with col1:
            label = f"{entry.name}  ({summary['count']} messages)"
            if entry.id == session.session.id:
                label = "▶ " + label
            with st.expander(label):
                st.caption(f"id `{entry.id}` · {entry.provider or '—'} / {entry.model or '—'}")
                st.write(f"**Last Human:** {summary['last_human'] or 'No human message'}")
                st.write(f"**Last AI:** {summary['last_ai'] or 'No AI message'}")

        
        with col2:
            if st.button("R", key=f"rename_btn_{entry.id}", help="Rename"):
                error = session.rename_session(entry.id, new_name)
                if error:
                    st.error(error)
                else:
                    st.rerun()
        with col3:
            new_name = st.text_input(
                "New name", key=f"rename_input_{entry.id}", label_visibility="collapsed",
                placeholder="new name",
            )
        with col4:
            if st.button("D", key=f"del_sess_{entry.id}", help="Delete"):
                error = session.delete_session(entry.id)
                if error:
                    st.error(error)
                else:
                    st.rerun()


def render_logs_tab(session: ChatSession) -> None:
    st.subheader("Full Message History")

    if not session.messages:
        st.info("Nothing in this session yet.")
        return

    for i, msg in enumerate(session.messages):
        col1, col2 = st.columns([0.9, 0.1])
        with col1:
            label = f"{i}: {msg.get('role')}"
            if msg.get("tool_calls"):
                label += f" ({', '.join(c['function']['name'] for c in msg['tool_calls'])})"
            elif msg.get("role") == "tool":
                label += f" ({tool_name_for(session.messages, i)})"
            with st.expander(label):
                st.code(json.dumps(msg, indent=2, default=str), language="json")
        with col2:
            if st.button("🗑️", key=f"del_msg_{i}"):
                session.delete_message(i)
                st.rerun()


def render_editor_tab(session: ChatSession) -> None:
    st.subheader("File Editor")
    root = session.root
    st.caption(f"Editing inside `{root}`")

    files = list_project_files(root)
    if not files:
        st.info("No editable text files found in this workspace.")
        return

    edit_path = st.selectbox("Select a file to edit:", files, key="editor_file_picker")

    if st.button("Load File"):
        content = read_file(root, edit_path)
        if content.startswith("Error"):
            st.error(content)
        else:
            st.session_state.edit_content = content
            st.session_state.edit_path = edit_path
            # A unique key forces the editor to remount with the new text
            st.session_state.editor_key = str(uuid.uuid4())

    if "edit_content" not in st.session_state:
        return

    loaded_path = st.session_state.get("edit_path", edit_path)
    if loaded_path != edit_path:
        st.warning(f"Editing `{loaded_path}`. Press Load File to open `{edit_path}`.")

    st.session_state.setdefault("editor_key", "editor_initial")

    if st_ace:
        new_content = st_ace(
            value=st.session_state.edit_content,
            language=ace_language(loaded_path),
            theme="monokai",
            key=st.session_state.editor_key,
        )
    else:
        st.caption("`pip install streamlit-ace` for syntax highlighting.")
        new_content = st.text_area(
            "Contents", value=st.session_state.edit_content, height=520,
            key=st.session_state.editor_key,
        )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("💾 Save Changes", use_container_width=True):
            result = write_file(root, loaded_path, new_content or "")
            if result.startswith("Error"):
                st.error(result)
            else:
                st.success(result)
                st.session_state.edit_content = new_content

    with col2:
        if st.button("🔄 Reset Unsaved Changes", use_container_width=True):
            st.session_state.edit_content = read_file(root, loaded_path)
            st.session_state.editor_key = str(uuid.uuid4())
            st.rerun()


def render_models_tab(session: ChatSession) -> None:
    st.subheader("Model Selection")

    # --- current model + catalog freshness ---
    col1, col2 = st.columns([0.65, 0.35])
    with col1:
        if session.model:
            st.success(f"**Active:** `{session.model}`  ·  {session.provider}")
        else:
            st.warning("No model selected yet. Pick one below.")
    with col2:
        if st.button("🔄 Re-discover models", use_container_width=True, type="primary"):
            with st.spinner("Querying every provider with a key set..."):
                session.refresh_catalog()
            st.rerun()
        updated = session.catalog_updated_at()
        st.caption(
            f"Catalog updated {time.strftime('%d %b %H:%M', time.localtime(updated))}"
            if updated else "Catalog has never been built."
        )

    # --- provider key status ---
    status = session.provider_status()
    cols = st.columns(len(status))
    for col, entry in zip(cols, status):
        with col:
            if entry["ready"]:
                col.metric(entry["provider"], f"{entry['count']} models")
            else:
                col.metric(entry["provider"], "no key", delta=entry["env"], delta_color="off")

    if not any(entry["ready"] for entry in status):
        st.error("No API keys found. Set at least one in your .env, then re-discover.")
        return

    # --- type a model in by hand -------------------------------------------
    # Discovery needs a live key *and* a listable endpoint; typing an id is the
    # escape hatch when the catalog is empty or lags behind a new release.
    with st.expander("⌨️ Use a model that isn't listed"):
        ready = [e["provider"] for e in status if e["ready"]]
        col1, col2, col3 = st.columns([0.4, 0.4, 0.2])
        manual_provider = col1.selectbox("Provider", ready, key="manual_provider")
        manual_model = col2.text_input("Model id", key="manual_model",
                                       placeholder="gpt-4o-mini")
        if col3.button("Use it", use_container_width=True, disabled=not manual_model.strip()):
            session.set_model(manual_provider, manual_model.strip())
            st.rerun()

    st.divider()

    # --- search + filter ---
    col1, col2 = st.columns([0.55, 0.45])
    query = col1.text_input("Search", placeholder="gpt, llama, gemini…", key="model_search")
    wanted = col2.multiselect(
        "Providers",
        [e["provider"] for e in status if e["count"]],
        default=[e["provider"] for e in status if e["count"]],
        key="model_provider_filter",
    )

    matches = [pair for pair in session.search_catalog(query) if pair[0] in wanted]

    if not matches:
        st.info("Nothing matches that search. Re-discover, or type a model id above.")
        return

    limit = 60
    st.caption(
        f"{len(matches)} model(s)" + (f" — showing the first {limit}" if len(matches) > limit else "")
    )

    # --- results ---
    current = (session.provider, session.model)
    for provider, model in matches[:limit]:
        is_current = (provider, model) == current
        col1, col2, col3 = st.columns([0.62, 0.22, 0.16])
        col1.markdown(f"{'✅ ' if is_current else ''}`{model}`")
        col2.caption(provider)
        if is_current:
            col3.button("In use", key=f"use_{provider}_{model}", disabled=True,
                        use_container_width=True)
        elif col3.button("Use", key=f"use_{provider}_{model}", use_container_width=True):
            session.set_model(provider, model)
            st.rerun()


def render_tools_tab(session: ChatSession) -> None:
    st.subheader("Registered Tools")
    st.caption(
        "Discovered by `tools/__init__.py` from every `@tool`-decorated function in `tools/`. "
        "Choose which tools are allowed to be offered to the model."
    )
    # --- 👇 HELPFUL WARNING IF MASTER SWITCH IS OFF 👇 ---
    if not session.tools_enabled:
        st.warning("⚠️ **Tools are currently disabled globally.** Turn on **Enable Tools** in the sidebar to use them.")
    # ---------------------------------------------------
    from tools import TOOLS  # imported late so a reload picks up new files

    if not TOOLS:
        st.info("No tools registered. Add one to `tools/` with the `@tool` decorator.")
        return

    # Loop through every tool and render a checkbox + expander info
    for spec in TOOLS:
        function = spec.get("function", {})
        tool_name = function.get("name", "?")

        # Is this tool currently enabled?
        is_currently_enabled = tool_name in session.enabled_tool_names

        # Put a checkbox right alongside an expander for details
        col_box, col_exp = st.columns([0.03, 0.97])

        with col_box:
            # When they click the checkbox, update session state immediately
            new_state = st.checkbox("Enable", value=is_currently_enabled, key=f"tool_toggle_{tool_name}", label_visibility="collapsed")
            if new_state != is_currently_enabled:
                if new_state:
                    session.enabled_tool_names.add(tool_name)
                else:
                    session.enabled_tool_names.discard(tool_name)
                st.rerun()

        with col_exp:
            with st.expander(f"🔧 {tool_name}"):
                st.write(function.get("description") or "_no description_")
                st.code(json.dumps(function.get("parameters", {}), indent=2), language="json")


def render_skills_tab(session: ChatSession) -> None:
    st.subheader("Installed Skills")

    catalog = skill_catalog()
    if not catalog:
        st.info("Nothing in `skills/` yet. Add `skills/<name>/SKILL.md` and rescan.")
        return

    st.caption("Skills live beside the app, so they follow you across workspaces.")
    for skill in catalog:
        with st.expander(f"{skill['name']} — {skill['description'] or 'no description'}"):
            st.caption(skill["path"])
            if skill["files"]:
                st.caption("Bundled: " + ", ".join(skill["files"]))
            st.code(skill["body"], language="markdown")


def render_prompts_tab(session: ChatSession) -> None:
    st.subheader("Installed Prompts")

    catalog = prompt_catalog()
    if not catalog:
        st.info("Nothing in `prompts/` yet. Add `prompts/<name>/PROMPT.md` and rescan.")
        return

    st.caption("Prompts live beside the app, so they follow you across workspaces.")
    for prompt in catalog:
        with st.expander(f"{prompt['name']} — {prompt['description'] or 'no description'}"):
            st.caption(prompt["path"])
            if prompt["files"]:
                st.caption("Bundled: " + ", ".join(prompt["files"]))
            st.code(prompt["body"], language="markdown")

def render_workspaces_tab(session: ChatSession) -> None:
    st.subheader("Registered Workspaces")
    st.caption(f"Registry `.state/workspaces.json` (Unregistering does not delete files from disk)")

    for ws in session.list_workspaces():
        col1, col2 = st.columns([0.8, 0.2])

        with col1:
            label = f"📁 {ws.name}  ·  `{ws.path}`"
            if ws.id == session.workspace.id:
                label = "▶ " + label
            st.markdown(label)

        with col2:
            # Don't let them delete the active workspace easily without switching first, 
            # or handle it gracefully. Here we let them unregister any workspace.
            if st.button("🗑️ Delete", key=f"del_ws_{ws.id}"):
                error = session.delete_workspace(ws.id)
                if error:
                    st.error(error)
                else:
                    reset_workspace_widgets()
                    st.rerun()

# --- AUTHORING --------------------------------------------------------------

NEW_ENTRY = "➕ New…"


def _author_load(kind: str, slug: str | None) -> None:
    """
    Point the editor at `slug` (or a blank entry).

    Only plain state is written here, never a widget key: this runs from button
    callbacks, and Streamlit refuses to let you assign to the key of a widget
    that already rendered this run. The form widgets instead take their value
    from these vars and carry `author_form_key` in their own keys, so bumping
    that key remounts them with the new values.
    """
    st.session_state.author_kind = kind
    st.session_state.author_slug = slug
    st.session_state.author_form_key = str(uuid.uuid4())

    loaded = authoring.load(kind, slug) if slug else None
    st.session_state.author_name = loaded["name"] if loaded else ""
    st.session_state.author_desc = loaded["description"] if loaded else ""
    st.session_state.author_body = loaded["body"] if loaded else ""
    st.session_state.author_layout = loaded["layout"] if loaded else authoring.SINGLE_FILE
    if loaded and loaded["malformed_frontmatter"]:
        st.session_state.author_warning = (
            f"`{loaded['rel_path']}` has no closing `---` fence, so the loader was "
            "reading its frontmatter as body text. Saving here repairs it."
        )


def _on_disk_slugs(kind: str) -> list[str]:
    """
    Entry names as they exist on disk.

    Editing keys on the filename, not the catalog, because the catalog is keyed
    on the frontmatter name and the two can disagree.
    """
    cfg = authoring.KINDS[kind]
    base, entry = cfg["base"], cfg["entry"]
    if not os.path.isdir(base):
        return []
    found = []
    for item in sorted(os.listdir(base)):
        if item.startswith((".", "__")):
            continue
        if os.path.isdir(os.path.join(base, item)):
            if os.path.isfile(os.path.join(base, item, entry)):
                found.append(item)
        elif item.lower().endswith(".md"):
            found.append(os.path.splitext(item)[0])
    return found


def render_authoring_tab(session: ChatSession) -> None:
    st.subheader("Create & Edit")
    st.caption(
        "Writes into `prompts/` and `skills/` beside the app, not into the workspace. "
        "Saving refreshes this session's catalog immediately."
    )

    st.session_state.setdefault("author_form_key", "author_initial")
    st.session_state.setdefault("author_slug", None)
    st.session_state.setdefault("author_name", "")
    st.session_state.setdefault("author_desc", "")
    st.session_state.setdefault("author_body", "")
    st.session_state.setdefault("author_layout", authoring.SINGLE_FILE)

    kind = st.radio(
        "Catalog", ["prompt", "skill"], horizontal=True, key="author_kind_picker",
        format_func=lambda k: f"{'📜' if k == 'prompt' else '🧩'} {k.title()}s",
    )
    cfg = authoring.KINDS[kind]

    choices = [NEW_ENTRY] + _on_disk_slugs(kind)
    current = st.session_state.author_slug
    index = choices.index(current) if current in choices else 0

    # The form key rides along in this widget's key too, so a reset remounts the
    # selectbox at the right index instead of fighting the old selection.
    picked = st.selectbox(
        "Entry", choices, index=index,
        key=f"author_pick_{kind}_{st.session_state.author_form_key}",
    )
    wanted = None if picked == NEW_ENTRY else picked

    # Selection or catalog changed -> reload the form. Safe here: no form widget
    # has been instantiated yet this run.
    if st.session_state.get("author_kind") != kind or current != wanted:
        _author_load(kind, wanted)
        st.rerun()

    editing = st.session_state.author_slug

    notice = st.session_state.pop("author_notice", None)
    if notice:
        st.success(notice)
    warning = st.session_state.pop("author_warning", None)
    if warning:
        st.warning(warning)

    form_key = st.session_state.author_form_key

    col1, col2 = st.columns([0.42, 0.58])
    with col1:
        name = st.text_input(
            "Name", value=st.session_state.author_name,
            placeholder="kebab-case, no spaces",
            help=f"Loaded with `{cfg['command']} <name>`.",
            key=f"author_name_{form_key}",
        )
    with col2:
        layouts = [authoring.SINGLE_FILE, authoring.DIRECTORY]
        layout = st.radio(
            "Layout", layouts, horizontal=True,
            index=layouts.index(st.session_state.author_layout),
            format_func=lambda l: (
                "Single file" if l == authoring.SINGLE_FILE else "Directory + resources"
            ),
            help="Use the directory layout only when the entry ships resource files.",
            key=f"author_layout_{form_key}",
        )

    description = st.text_input(
        "Description", value=st.session_state.author_desc,
        placeholder="One line, shown in the catalog listing.",
        key=f"author_desc_{form_key}",
    )

    if name:
        destination = authoring.target_path(kind, name, layout)
        st.caption(f"→ `{os.path.relpath(destination, cfg['module'].PROJECT_ROOT)}`")

    st.caption("Body only — the fields above are written as frontmatter for you.")
    if st_ace:
        body = st_ace(
            value=st.session_state.author_body, language="markdown",
            theme="monokai", height=420, key=f"author_body_{form_key}",
        )
    else:
        body = st.text_area(
            "Body", value=st.session_state.author_body, height=420,
            label_visibility="collapsed", key=f"author_body_{form_key}",
        )
    body = body or ""

    errors, warnings = authoring.validate(kind, name, description, body, layout, editing)
    for problem in errors:
        st.error(problem)
    for note in warnings:
        st.warning(note)

    col1, col2, col3, col4 = st.columns([0.28, 0.28, 0.18, 0.26])

    if col1.button("💾 Save", type="primary", use_container_width=True,
                   disabled=bool(errors)):
        ok, message = authoring.save(kind, name, description, body, layout, editing)
        if ok:
            reload_catalog(kind)
            _author_load(kind, name.strip())
            st.session_state.author_notice = message
            st.rerun()
        st.error(message)

    if col2.button("🧪 Insert starter body", use_container_width=True,
                   disabled=bool(body.strip())):
        st.session_state.author_body = authoring.starter_body(name or "new entry")
        st.session_state.author_form_key = str(uuid.uuid4())
        st.rerun()

    if col3.button("↩️ Revert", use_container_width=True):
        _author_load(kind, editing)
        st.rerun()

    if editing:
        with col4.popover("🗑️ Delete", use_container_width=True):
            st.caption(f"Permanently delete `{editing}`?")
            if st.session_state.author_layout == authoring.DIRECTORY:
                st.caption("Its bundled files go with it.")
            if st.button("Yes, delete it", type="primary", key="author_delete_confirm"):
                ok, message = authoring.delete(kind, editing)
                if ok:
                    reload_catalog(kind)
                    _author_load(kind, None)
                    st.session_state.author_notice = message
                    st.rerun()
                st.error(message)

    if editing:
        _render_bundled_editor(kind, editing)
        with st.expander("👁️ Preview what the model receives"):
            rendered = authoring.preview(kind, editing, "sample task")
            st.code(rendered or "Not loadable — fix the errors above.",
                    language="markdown")


def _render_bundled_editor(kind: str, slug: str) -> None:
    saved_layout = st.session_state.author_layout

    with st.expander("📎 Bundled files"):
        if saved_layout != authoring.DIRECTORY:
            st.caption(
                "Single-file entries cannot ship resources. Switch the layout to "
                "directory and save, then add files here."
            )
            return

        st.caption(
            "These are listed to the model, not inlined. Reference a file by its "
            "path in the body or it will never be read."
        )

        # Bundled paths are recorded relative to the repo root, but
        # save_bundled wants them relative to the entry's own directory — and
        # they can be nested a level deeper.
        entry_dir = os.path.relpath(
            os.path.dirname(authoring.target_path(kind, slug, authoring.DIRECTORY)),
            authoring.KINDS[kind]["module"].PROJECT_ROOT,
        )

        for rel in authoring.bundled_files(kind, slug):
            st.markdown(f"**`{rel}`**")
            content = st.text_area(
                rel, value=authoring.read_bundled(kind, rel), height=200,
                key=f"bundle_body_{kind}_{rel}", label_visibility="collapsed",
            )
            col1, col2, _ = st.columns([0.2, 0.2, 0.6])
            if col1.button("💾 Save", key=f"bundle_save_{kind}_{rel}",
                           use_container_width=True):
                ok, message = authoring.save_bundled(
                    kind, slug, os.path.relpath(rel, entry_dir), content
                )
                (st.success if ok else st.error)(message)
            if col2.button("🗑️ Remove", key=f"bundle_del_{kind}_{rel}",
                           use_container_width=True):
                ok, message = authoring.delete_bundled(kind, rel)
                if ok:
                    st.rerun()
                st.error(message)

        st.divider()
        new_name = st.text_input("New file", placeholder="checklist.md",
                                 key=f"bundle_new_name_{kind}_{slug}")
        new_body = st.text_area("Contents", height=140,
                                key=f"bundle_new_body_{kind}_{slug}")
        if st.button("➕ Add file", key=f"bundle_add_{kind}_{slug}"):
            ok, message = authoring.save_bundled(kind, slug, new_name, new_body)
            if ok:
                st.rerun()
            st.error(message)


# --- CHAT -------------------------------------------------------------------


def render_message_content(content) -> None:
    """Render a message's content, whether it's plain text or a list of
    OpenAI-style content parts (text / image_url)."""
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                st.markdown(sanitize_content(part))
            elif part.get("type") == "text":
                st.markdown(sanitize_content(part.get("text", "")))
            elif part.get("type") == "image_url":
                try:
                    st.image(data_url_to_bytes(part["image_url"]["url"]))
                except Exception as e:                # noqa: BLE001
                    st.caption(f"[Image display error: {e}]")
    else:
        st.markdown(sanitize_content(content))


def render_transcript(session: ChatSession) -> None:
    """Chat history, rendered straight from the raw message list."""
    for i, msg in enumerate(session.messages):
        role = msg.get("role")

        if role == "system":
            with st.chat_message("system", avatar="⚙️"):
                with st.expander("System prompt", expanded=False):
                    st.markdown(sanitize_content(msg.get("content", "")))

        elif role == "user":
            with st.chat_message("user"):
                render_message_content(msg.get("content", ""))

        elif role == "assistant":
            content = msg.get("content") or ""
            # Only render if there is actual text (ignores silent tool calls)
            if isinstance(content, list) or (isinstance(content, str) and content.strip()):
                with st.chat_message("assistant"):
                    render_message_content(content)
            elif msg.get("tool_calls"):
                with st.chat_message("assistant"):
                    names = ", ".join(c["function"]["name"] for c in msg["tool_calls"])
                    st.caption(f"🔧 requested: {names}")

        elif role == "tool":
            # The tool name isn't on the message; resolve it from the call id.
            with st.chat_message("tool", avatar="🔧"):
                with st.expander(f"Result from {tool_name_for(session.messages, i)}",
                                 expanded=False):
                    st.code(str(msg.get("content", "")), language="text")


def render_tool_approval(session: ChatSession, auto_approve: bool) -> None:
    """The approval gate shown whenever the model asked for a tool."""
    print(">>> RENDERING TOOL APPROVAL UI NOW! <<<")
    with st.chat_message("assistant"):
        st.warning("⚠️ **The agent has requested to execute the following tool(s):**")

        for call in session.pending:
            with st.expander(f"Tool Call: {call.name}", expanded=True):
                for key, value in call.display_args.items():
                    st.markdown(f"**{key}:**")
                    st.code(str(value), language="python")

        if auto_approve:
            st.info("Auto-approving because the checkbox is ticked...")
            for _result in session.approve_tools():   # generator: must be drained
                pass
            st.rerun()

        col1, col2, col3 = st.columns([0.4, 0.3, 0.3])

        if col1.button("✅ Approve Action"):
            with st.status("Executing tools...", expanded=True) as status:
                for result in session.approve_tools():
                    st.code(f"**{result['name']}** → {result['output'][:200]}", language="text")
                status.update(label="Action complete!", state="complete", expanded=False)
            st.rerun()

        if col2.button("❌ Deny Action"):
            session.deny_tools()
            st.rerun()

        with col3:
            with st.popover("💬 Provide Feedback"):
                feedback = st.text_area("Tell the agent what to change:")
                if st.button("Submit Feedback"):
                    if feedback.strip():
                        session.send_tool_feedback(feedback)
                        st.rerun()
                    else:
                        st.warning("Please enter some feedback.")


# --- TYPED COMMANDS ---------------------------------------------------------


def handle_command(session: ChatSession, text: str) -> tuple[str | None, str | None]:
    """
    Expand the CLI-style commands the chat box accepts.

    Returns (text_to_submit, flash_note); at most one is set. A plain message
    comes back unchanged as text_to_submit.
    """
    stripped = text.strip()

    if stripped.startswith("!"):
        command = stripped.lstrip("!").strip()
        if not command:
            return None, "Give the shell something to run."

        # 1. Run the shell
        output = run_shell(session.root, command)

        # 2. If it's quiet, just show the output and stop
        if stripped.startswith("!!"):
            return None, output

        # 3. If it's a normal '!', add the command to history 
        # and trigger the agent to think about it.
        session.messages.append({"role": "user", "content": f"`{command.strip()}` output:\n\n```\n{output}\n```"})
        session._save() # Make sure it's saved!
        session.busy = False # Tell the app to start the 'thinking' loop

        return None, None

    if not stripped.startswith("/"):
        return text, None

    word, _, rest = stripped.partition(" ")
    word = word.lower()
    rest = rest.strip()

    if word in ("/skills", "/prompts"):
        module = skills_mod if word == "/skills" else prompts_mod
        if rest.lower() in ("reload", "refresh"):
            reload_catalog("skill" if word == "/skills" else "prompt")
            return None, "[reloaded]\n" + module.format_catalog()
        return None, module.format_catalog()

    if word in ("/skill", "/prompt"):
        module = skills_mod if word == "/skill" else prompts_mod
        if not rest:
            return None, module.format_catalog()
        name, _, task = rest.partition(" ")
        entry, candidates = module.resolve(name)
        if entry is None:
            if candidates:
                return None, (f"'{name}' is ambiguous. Did you mean: "
                              + ", ".join(c["name"] for c in candidates))
            return None, f"No entry named '{name}'.\n\n" + module.format_catalog()
        return module.render(entry, task.strip()), None

    if word == "/system":
        session.set_system_prompt(rest)
        return None, "System prompt updated." if rest else "System prompt cleared."

    if word == "/temp":
        try:
            session.set_temperature(float(rest))
        except ValueError:
            return None, f"'{rest}' is not a number."
        return None, f"Temperature set to {session.temperature}."

    if word == "/reset":
        session.clear_history()
        return None, "History cleared."

    if word == "/help":
        return None, (
            "!<cmd>          run a shell command and share the output\n"
            "!!<cmd>         run it quietly (output stays out of the chat)\n"
            "/skills         list skills      /skill <name> [task]\n"
            "/prompts        list prompts     /prompt <name> [task]\n"
            "/system <text>  set the system prompt\n"
            "/temp <value>   set the sampling temperature\n"
            "/reset          clear the conversation\n"
            "Workspaces, sessions and models live in the sidebar and tabs."
        )

    return text, None                                 # unknown slash -> send as-is


def get_chat_input():
    """`accept_file` needs Streamlit >= 1.43; degrade to a text-only box."""
    placeholder = "Message, !shell command, /skill <name> or /prompt <name> …"
    try:
        return st.chat_input(
            placeholder + " (use + to attach files)",
            accept_file="multiple",
            file_type=sorted(IMAGE_EXTENSIONS | TEXT_EXTENSIONS),
        )
    except TypeError:
        return st.chat_input(placeholder)


# --- ENTRY POINT ------------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title="Modular Agent", page_icon="💬", layout="wide")

    session = get_session()
    print(f"AFTER get_session() -> session.pending is: {bool(session.pending)}")

    auto_approve = render_sidebar(session)
    print(f"AFTER render_sidebar() -> session.pending is: {bool(session.pending)}")

    (
        tab_chat,
        tab_models,
        tab_edit,
        tab_skills,
        tab_prompts,
        tab_author,
        tab_tools,
        tab_logs,
        tab_history,
        tab_workspaces, # <-- Add this!
    ) = st.tabs(
        [
            "💬 Chat Interface",
            "🧠 Models",
            "📝 Editor",
            "🧩 Skills",
            "📜 Prompts",
            "✍️ Create & Edit",
            "🔧 Tools",
            "🗒️ Message Logs",
            "🕒 Manage Sessions",
            "📂 Manage Workspaces", # <-- Add this!
        ]
    )

    with tab_models:
        render_models_tab(session)

    with tab_history:
        render_history_tab(session)

    with tab_logs:
        render_logs_tab(session)

    with tab_skills:
        render_skills_tab(session)

    with tab_prompts:
        render_prompts_tab(session)

    with tab_author:
        render_authoring_tab(session)

    with tab_tools:
        render_tools_tab(session)

    with tab_edit:
        render_editor_tab(session)
    
    with tab_workspaces:
        render_workspaces_tab(session)

    print(f"RIGHT BEFORE tab_chat -> session.pending is: {bool(session.pending)}")
    with tab_chat:
        print(f"INSIDE tab_chat -> session.pending is: {bool(session.pending)}")
        if session.provider:
            st.caption(
                f"**Model:** `[{session.provider}] {session.model}` · "
                f"**Session:** `{session.session.name[:24]}` · "
                f"**Dir:** `{os.path.basename(session.root)}`"
            )

        note = st.session_state.pop("flash", None)
        if note:
            st.code(note, language="bash")

        render_transcript(session)

        if session.last_error:
            st.error(session.last_error)

        # --- 👇 ADD THESE PRINTS RIGHT HERE 👇 ---
        print(f"DRAWING CHAT TAB. session.pending is: {bool(session.pending)}")
        if session.pending:
            print(f"--> There are {len(session.pending)} pending tools!")
        else:
            print(f"--> NO PENDING TOOLS. Why? Let's check last message role: {session.messages[-1].get('role') if session.messages else 'No messages'}")
        # ----------------------------------------

        if session.pending:
            render_tool_approval(session, auto_approve)

        # One model call per rerun; the loop settles when `busy` goes false.
        elif session.busy:
            with st.chat_message("assistant"):
                with st.spinner(f"{session.model} is thinking..."):
                    session.step()
            st.rerun()

    # --- NEW USER INPUT ---

    if not session.is_ready():
        with tab_chat:
            st.warning(
                "⚠️ **Open the 🧠 Models tab** to pick a model, and make sure its API key is "
                "set in your .env."
            )
        st.chat_input("Select a model to start chatting...", disabled=True)
        return

    user_prompt = get_chat_input()

    if user_prompt:
        user_text = user_prompt.text if hasattr(user_prompt, "text") else str(user_prompt)
        attached_files = user_prompt.files if hasattr(user_prompt, "files") else []

        user_text, note = handle_command(session, user_text or "")
        if note and not attached_files:
            flash(note)
            st.rerun()
        if note:
            flash(note)

        image_parts = []
        text_blocks = []
        for f in attached_files:
            if is_image_file(f.name):
                image_parts.append({
                    "type": "image_url",
                    "image_url": {"url": encode_image_to_data_url(f)},
                })
            else:
                text, truncated = read_text_file(f)
                text_blocks.append(format_text_file_block(f.name, text, truncated))

        full_text = user_text or ""
        if text_blocks:
            full_text = (full_text + "\n\n" if full_text else "") + "\n\n".join(text_blocks)

        if image_parts:
            content = []
            if full_text:
                content.append({"type": "text", "text": full_text})
            content.extend(image_parts)
        else:
            content = full_text

        # submit() takes text or an OpenAI-style content list either way, so
        # vision turns need no special path here.
        if content:
            session.submit(content)
        st.rerun()


if __name__ == "__main__":
    main()
