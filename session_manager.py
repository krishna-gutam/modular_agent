#!/usr/bin/env python3
"""
Session Manager for modular_agent.

Implements the "Session Manager" (SM) participant from
coding_system_architecture.mmd. This first cut covers:

    2. SESSION LIFECYCLE
        Create Session   -> createSession(in current active workspace)
                             SM resolves the active workspace via WM,
                             then initializes session defaults
                             (provider, model, temperature).
        Rename Session   -> renameSession(session name, new name)
        Delete Session   -> deleteSession(session name)
        Switch Session   -> listSessions(workspace) / switchSession(...)
                             Restores conversation + model configuration.

    3. MODEL CONFIGURATION (persistence side)
        SM stores provider, model, and temperature per session so a
        resumed session comes back with the same configuration.

    11. LEAVE AND RESUME LATER
        Sessions (and their conversation history + model config) are
        persisted to disk, so closing the chatbot and reopening it later
        can resume a session with its state intact.

Sessions are scoped to a workspace (a session "belongs" to whichever
Workspace it was created in, mirroring "createSession(in current active
workspace)" in the diagram) and are persisted to a small JSON registry
(~/.state/sessions.json next to workspaces.json by default) so they
survive across chatbot restarts.

Approval mode, skills, and the agent tool-execution loop (sections 4-10,
12-13 of the diagram) are out of scope here since chatbot.py doesn't yet
run an agent/tool loop -- this module only covers what a plain
prompt-in/reply-out CLI chatbot needs from the Session Manager.
"""

import json
import os
import time
import uuid

DEFAULT_REGISTRY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".state")
DEFAULT_REGISTRY_PATH = os.path.join(DEFAULT_REGISTRY_DIR, "sessions.json")


class SessionError(Exception):
    """Raised for invalid session operations (bad name, not found, etc.)."""


class Session:
    """
    A single conversation session: scoped to a workspace, carrying its
    own model configuration (provider/model/temperature) and its own
    conversation history so multiple sessions in the same workspace
    don't step on each other.
    """

    def __init__(
        self,
        session_id,
        workspace_id,
        name=None,
        provider=None,
        model=None,
        temperature=0.7,
        messages=None,
        status="IDLE",
        created_at=None,
        last_active_at=None,
    ):
        self.id = session_id
        self.workspace_id = workspace_id
        # Diagram: "New Session (default name is uuid)"
        self.name = name or session_id
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self.messages = messages if messages is not None else []
        self.status = status
        self.created_at = created_at if created_at is not None else time.time()
        self.last_active_at = last_active_at if last_active_at is not None else self.created_at

    def to_dict(self):
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "messages": self.messages,
            "status": self.status,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            session_id=data["id"],
            workspace_id=data["workspace_id"],
            name=data.get("name"),
            provider=data.get("provider"),
            model=data.get("model"),
            temperature=data.get("temperature", 0.7),
            messages=data.get("messages", []),
            status=data.get("status", "IDLE"),
            created_at=data.get("created_at"),
            last_active_at=data.get("last_active_at"),
        )


