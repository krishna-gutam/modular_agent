#!/usr/bin/env python3
"""
CLI Chatbot for testing ModelGateway (modular_agent).

Lets you pick a provider + model, chat interactively, and exercise the
gateway's generate() / list_models() methods against whichever API keys
you have set in your environment (or a .env file).

Usage:
    python chatbot.py
    python chatbot.py --provider Groq --model llama-3.1-8b-instant
    python chatbot.py --provider OpenAI --model gpt-4o-mini --temperature 0.2

In-chat commands (type these instead of a message):
    /help                    Show this list of commands
    /providers               List configured providers and whether a key is set
    /provider <name>         Switch provider (keeps conversation history)
    /model <name>            Switch model
    /models                  Fetch live model list for the current provider
    /system <text>           Set/replace the system prompt
    /temp <value>            Set sampling temperature (e.g. /temp 0.3)
    /history                 Print the full conversation so far
    /reset                   Clear conversation history (keeps system prompt)
    /raw                     Toggle printing the raw JSON response from the API
    /workspace               Show the current active workspace
    /workspace list          List all known workspaces
    /workspace new <path>    Create (or re-activate) a workspace at <path>
    /workspace switch <sel>  Switch to a workspace by number or path
    /session                 Show the current active session
    /session list            List all sessions in the active workspace
    /session new [name]      Create a new session (default name is a uuid)
    /session rename <name>   Rename the active session
    /session delete <sel>    Delete a session by number or name
    /session switch <sel>    Switch to a session by number or name
    /quit or /exit           Leave the chat
"""

import argparse
import json
import os
import sys

from model_gateway import ModelGateway
from workspace_manager import WorkspaceManager, WorkspaceError
from session_manager import SessionManager, SessionError
from tools import TOOLS, execute_tool

# ANSI colors (safe no-op looking codes on terminals that don't support them)
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"

DEFAULT_MODELS = {
    "OpenAI": "gpt-4o-mini",
    "OpenRouter": "openai/gpt-4o-mini",
    "Groq": "llama-3.1-8b-instant",
    "Google Gemini (OpenAI Compatible)": "gemini-1.5-flash",
}


def provider_has_key(gateway, provider_name):
    config = gateway.CONFIGS.get(provider_name, {})
    env_var = config.get("api_key_env")
    return bool(env_var and os.getenv(env_var))


def print_providers(gateway, current=None):
    print(f"\n{BOLD}Configured providers:{RESET}")
    for name in gateway.CONFIGS:
        has_key = provider_has_key(gateway, name)
        marker = f"{GREEN}✔ key set{RESET}" if has_key else f"{RED}✘ no key{RESET}"
        pointer = f"{CYAN}→{RESET} " if name == current else "  "
        print(f"{pointer}{name} [{marker}]")
    print()


def choose_provider(gateway):
    names = list(gateway.CONFIGS.keys())
    print_providers(gateway)
    while True:
        choice = input(
            f"Pick a provider by number or name {DIM}(1-{len(names)}){RESET}: "
        ).strip()
        if not choice:
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            return names[int(choice) - 1]
        for name in names:
            if choice.lower() == name.lower():
                return name
        print(f"{RED}Unrecognized choice, try again.{RESET}")


def format_workspace_line(ws, index=None, current_id=None):
    pointer = f"{CYAN}→{RESET} " if ws.id == current_id else "  "
    label = f"{index}. " if index is not None else ""
    return f"{pointer}{label}{BOLD}{ws.name}{RESET} {DIM}({ws.path}){RESET}"


def print_workspaces(wm):
    workspaces = wm.list_workspaces()
    current = wm.resolve_workspace()
    current_id = current.id if current else None
    print(f"\n{BOLD}Known workspaces:{RESET}")
    if not workspaces:
        print(f"{DIM}(none yet — use /workspace new <path>){RESET}")
    for i, ws in enumerate(workspaces, start=1):
        print(format_workspace_line(ws, index=i, current_id=current_id))
    print()


def print_current_workspace(wm):
    ws = wm.resolve_workspace()
    if ws is None:
        print(f"{YELLOW}No active workspace.{RESET} Use /workspace new <path> to create one.")
    else:
        print(f"Active workspace: {CYAN}{ws.name}{RESET} {DIM}({ws.path}){RESET}")


