"""
chat_session.py
---------------
Frontend-agnostic wrapper around `model_gateway`, `workspace_manager`,
`session_manager` and `tools`.

The CLI drives the agent with a `while True:` loop and a blocking `input()`
for tool approval. A Streamlit script can't do that — it reruns top to bottom
on every interaction — so the same loop is exposed here as a state machine:

    session.submit(text)        # -> busy = True
    while session.busy:
        session.step()          # one gateway.generate() call
        if session.pending:     # model asked for tools; nothing runs yet
            session.approve_tools()   # or deny_tools() / send_tool_feedback()

`chatbot.py` and `chatbot_tui.py` keep working untouched — this is a third
frontend over the same core, not a replacement.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from model_gateway import ModelGateway
from workspace_manager import WorkspaceManager, WorkspaceError
from session_manager import SessionManager, SessionError
from tools import TOOLS, execute_tool

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CATALOG_PATH = os.path.join(PROJECT_ROOT, "model_catalog.json")

DEFAULT_MODELS = {
    "OpenAI": "gpt-4o-mini",
    "OpenRouter": "openai/gpt-4o-mini",
    "Groq": "llama-3.1-8b-instant",
    "Google Gemini (OpenAI Compatible)": "gemini-3.1-flash-lite",
}

DECLINED = json.dumps({"error": "Tool call declined by user."})


def sanitize_content(text) -> str:
    """Stop stray dollar signs from being swallowed as LaTeX by st.markdown."""
    if not isinstance(text, str):
        text = str(text)
    return text


def estimate_tokens(messages: list[dict]) -> int:
    try:
        return len(json.dumps(messages, default=str)) // 4
    except (TypeError, ValueError):
        return 0


def tool_name_for(messages: list[dict], index: int) -> str:
    """
    Look back for the assistant turn that requested messages[index].

    The tool name isn't stored on the tool message itself: not every provider
    accepts extra keys on a `role: "tool"` turn, so the transcript resolves it
    from the matching tool_call_id instead of writing it into the payload.
    """
    call_id = messages[index].get("tool_call_id")
    for msg in reversed(messages[:index]):
        for call in msg.get("tool_calls") or []:
            if call.get("id") == call_id:
                return call.get("function", {}).get("name", "tool")
    return "tool"


@dataclass
class PendingCall:
    id: str
    name: str
    args: dict = field(default_factory=dict)

    @property
    def display_args(self) -> dict:
        return self.args or {"(no arguments)": ""}


class ChatSession:
    """One live conversation, bound to the active workspace + session."""

    def __init__(self, workspace_path: str | None = None,
                 session_name: str | None = None) -> None:
        self.gateway = ModelGateway()
        self.wm = WorkspaceManager()
        self.workspace = self._resolve_workspace(workspace_path)
        self.sm = SessionManager(self.wm)
        self.session = self._resolve_session(session_name)

        self.provider: str = ""
        self.model: str = ""
        self.temperature: float = 0.7
        self.messages: list[dict] = []
        self._adopt(self.session)

        self.pending: list[PendingCall] = []
        self.busy = False
        self.last_error: str | None = None
        self.tools_enabled = True

    # -- workspace ---------------------------------------------------------

    def _resolve_workspace(self, path: str | None):
        if path:
            return self.wm.create_workspace(path)
        if not self.wm.list_workspaces():
            return self.wm.create_workspace(os.getcwd())
        return self.wm.resolve_workspace() or self.wm.switch_workspace(1)

    @property
    def root(self) -> str:
        return os.path.abspath(self.workspace.path)

    def list_workspaces(self) -> list:
        return self.wm.list_workspaces()

    def create_workspace(self, path: str) -> str | None:
        """Create/activate a workspace. Returns an error string, or None."""
        try:
            self.workspace = self.wm.create_workspace(path)
        except WorkspaceError as exc:
            return str(exc)
        self._rebind_sessions()
        return None

    def switch_workspace(self, selector) -> str | None:
        try:
            self.workspace = self.wm.switch_workspace(selector)
        except WorkspaceError as exc:
            return str(exc)
        self._rebind_sessions()
        return None

    def _rebind_sessions(self) -> None:
        """A new workspace means a new session pool; resume or start one."""
        self.sm = SessionManager(self.wm)
        if self.sm.list_sessions():
            session = self.sm.resolve_session() or self.sm.switch_session(1)
        else:
            session = self.sm.create_session(
                provider=self.provider, model=self.model, temperature=self.temperature
            )
        self._adopt(session)
        self._clear_run_state()

    # -- sessions ----------------------------------------------------------

    def _resolve_session(self, name: str | None):
        if name:
            try:
                return self.sm.switch_session(name)
            except SessionError:
                return self.sm.create_session(name=name)
        if not self.sm.list_sessions():
            return self.sm.create_session()
        return self.sm.resolve_session() or self.sm.switch_session(1)

    def _adopt(self, session) -> None:
        """Restore a session's conversation *and* its model configuration."""
        self.session = session
        self.provider = (
            session.provider if session.provider in self.gateway.CONFIGS
            else (self.provider or self._preferred_provider())
        )
        self.model = session.model or self.model or DEFAULT_MODELS.get(self.provider, "")
        if session.temperature is not None:
            self.temperature = session.temperature
        self.messages = list(session.messages)
        self.sm.update_model_config(
            session, provider=self.provider, model=self.model, temperature=self.temperature
        )

    def _preferred_provider(self) -> str:
        names = list(self.gateway.CONFIGS)
        keyed = [n for n in names if self.provider_ready(n)]
        return (keyed or names or [""])[0]

    def _clear_run_state(self) -> None:
        self.pending = []
        self.busy = False
        self.last_error = None

    def list_sessions(self) -> list:
        return self.sm.list_sessions()

    def session_summary(self, session) -> dict:
        last_human = last_ai = ""
        for msg in session.messages:
            if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                last_human = msg["content"][:160]
            elif msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
                last_ai = (msg.get("content") or "")[:160]
        return {"count": len(session.messages), "last_human": last_human, "last_ai": last_ai}

    def new_session(self, name: str | None = None) -> str | None:
        try:
            session = self.sm.create_session(
                name=name or None, provider=self.provider,
                model=self.model, temperature=self.temperature,
            )
        except SessionError as exc:
            return str(exc)
        self._adopt(session)
        self._clear_run_state()
        return None

    def switch_session(self, selector) -> str | None:
        try:
            session = self.sm.switch_session(selector)
        except SessionError as exc:
            return str(exc)
        self._adopt(session)
        self._clear_run_state()
        return None

    def rename_session(self, session_id: str, new_name: str) -> str | None:
        if not new_name.strip():
            return "Give the session a name first."
        try:
            renamed = self.sm.rename_session(session_id, new_name.strip())
        except SessionError as exc:
            return str(exc)
        if renamed.id == self.session.id:
            self.session = renamed
        return None

    def delete_session(self, selector) -> str | None:
        try:
            deleted = self.sm.delete_session(selector)
        except SessionError as exc:
            return str(exc)
        if deleted.id != self.session.id:
            return None
        remaining = self.sm.list_sessions()
        if remaining:
            self._adopt(self.sm.switch_session(remaining[0].id))
        else:
            self._adopt(self.sm.create_session(
                provider=self.provider, model=self.model, temperature=self.temperature
            ))
        self._clear_run_state()
        return None

    # -- configuration -----------------------------------------------------

    def provider_ready(self, provider: str) -> bool:
        env = self.gateway.CONFIGS.get(provider, {}).get("api_key_env")
        return bool(env and os.getenv(env))

    def env_var_for(self, provider: str) -> str:
        return self.gateway.CONFIGS.get(provider, {}).get("api_key_env", "?")

    def set_model(self, provider: str, model: str) -> None:
        self.provider, self.model = provider, model
        self.sm.update_model_config(self.session, provider=provider, model=model)

    def set_temperature(self, temperature: float) -> None:
        self.temperature = float(temperature)
        self.sm.update_model_config(self.session, temperature=self.temperature)

    @property
    def system_prompt(self) -> str:
        for msg in self.messages:
            if msg.get("role") == "system":
                return msg.get("content") or ""
        return ""

    def set_system_prompt(self, text: str) -> None:
        self.messages = [m for m in self.messages if m.get("role") != "system"]
        if text.strip():
            self.messages.insert(0, {"role": "system", "content": text.strip()})
        self._save()

    def is_ready(self) -> bool:
        return bool(self.provider and self.model)

    @property
    def token_count(self) -> int:
        return estimate_tokens(self.messages)

    # -- model catalog -----------------------------------------------------

    def _load_catalog(self) -> dict:
        try:
            with open(CATALOG_PATH, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {"updated": 0, "models": {}}

    def catalog_updated_at(self) -> float:
        return self._load_catalog().get("updated", 0)

    def refresh_catalog(self) -> dict[str, int]:
        """Ask every key-bearing provider for its live model list."""
        catalog = self._load_catalog().get("models", {})
        counts: dict[str, int] = {}
        for provider, config in self.gateway.PROVIDERS.items():
            if not self.provider_ready(provider):
                counts[provider] = 0
                continue
            try:
                models = self.gateway.fetch_models(provider, config)
            except Exception:
                models = None
            if models:
                catalog[provider] = sorted(str(m) for m in models)
            counts[provider] = len(catalog.get(provider, []))
        payload = {"updated": time.time(), "models": catalog}
        try:
            with open(CATALOG_PATH, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
        except OSError:
            pass
        return counts

    def provider_status(self) -> list[dict]:
        catalog = self._load_catalog().get("models", {})
        return [
            {
                "provider": name,
                "env": self.gateway.CONFIGS[name].get("api_key_env", "?"),
                "ready": self.provider_ready(name),
                "count": len(catalog.get(name, [])),
                "listable": name in self.gateway.PROVIDERS,
            }
            for name in self.gateway.CONFIGS
        ]

    def search_catalog(self, query: str = "") -> list[tuple[str, str]]:
        catalog = self._load_catalog().get("models", {})
        needle = query.strip().lower()
        pairs = [
            (provider, model)
            for provider, models in sorted(catalog.items())
            for model in models
            if not needle or needle in model.lower()
        ]
        return pairs

    # -- history -----------------------------------------------------------

    def _save(self) -> None:
        self.sm.set_messages(self.session, self.messages)

    def clear_history(self) -> None:
        self.messages = [m for m in self.messages if m.get("role") == "system"]
        self._save()
        self._clear_run_state()

    def delete_message(self, index: int) -> None:
        if 0 <= index < len(self.messages):
            self.messages.pop(index)
            self._save()

    def undo_last_turn(self) -> bool:
        """Drop everything back to (and including) the last user message."""
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].get("role") == "user":
                self.messages = self.messages[:i]
                self._save()
                self._clear_run_state()
                return True
        return False

    def undo_first_turn(self) -> bool:
        """Drop the oldest user turn and everything up to the next one."""
        starts = [i for i, m in enumerate(self.messages) if m.get("role") == "user"]
        if not starts:
            return False
        first = starts[0]
        end = starts[1] if len(starts) > 1 else len(self.messages)
        self.messages = self.messages[:first] + self.messages[end:]
        self._save()
        return True

    # -- the agent loop ----------------------------------------------------

    def submit(self, content: Any) -> None:
        """Queue a user turn. The frontend then calls step() until !busy."""
        if not content:
            return
        self.messages.append({"role": "user", "content": content})
        self.last_error = None
        self.busy = True
        self._save()

    def step(self) -> None:
        """One gateway.generate() call — the body of the CLI's inner loop."""
        self.sm.set_status(self.session, "RUNNING")
        try:
            response = self.gateway.generate(
                self.provider, self.model, self.messages,
                temperature=self.temperature,
                tools=TOOLS if self.tools_enabled else None,
            )
        except Exception as exc:  # network, auth, bad config…
            response = {"error": f"{type(exc).__name__}: {exc}"}

        self.last_response = response

        # generate() returns the raw API payload: the message lives under
        # choices[0], not at the top level.
        choices = response.get("choices") or [{}]
        msg = choices[0].get("message") or {}
        tool_calls = msg.get("tool_calls")

        if tool_calls:
            self.messages.append(msg)
            self.pending = [
                PendingCall(
                    id=call.get("id"),
                    name=call.get("function", {}).get("name", ""),
                    args=self._parse_args(call),
                )
                for call in tool_calls
            ]
            self.busy = False  # nothing runs until the user approves
            self._save()
            self.sm.set_status(self.session, "IDLE")
            return

        reply, error = self._extract_reply(response)
        if error:
            self.last_error = error
            self.busy = False
            self.sm.set_status(self.session, "IDLE")
            return

        self.messages.append({"role": "assistant", "content": reply})
        self.busy = False
        self._save()
        self.sm.set_status(self.session, "IDLE")

    @staticmethod
    def _parse_args(call: dict) -> dict:
        try:
            return json.loads(call.get("function", {}).get("arguments") or "{}")
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _extract_reply(response: dict) -> tuple[str | None, str | None]:
        if "error" in response:
            return None, str(response["error"])
        try:
            return response["choices"][0]["message"].get("content", ""), None
        except (KeyError, IndexError, TypeError):
            return None, f"Unexpected response shape: {json.dumps(response, default=str)[:500]}"

    def approve_tools(self) -> Iterator[dict]:
        """Run every pending call, yielding {'name', 'output'} as it goes."""
        for call in self.pending:
            try:
                output = execute_tool(call.name, call.args)
            except Exception as exc:
                output = json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            self._record_result(call, output)
            yield {"name": call.name, "output": str(output)}
        self._finish_tools()

    def deny_tools(self) -> None:
        for call in self.pending:
            self._record_result(call, DECLINED)
        self._finish_tools()

    def send_tool_feedback(self, feedback: str) -> None:
        note = json.dumps({"error": "Tool call declined by user.", "feedback": feedback})
        for call in self.pending:
            self._record_result(call, note)
        self._finish_tools()

    def _record_result(self, call: PendingCall, output: Any) -> None:
        # Every tool_call_id from the assistant's turn needs a matching tool
        # response — approved or not — or the next request is rejected.
        self.messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "content": output if isinstance(output, str) else json.dumps(output, default=str),
        })

    def _finish_tools(self) -> None:
        self.pending = []
        self.busy = True  # go back to the model with the results
        self._save()