class SessionManager:
    """
    Manages session creation, renaming, deletion, switching, conversation
    persistence, and model-config persistence -- scoped per workspace.

    Public API mirrors the SM participant in the sequence diagram:
        create_session(...)             -> createSession(workspace)
        list_sessions(workspace)        -> listSessions(workspace)
        switch_session(id, workspace)   -> switchSession(workspace, name)
        rename_session(id, new_name)    -> renameSession(name, new_name)
        delete_session(id)              -> deleteSession(name)
        resolve_session(workspace)      -> resolve the active session

    A WorkspaceManager is used to resolve "the current active workspace"
    (SM->>WM: resolveWorkspace()) whenever a workspace isn't passed in
    explicitly.
    """

    def __init__(self, workspace_manager=None, registry_path=None):
        self.wm = workspace_manager
        self.registry_path = registry_path or DEFAULT_REGISTRY_PATH
        self._sessions = {}            # id -> Session
        self._active_by_workspace = {}  # workspace_id -> session_id
        self._load_registry()

    # ---------------------------------------------------------------- #
    # Persistence
    # ---------------------------------------------------------------- #

    def _load_registry(self):
        if not os.path.exists(self.registry_path):
            return
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        for entry in data.get("sessions", []):
            try:
                session = Session.from_dict(entry)
            except KeyError:
                continue
            self._sessions[session.id] = session
        self._active_by_workspace = data.get("active_by_workspace", {})

    def _save_registry(self):
        os.makedirs(os.path.dirname(self.registry_path), exist_ok=True)
        data = {
            "active_by_workspace": self._active_by_workspace,
            "sessions": [s.to_dict() for s in self._sessions.values()],
        }
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # ---------------------------------------------------------------- #
    # Lifecycle: Create / Rename / Delete / Switch / Resolve
    # ---------------------------------------------------------------- #

    def create_session(self, name=None, workspace=None, provider=None, model=None,
                        temperature=0.7, activate=True):
        """
        createSession(in current active workspace)

        SM->>WM: resolveWorkspace(current active workspace)
        SM->>SM: Initialize session defaults [provider, model, temperature]

        `provider`/`model`/`temperature` are the session defaults to seed
        the new session with (e.g. carried over from whatever session/
        config is currently active) -- matching "Initialize session
        defaults" in the diagram.
        """
        ws = self._require_workspace(workspace)

        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            workspace_id=ws.id,
            name=name,
            provider=provider,
            model=model,
            temperature=temperature,
        )
        self._sessions[session_id] = session

        if activate:
            self._activate(ws.id, session_id)
        else:
            self._save_registry()

        return session

    def list_sessions(self, workspace=None):
        """
        listSessions(current active workspace)

        Return all sessions belonging to the given (or current active)
        workspace, most recently active first.
        """
        ws = self._require_workspace(workspace)
        sessions = [s for s in self._sessions.values() if s.workspace_id == ws.id]
        return sorted(sessions, key=lambda s: s.last_active_at, reverse=True)

    def rename_session(self, identifier, new_name, workspace=None):
        """renameSession(session name, new name)"""
        new_name = (new_name or "").strip()
        if not new_name:
            raise SessionError("New session name cannot be empty.")

        session = self._resolve_identifier(identifier, workspace=workspace)
        if session is None:
            raise SessionError(f"No session matching '{identifier}'. Try /session list.")

        session.name = new_name
        self._save_registry()
        return session

    def delete_session(self, identifier, workspace=None):
        """deleteSession(session name)"""
        session = self._resolve_identifier(identifier, workspace=workspace)
        if session is None:
            raise SessionError(f"No session matching '{identifier}'. Try /session list.")

        del self._sessions[session.id]
        if self._active_by_workspace.get(session.workspace_id) == session.id:
            del self._active_by_workspace[session.workspace_id]
        self._save_registry()
        return session

    def switch_session(self, identifier, workspace=None):
        """
        switchSession(current active workspace, selected session name)

        SM->>SM: Load persisted selected session
        (Restore conversation + model configuration is implicit: the
        Session object itself already carries `messages`, `provider`,
        `model`, and `temperature`.)
        """
        ws = self._require_workspace(workspace)
        session = self._resolve_identifier(identifier, workspace=ws)
        if session is None:
            raise SessionError(
                f"No session matching '{identifier}' in workspace '{ws.name}'. "
                f"Try /session list."
            )
        self._activate(ws.id, session.id)
        return session

    def resolve_session(self, workspace=None):
        """Return the currently active Session for the workspace, or None."""
        ws = workspace or (self.wm.resolve_workspace() if self.wm else None)
        if ws is None:
            return None
        session_id = self._active_by_workspace.get(ws.id)
        if session_id is None:
            return None
        return self._sessions.get(session_id)

    # ---------------------------------------------------------------- #
    # Conversation + model-config persistence
    #
    # These back sections 3 (Model Configuration) and 7-10 (conversation
    # turns / run completion) of the diagram, scoped down to what a
    # plain request/response chatbot needs to persist.
    # ---------------------------------------------------------------- #

    def set_messages(self, session, messages):
        """Replace the session's persisted conversation history."""
        session.messages = messages
        self._touch_and_save(session)

    def add_message(self, session, message):
        """Append a single message to the session's conversation history."""
        session.messages.append(message)
        self._touch_and_save(session)

    def update_model_config(self, session, provider=None, model=None, temperature=None):
        """Save ModelConfig: provider / model / temperature."""
        if provider is not None:
            session.provider = provider
        if model is not None:
            session.model = model
        if temperature is not None:
            session.temperature = temperature
        self._touch_and_save(session)

    def set_status(self, session, status):
        """e.g. IDLE / WAITING_FOR_APPROVAL, per "Leave and Resume Later"."""
        session.status = status
        self._touch_and_save(session)

    # ---------------------------------------------------------------- #
    # Helpers
    # ---------------------------------------------------------------- #

    def _require_workspace(self, workspace=None):
        if workspace is not None:
            return workspace
        if self.wm is None:
            raise SessionError("SessionManager has no WorkspaceManager configured.")
        ws = self.wm.resolve_workspace()
        if ws is None:
            raise SessionError("No active workspace. Create or switch a workspace first.")
        return ws

    def _activate(self, workspace_id, session_id):
        session = self._sessions[session_id]
        session.last_active_at = time.time()
        self._active_by_workspace[workspace_id] = session_id
        self._save_registry()

    def _touch_and_save(self, session):
        session.last_active_at = time.time()
        self._save_registry()

    def _find_by_name(self, name, workspace_id=None):
        for s in self._sessions.values():
            if s.name == name and (workspace_id is None or s.workspace_id == workspace_id):
                return s
        return None

    def _resolve_identifier(self, identifier, workspace=None):
        ws = workspace

        # Numeric string / int -> 1-based index into list_sessions(ws),
        # scoped to the workspace when we have one (matches the numbered
        # list the CLI prints via /session list).
        if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
            index = int(identifier) - 1
            listed = self.list_sessions(ws) if ws is not None else list(self._sessions.values())
            if 0 <= index < len(listed):
                return listed[index]
            return None

        # Exact session id
        if identifier in self._sessions:
            return self._sessions[identifier]

        # Fall back to matching by name (scoped to workspace if given)
        return self._find_by_name(identifier, workspace_id=ws.id if ws is not None else None)
    
    def remove_sessions_for_workspace(self, workspace_id: str) -> None:
        """Drop all sessions belonging to a specific workspace."""
        to_delete = [sid for sid, s in self._sessions.items() if s.workspace_id == workspace_id]
        for sid in to_delete:
            del self._sessions[sid]

        # If the active session was in this workspace, clear it
            if self._active_by_workspace.get(workspace_id):
                del self._active_by_workspace[workspace_id]

            self._save_registry()