def setup_workspace(wm, requested_path):
    """
    Run the "1. WORKSPACE LIFECYCLE" flow at startup:
      - If --workspace was passed, create/activate that path directly.
      - Else if workspaces already exist, let the user create a new one
        or switch to an existing one (defaulting to the most recent).
      - Else, create one at the current directory (the diagram's default).
    """
    if requested_path:
        try:
            return wm.create_workspace(requested_path)
        except WorkspaceError as e:
            print(f"{RED}{e}{RESET}")
            sys.exit(1)

    existing = wm.list_workspaces()
    if not existing:
        # First run: default is current working directory, per the diagram.
        ws = wm.create_workspace(os.getcwd())
        print(f"{YELLOW}Created workspace at {ws.path}{RESET}")
        return ws

    print_workspaces(wm)
    print(f"{DIM}Enter a number to switch to a workspace, a new path to create one,{RESET}")
    choice = input(
        f"{DIM}or press Enter to use the most recent one:{RESET} "
    ).strip()

    if not choice:
        return wm.switch_workspace(1)  # most recent, per list_workspaces() ordering
    if choice.isdigit():
        try:
            return wm.switch_workspace(choice)
        except WorkspaceError as e:
            print(f"{RED}{e}{RESET}")
            return wm.switch_workspace(1)
    try:
        return wm.create_workspace(choice)
    except WorkspaceError as e:
        print(f"{RED}{e}{RESET}")
        return wm.switch_workspace(1)


