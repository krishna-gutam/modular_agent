#!/usr/bin/env python3
"""
Workspace Manager for modular_agent.

Implements the "Workspace Manager" (WM) participant and the
"1. WORKSPACE LIFECYCLE" flow described in coding_system_architecture.mmd:

    Create Workspace
        User provides path (default: current working directory)
        WM initializes the workspace
        WM sets the current working directory to the workspace path

    Switch Workspace
        UI lists all known workspaces
        User selects one
        WM resolves it and sets the current working directory to it

Workspaces are persisted to a small JSON registry
(~/.modular_agent/workspaces.json by default) so they survive across
chatbot restarts -- mirroring how the diagram expects a session to later
be resumed with "workspace name" intact.
"""

import json
import os
import time
import uuid

DEFAULT_REGISTRY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".state")
DEFAULT_REGISTRY_PATH = os.path.join(DEFAULT_REGISTRY_DIR, "workspaces.json")


class WorkspaceError(Exception):
    """Raised for invalid workspace operations (bad path, not found, etc.)."""


class Workspace:
    """A single registered workspace: an id, a filesystem path, and metadata."""

    def __init__(self, workspace_id, path, name=None, created_at=None, last_active_at=None):
        self.id = workspace_id
        self.path = path
        self.name = name or os.path.basename(os.path.normpath(path)) or path
        self.created_at = created_at if created_at is not None else time.time()
        self.last_active_at = last_active_at if last_active_at is not None else self.created_at

    def to_dict(self):
        return {
            "id": self.id,
            "path": self.path,
            "name": self.name,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            workspace_id=data["id"],
            path=data["path"],
            name=data.get("name"),
            created_at=data.get("created_at"),
            last_active_at=data.get("last_active_at"),
        )


class WorkspaceManager:
    """
    Manages workspace creation, switching, resolution, and persistence.

    Public API mirrors the WM participant in the sequence diagram:
        create_workspace(path)   -> createWorkspace(path)
        list_workspaces()        -> listWorkspaces()
        switch_workspace(id)     -> switchWorkspace(path)
        resolve_workspace()      -> resolveWorkspace()
    """

    def __init__(self, registry_path=None):
        self.registry_path = registry_path or DEFAULT_REGISTRY_PATH
        self._workspaces = {}   # id -> Workspace
        self._active_id = None
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

        for entry in data.get("workspaces", []):
            try:
                ws = Workspace.from_dict(entry)
            except KeyError:
                continue
            self._workspaces[ws.id] = ws
        self._active_id = data.get("active_id")

    def _save_registry(self):
        os.makedirs(os.path.dirname(self.registry_path), exist_ok=True)
        data = {
            "active_id": self._active_id,
            "workspaces": [ws.to_dict() for ws in self._workspaces.values()],
        }
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # ---------------------------------------------------------------- #
    # Lifecycle: Create / Switch / Resolve
    # ---------------------------------------------------------------- #

    def create_workspace(self, path=None, name=None, activate=True):
        """
        createWorkspace(path)

        Initialize a workspace at `path` (defaults to the current working
        directory, matching the diagram's "default is current directory
        path"), register it, and -- unless activate=False -- make it the
        active workspace and chdir into it.

        Re-creating a workspace at a path that's already registered simply
        re-activates the existing registration instead of duplicating it.
        """
        path = os.path.abspath(os.path.expanduser(path or os.getcwd()))

        existing = self._find_by_path(path)
        if existing:
            if activate:
                self._activate(existing.id)
            return existing

        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            raise WorkspaceError(f"Could not create workspace directory '{path}': {e}")

        ws = Workspace(workspace_id=str(uuid.uuid4()), path=path, name=name)
        self._workspaces[ws.id] = ws

        if activate:
            self._activate(ws.id)
        else:
            self._save_registry()

        return ws

    def list_workspaces(self):
        """
        listWorkspaces()

        Return all known workspaces, most recently active first.
        """
        return sorted(self._workspaces.values(), key=lambda w: w.last_active_at, reverse=True)

    def switch_workspace(self, identifier):
        """
        switchWorkspace(path)

        Resolve an existing workspace by path, id, or its 1-based position
        in list_workspaces() (as shown to the user), make it active, and
        chdir into it. Raises WorkspaceError if it can't be resolved or the
        path no longer exists on disk.
        """
        ws = self._resolve_identifier(identifier)
        if ws is None:
            raise WorkspaceError(f"No workspace matching '{identifier}'. Try /workspace list.")
        if not os.path.isdir(ws.path):
            raise WorkspaceError(f"Workspace path no longer exists: {ws.path}")
        self._activate(ws.id)
        return ws

    def resolve_workspace(self):
        """
        resolveWorkspace()

        Return the currently active Workspace, or None if none is active.
        """
        if self._active_id is None:
            return None
        return self._workspaces.get(self._active_id)

    def remove_workspace(self, identifier):
        """Unregister a workspace (does not delete files from disk)."""
        ws = self._resolve_identifier(identifier)
        if ws is None:
            raise WorkspaceError(f"No workspace matching '{identifier}'.")
        del self._workspaces[ws.id]
        if self._active_id == ws.id:
            self._active_id = None
        self._save_registry()
        return ws

    # ---------------------------------------------------------------- #
    # Helpers
    # ---------------------------------------------------------------- #

    def _activate(self, workspace_id):
        ws = self._workspaces[workspace_id]
        ws.last_active_at = time.time()
        self._active_id = workspace_id
        os.chdir(ws.path)
        self._save_registry()

    def _find_by_path(self, path):
        norm = os.path.abspath(os.path.expanduser(path))
        for ws in self._workspaces.values():
            if os.path.abspath(ws.path) == norm:
                return ws
        return None

    def _resolve_identifier(self, identifier):
        # Numeric string / int -> 1-based index into list_workspaces()
        if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
            index = int(identifier) - 1
            listed = self.list_workspaces()
            if 0 <= index < len(listed):
                return listed[index]
            return None

        # Exact workspace id
        if identifier in self._workspaces:
            return self._workspaces[identifier]

        # Fall back to matching by filesystem path
        return self._find_by_path(identifier)