def handle_workspace_command(wm, arg):
    """Handle the /workspace [list|new <path>|switch <sel>] command."""
    parts = arg.split(maxsplit=1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""

    if not sub:
        print_current_workspace(wm)
        return

    if sub == "list":
        print_workspaces(wm)
        return

    if sub in ("new", "create"):
        if not rest:
            print(f"{RED}Usage: /workspace new <path>{RESET}")
            return
        try:
            ws = wm.create_workspace(rest)
            print(f"Workspace {CYAN}{ws.name}{RESET} ready at {DIM}{ws.path}{RESET}. "
                  f"Working directory switched.")
        except WorkspaceError as e:
            print(f"{RED}{e}{RESET}")
        return

    if sub == "switch":
        if not rest:
            print(f"{RED}Usage: /workspace switch <number|path>{RESET}")
            return
        try:
            ws = wm.switch_workspace(rest)
            print(f"Switched to workspace {CYAN}{ws.name}{RESET} {DIM}({ws.path}){RESET}.")
        except WorkspaceError as e:
            print(f"{RED}{e}{RESET}")
        return

    print(f"{RED}Usage: /workspace [list|new <path>|switch <number|path>]{RESET}")


def format_session_line(session, index=None, current_id=None):
    pointer = f"{CYAN}→{RESET} " if session.id == current_id else "  "
    label = f"{index}. " if index is not None else ""
    model_bits = f"{session.provider or '?'} / {session.model or '?'}"
    return (
        f"{pointer}{label}{BOLD}{session.name}{RESET} "
        f"{DIM}({model_bits}, {len(session.messages)} msgs){RESET}"
    )


def print_sessions(sm):
    sessions = sm.list_sessions()
    current = sm.resolve_session()
    current_id = current.id if current else None
    print(f"\n{BOLD}Sessions in this workspace:{RESET}")
    if not sessions:
        print(f"{DIM}(none yet — use /session new){RESET}")
    for i, s in enumerate(sessions, start=1):
        print(format_session_line(s, index=i, current_id=current_id))
    print()


def print_current_session(sm):
    session = sm.resolve_session()
    if session is None:
        print(f"{YELLOW}No active session.{RESET} Use /session new to create one.")
    else:
        print(
            f"Active session: {CYAN}{session.name}{RESET} "
            f"{DIM}({session.provider or '?'} / {session.model or '?'}, "
            f"temp={session.temperature}, {len(session.messages)} msgs){RESET}"
        )


def setup_session(sm, requested_name):
    """
    Run the "2. SESSION LIFECYCLE" flow at startup:
      - If --session was passed, resume that session by name if it
        exists in the active workspace, else create it fresh.
      - Else if sessions already exist in this workspace, let the user
        pick one to resume or start a new one (defaulting to the most
        recent, mirroring setup_workspace()).
      - Else, create a brand new session (default name is a uuid).

    Provider/model/temperature aren't seeded here: at startup we don't
    yet know the effective config (it may come from --provider/--model/
    --temperature, from a resumed session, or from an interactive
    prompt), so main() resolves and persists those onto the session
    right after this returns.
    """
    if requested_name:
        try:
            return sm.switch_session(requested_name)
        except SessionError:
            return sm.create_session(name=requested_name)

    existing = sm.list_sessions()
    if not existing:
        session = sm.create_session()
        print(f"{YELLOW}Created session {session.name}{RESET}")
        return session

    print_sessions(sm)
    print(f"{DIM}Enter a number to switch to a session, a new name to create one,{RESET}")
    choice = input(
        f"{DIM}or press Enter to use the most recent one:{RESET} "
    ).strip()

    if not choice:
        return sm.switch_session(1)  # most recent, per list_sessions() ordering
    if choice.isdigit():
        try:
            return sm.switch_session(choice)
        except SessionError as e:
            print(f"{RED}{e}{RESET}")
            return sm.switch_session(1)
    return sm.create_session(name=choice)


def handle_session_command(sm, session, arg, provider, model, temperature):
    """
    Handle the /session [list|new [name]|rename <name>|delete <sel>|switch <sel>]
    command. Returns a new active Session if the command switched sessions
    (new/delete-of-current/switch), or None if the active session is
    unchanged.
    """
    parts = arg.split(maxsplit=1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""

    if not sub:
        print_current_session(sm)
        return None

    if sub == "list":
        print_sessions(sm)
        return None

    if sub in ("new", "create"):
        new_session = sm.create_session(
            name=rest or None, provider=provider, model=model, temperature=temperature
        )
        print(f"Created and switched to session {CYAN}{new_session.name}{RESET}")
        return new_session

    if sub == "rename":
        if not rest:
            print(f"{RED}Usage: /session rename <new name>{RESET}")
            return None
        try:
            renamed = sm.rename_session(session.id, rest)
            print(f"Session renamed to {CYAN}{renamed.name}{RESET}")
        except SessionError as e:
            print(f"{RED}{e}{RESET}")
        return None

    if sub == "delete":
        selector = rest or session.id
        try:
            deleted = sm.delete_session(selector)
        except SessionError as e:
            print(f"{RED}{e}{RESET}")
            return None
        print(f"Session {CYAN}{deleted.name}{RESET} deleted.")
        if deleted.id != session.id:
            return None
        # We deleted the active session: fall back to the most recent
        # remaining one, or spin up a fresh session if none are left.
        remaining = sm.list_sessions()
        if remaining:
            return sm.switch_session(remaining[0].id)
        return sm.create_session(provider=provider, model=model, temperature=temperature)

    if sub == "switch":
        if not rest:
            print(f"{RED}Usage: /session switch <number|name>{RESET}")
            return None
        try:
            switched = sm.switch_session(rest)
            print(f"Switched to session {CYAN}{switched.name}{RESET}")
            return switched
        except SessionError as e:
            print(f"{RED}{e}{RESET}")
            return None

    print(f"{RED}Usage: /session [list|new [name]|rename <name>|delete <sel>|switch <number|name>]{RESET}")
    return None


def print_help():
    print(f"""
{BOLD}Commands:{RESET}
  /help                    Show this list of commands
  /providers               List configured providers and whether a key is set
  /provider <name>         Switch provider (keeps conversation history)
  /model <name>            Switch model
  /models                  Fetch live model list for the current provider
  /system <text>           Set/replace the system prompt
  /temp <value>            Set sampling temperature (e.g. /temp 0.3)
  /history                 Print the full conversation so far
  /reset                   Clear conversation history (keeps system prompt)
  /raw                     Toggle printing the raw JSON response from the API
  /workspace               Show the current active workspace
  /workspace list          List all known workspaces
  /workspace new <path>    Create (or re-activate) a workspace at <path>
  /workspace switch <sel>  Switch to a workspace by number or path
  /session                 Show the current active session
  /session list            List all sessions in the active workspace
  /session new [name]      Create a new session (default name is a uuid)
  /session rename <name>   Rename the active session
  /session delete <sel>    Delete a session by number or name
  /session switch <sel>    Switch to a session by number or name
  /quit or /exit           Leave the chat
""")


def print_history(messages):
    print(f"\n{BOLD}--- Conversation history ---{RESET}")
    if not messages:
        print(f"{DIM}(empty){RESET}")
    for m in messages:
        role = m["role"]
        color = {"system": YELLOW, "user": CYAN, "assistant": GREEN}.get(role, "")
        print(f"{color}{role}:{RESET} {m['content']}")
    print(f"{BOLD}-----------------------------{RESET}\n")


def fetch_and_print_models(gateway, provider_name):
    config = gateway.PROVIDERS.get(provider_name)
    if not config:
        print(f"{RED}No model-listing endpoint configured for {provider_name}.{RESET}")
        return
    print(f"{DIM}Fetching model list for {provider_name}...{RESET}")
    models = gateway.fetch_models(provider_name, config)
    if models is None:
        print(
            f"{RED}Could not fetch models (missing/invalid API key, or request failed).{RESET}"
        )
        return
    print(f"\n{BOLD}Available models for {provider_name} ({len(models)}):{RESET}")
    for m in models:
        print(f"  - {m}")
    print()


def extract_reply(response):
    """Pull the assistant's text content out of a ModelGateway response."""
    if "error" in response:
        return None, response["error"]
    try:
        message = response["choices"][0]["message"]
        return message.get("content", ""), None
    except (KeyError, IndexError, TypeError):
        return None, f"Unexpected response shape: {json.dumps(response)[:500]}"


def main():
    parser = argparse.ArgumentParser(description="CLI chatbot to test ModelGateway")
    parser.add_argument("--provider", help="Provider name (e.g. OpenAI, Groq, OpenRouter)")
    parser.add_argument("--model", help="Model name/id to use")
    parser.add_argument(
        "--temperature", type=float, default=None,
        help="Sampling temperature (default: resumed session's value, or 0.7)",
    )
    parser.add_argument("--system", help="Initial system prompt")
    parser.add_argument(
        "--workspace",
        help="Workspace path to create/activate on startup (default: current directory, "
             "or prompts if other workspaces already exist)",
    )
    parser.add_argument(
        "--session",
        help="Session name to create/resume in the active workspace (default: prompts if "
             "other sessions already exist, else creates a new uuid-named session)",
    )
    args = parser.parse_args()

    gateway = ModelGateway()
    wm = WorkspaceManager()
    workspace = setup_workspace(wm, args.workspace)

    sm = SessionManager(wm)
    session = setup_session(sm, args.session)

    # Resolve effective provider/model/temperature with this precedence:
    # explicit CLI flag > value restored from a resumed session > interactive
    # prompt / built-in default. This is what makes /session switch (and a
    # plain restart with --session <name>) restore "conversation + model
    # configuration" per the diagram's Switch Session step.
    provider = args.provider if args.provider in gateway.CONFIGS else None
    if provider is None and session.provider in gateway.CONFIGS:
        provider = session.provider
    if provider is None:
        if args.provider:
            print(f"{RED}Unknown provider '{args.provider}'.{RESET}")
        provider = choose_provider(gateway)

    if not provider_has_key(gateway, provider):
        env_var = gateway.CONFIGS[provider]["api_key_env"]
        print(
            f"{YELLOW}Warning: {env_var} is not set in your environment/.env — "
            f"requests to {provider} will fail until you set it.{RESET}"
        )

    model = args.model or session.model or DEFAULT_MODELS.get(provider, "")
    if not model:
        model = input("Enter a model name/id to use: ").strip()

    temperature = args.temperature if args.temperature is not None else (
        session.temperature if session.temperature is not None else 0.7
    )

    messages = list(session.messages)
    if args.system:
        messages = [m for m in messages if m["role"] != "system"]
        messages.insert(0, {"role": "system", "content": args.system})

    # Persist the resolved config/history back onto the session so a
    # brand-new session's defaults (and any --system override) are saved
    # immediately, not just after the first message.
    sm.update_model_config(session, provider=provider, model=model, temperature=temperature)
    sm.set_messages(session, messages)

    show_raw = False

    print(f"\n{BOLD}ModelGateway CLI Chatbot{RESET}")
    print(f"Provider: {CYAN}{provider}{RESET}  Model: {CYAN}{model}{RESET}  "
          f"Temp: {CYAN}{temperature}{RESET}")
    print(f"Workspace: {CYAN}{workspace.name}{RESET} {DIM}({workspace.path}){RESET}")
    print(f"Session: {CYAN}{session.name}{RESET} {DIM}({len(messages)} msgs restored){RESET}")
    print(f"{DIM}Type /help for commands, /quit to exit.{RESET}\n")

    while True:
        try:
            ws_prompt = wm.resolve_workspace()
            ws_label = ws_prompt.name if ws_prompt else "no-workspace"
            user_input = input(
                f"{CYAN}you{RESET} {DIM}[{ws_label}/{session.name}]{RESET}{CYAN}>{RESET} "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            sm.set_status(session, "IDLE")
            print("\nBye!")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd in ("/quit", "/exit"):
                sm.set_status(session, "IDLE")
                print("Bye!")
                break
            elif cmd == "/help":
                print_help()
            elif cmd == "/providers":
                print_providers(gateway, current=provider)
            elif cmd == "/provider":
                if arg and arg in gateway.CONFIGS:
                    provider = arg
                    if not provider_has_key(gateway, provider):
                        env_var = gateway.CONFIGS[provider]["api_key_env"]
                        print(f"{YELLOW}Warning: {env_var} is not set.{RESET}")
                    sm.update_model_config(session, provider=provider)
                    print(f"Switched provider to {CYAN}{provider}{RESET}")
                else:
                    print(f"{RED}Usage: /provider <name>. Try /providers to see options.{RESET}")
            elif cmd == "/model":
                if arg:
                    model = arg
                    sm.update_model_config(session, model=model)
                    print(f"Switched model to {CYAN}{model}{RESET}")
                else:
                    print(f"{RED}Usage: /model <name>{RESET}")
            elif cmd == "/models":
                fetch_and_print_models(gateway, provider)
            elif cmd == "/system":
                if arg:
                    messages = [m for m in messages if m["role"] != "system"]
                    messages.insert(0, {"role": "system", "content": arg})
                    sm.set_messages(session, messages)
                    print(f"{YELLOW}System prompt set.{RESET}")
                else:
                    print(f"{RED}Usage: /system <text>{RESET}")
            elif cmd == "/temp":
                try:
                    temperature = float(arg)
                    sm.update_model_config(session, temperature=temperature)
                    print(f"Temperature set to {CYAN}{temperature}{RESET}")
                except ValueError:
                    print(f"{RED}Usage: /temp <number>{RESET}")
            elif cmd == "/history":
                print_history(messages)
            elif cmd == "/reset":
                messages = [m for m in messages if m["role"] == "system"]
                sm.set_messages(session, messages)
                print(f"{YELLOW}Conversation history cleared.{RESET}")
            elif cmd == "/raw":
                show_raw = not show_raw
                print(f"Raw response printing: {CYAN}{'on' if show_raw else 'off'}{RESET}")
            elif cmd == "/workspace":
                handle_workspace_command(wm, arg)
            elif cmd == "/session":
                switched = handle_session_command(sm, session, arg, provider, model, temperature)
                if switched is not None:
                    # Active session changed (new/switch/delete-of-current):
                    # restore that session's conversation + model config,
                    # same as the startup resolution logic above.
                    session = switched
                    provider = session.provider or provider
                    model = session.model or model
                    temperature = session.temperature if session.temperature is not None else temperature
                    messages = list(session.messages)
            else:
                print(f"{RED}Unknown command '{cmd}'. Type /help for the list.{RESET}")
            continue

        messages.append({"role": "user", "content": user_input})
        sm.set_status(session, "RUNNING")

        print(f"{DIM}Calling {provider} ({model})...{RESET}")
        response = gateway.generate(provider, model, messages, temperature=temperature, tools=TOOLS)

        msg = response.get("message", {})

        tool_calls = msg.get("tool_calls")
        if tool_calls:
            messages.append(msg)
            print(f"{model}: [Calling tools...]")

            for tc in tool_calls:
                    call_id = tc["id"]
                    fn_name = tc["function"]["name"]
                    try:
                        fn_args = json.loads(tc["function"]["arguments"])
                    except Exception:
                        fn_args = {}
                    print(f"{model}: [Calling tools...] {fn_name} {fn_args}")
                    approval=input(f"{model}: [Approve this tool call? (y/n): ")
                    if approval == "y":
                        tool_output = execute_tool(fn_name, fn_args)
                        print(f"[Tool Output for {fn_name}]: {tool_output}")

                        messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_output
                    })
            continue

        if show_raw:
            print(f"{DIM}{json.dumps(response, indent=2)}{RESET}")

        reply, error = extract_reply(response)
        if error:
            print(f"{RED}Error: {error}{RESET}\n")
            messages.pop()  # don't keep a user turn that got no reply
            sm.set_status(session, "IDLE")
            continue

        messages.append({"role": "assistant", "content": reply})
        # Persist assistant response (diagram: "Agent->>SM: Persist assistant
        # response") and mark the run complete (Section 10: "Update
        # lastActiveAt").
        sm.set_messages(session, messages)
        sm.set_status(session, "IDLE")
        print(f"{GREEN}assistant>{RESET} {reply}\n")


if __name__ == "__main__":
    sys.exit(main() or 0)
