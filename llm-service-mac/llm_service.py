#!/usr/bin/env python3
"""
llm_service.py

Manages Ollama and llama-server as independent launchd services on macOS,
completely outside of Homebrew's control.

Usage:
  python3 llm_service.py <service> <command> [env_file]

Services:
  ollama        Manage the Ollama server
  llama         Manage the llama-server

Commands:
  install [env_file]   Write plist from env file, then load the service
  load                 Load (start) the service
  unload               Unload (stop) the service
  reload               Unload then load (restart) the service
  status               Show whether the service is running
  uninstall            Stop and delete the plist

Default env file locations:
  ollama:   ~/.ollama/env
  llama:    ~/.config/llama-server/env

Example env files:

  ~/.ollama/env
    OLLAMA_HOST=0.0.0.0
    OLLAMA_ORIGINS=*
    OLLAMA_KEEP_ALIVE=5m

  ~/.config/llama-server/env
    LLAMA_ARG_HOST=0.0.0.0
    LLAMA_ARG_PORT=8080
    LLAMA_ARG_MODELS_DIR=/Users/you/models
    LLAMA_ARG_CTX_SIZE=8192
    LLAMA_ARG_N_GPU_LAYERS=99
    LLAMA_ARG_SLEEP_IDLE_SECONDS=300

Lines starting with # and blank lines are ignored in env files.
"""

import sys
import shutil
import subprocess
from pathlib import Path
from xml.etree.ElementTree import indent
import xml.etree.ElementTree as ET


# ── Service definitions ───────────────────────────────────────────────────────

SERVICES = {
    "ollama": {
        "label":        "local.ollama.serve",
        "bin_candidates": [
            "/opt/homebrew/bin/ollama",    # Apple Silicon
            "/usr/local/bin/ollama",       # Intel Mac
        ],
        "bin_which":    "ollama",
        "program_args": ["serve"],         # appended after the binary
        "default_env":  Path.home() / ".ollama" / "env",
        "log":          Path.home() / ".ollama" / "ollama.log",
        "note":         "Stop Homebrew's service first: brew services stop ollama",
    },
    "llama": {
        "label":        "local.llama-server.serve",
        "bin_candidates": [
            "/opt/homebrew/bin/llama-server",   # Apple Silicon
            "/usr/local/bin/llama-server",      # Intel Mac
        ],
        "bin_which":    "llama-server",
        "program_args": [],                # llama-server needs no subcommand
        "default_env":  Path.home() / ".config" / "llama-server" / "env",
        "log":          Path.home() / ".config" / "llama-server" / "llama-server.log",
        "note":         "Stop Homebrew's service first: brew services stop llama.cpp",
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_bin(svc: dict) -> str:
    for path in svc["bin_candidates"]:
        if Path(path).exists():
            return path
    found = shutil.which(svc["bin_which"])
    if found:
        return found
    return svc["bin_candidates"][0]   # fall back with a warning


def parse_env_file(path: Path) -> dict:
    env = {}
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                print(f"  Warning: skipping line {lineno} (no '=' found): {line!r}")
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not key:
                print(f"  Warning: skipping line {lineno} (empty key)")
                continue
            env[key] = value
    return env


def build_plist(svc: dict, env_vars: dict, binary: str) -> ET.Element:
    label    = svc["label"]
    log_path = str(svc["log"])

    plist = ET.Element("plist", version="1.0")
    root  = ET.SubElement(plist, "dict")

    def add(parent, key, tag, text=None):
        ET.SubElement(parent, "key").text = key
        el = ET.SubElement(parent, tag)
        if text is not None:
            el.text = text
        return el

    add(root, "Label", "string", label)

    ET.SubElement(root, "key").text = "ProgramArguments"
    args_el = ET.SubElement(root, "array")
    ET.SubElement(args_el, "string").text = binary
    for arg in svc["program_args"]:
        ET.SubElement(args_el, "string").text = arg

    ET.SubElement(root, "key").text = "EnvironmentVariables"
    env_dict = ET.SubElement(root, "dict")
    for k, v in env_vars.items():
        ET.SubElement(env_dict, "key").text    = k
        ET.SubElement(env_dict, "string").text = v

    add(root, "RunAtLoad",         "true")
    add(root, "KeepAlive",         "true")
    add(root, "StandardOutPath",   "string", log_path)
    add(root, "StandardErrorPath", "string", log_path)

    return plist


def plist_path(svc: dict) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{svc['label']}.plist"


def write_plist(svc: dict, plist: ET.Element):
    path = plist_path(svc)
    indent(plist, space="    ")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                b'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n')
        ET.ElementTree(plist).write(f, encoding="utf-8", xml_declaration=False)
        f.write(b"\n")


def launchctl(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl"] + args, capture_output=True, text=True)


def is_loaded(svc: dict) -> bool:
    return launchctl(["list", svc["label"]]).returncode == 0


def ensure_plist(svc: dict):
    if not plist_path(svc).exists():
        print(f"Error: plist not found at {plist_path(svc)}")
        print("Run 'install' first.")
        sys.exit(1)


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_install(svc: dict, env_file: Path):
    print(f"Service:  {svc['label']}")
    print(f"Env file: {env_file}")

    if not env_file.exists():
        # Offer to create the default config directory and a starter file
        print(f"\nEnv file not found: {env_file}")
        env_file.parent.mkdir(parents=True, exist_ok=True)
        print(f"Created directory:  {env_file.parent}")
        print( "Please create the env file with your settings, for example:")
        if "ollama" in svc["label"]:
            print( "  OLLAMA_HOST=0.0.0.0")
            print( "  OLLAMA_KEEP_ALIVE=5m")
        else:
            print( "  LLAMA_ARG_HOST=0.0.0.0")
            print( "  LLAMA_ARG_PORT=8080")
            print( "  LLAMA_ARG_MODELS_DIR=/path/to/your/models")
            print( "  LLAMA_ARG_SLEEP_IDLE_SECONDS=300")
        sys.exit(1)

    env_vars = parse_env_file(env_file)
    if not env_vars:
        print("No variables found in env file — please add some settings.")
        sys.exit(1)

    print(f"\nFound {len(env_vars)} variable(s):")
    for k, v in env_vars.items():
        print(f"  {k} = {v}")

    binary = find_bin(svc)
    if not Path(binary).exists():
        print(f"\n  Warning: binary not found at {binary}")
        print(f"  Check that {svc['bin_which']} is installed (brew install ...).")

    if is_loaded(svc):
        print("\nUnloading existing service before reinstalling...")
        cmd_unload(svc, quiet=True)

    plist = build_plist(svc, env_vars, binary)
    write_plist(svc, plist)
    print(f"\nWrote plist: {plist_path(svc)}")
    if svc.get("note"):
        print(f"Note: {svc['note']}")

    cmd_load(svc)


def cmd_load(svc: dict):
    ensure_plist(svc)
    if is_loaded(svc):
        print("Service is already loaded.")
        return
    result = launchctl(["load", "-w", str(plist_path(svc))])
    if result.returncode == 0:
        print("Service loaded and started.")
    else:
        print(f"Error loading service: {result.stderr.strip()}")
        sys.exit(1)


def cmd_unload(svc: dict, quiet=False):
    if not is_loaded(svc):
        if not quiet:
            print("Service is not currently loaded.")
        return
    result = launchctl(["unload", "-w", str(plist_path(svc))])
    if result.returncode == 0:
        if not quiet:
            print("Service unloaded and stopped.")
    else:
        print(f"Error unloading service: {result.stderr.strip()}")
        sys.exit(1)


def cmd_reload(svc: dict):
    ensure_plist(svc)
    cmd_unload(svc, quiet=True)
    cmd_load(svc)
    print("Service reloaded.")


def cmd_status(svc: dict):
    path = plist_path(svc)
    print(f"Service: {svc['label']}")

    if not path.exists():
        print(f"Plist:   not installed ({path})")
        return

    print(f"Plist:   {path}")

    result = launchctl(["list", svc["label"]])
    if result.returncode != 0:
        print("Status:  not loaded")
        return

    pid, exit_code = None, None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith('"PID"'):
            pid = line.split("=")[-1].strip().rstrip(";").strip('"')
        elif line.startswith('"LastExitStatus"'):
            exit_code = line.split("=")[-1].strip().rstrip(";").strip('"')

    if pid and pid != "0":
        print(f"Status:  running  (PID {pid})")
    else:
        status = f"stopped (last exit: {exit_code})" if exit_code else "stopped"
        print(f"Status:  {status}")

    print(f"Log:     {svc['log']}")


def cmd_uninstall(svc: dict):
    cmd_unload(svc, quiet=True)
    path = plist_path(svc)
    if path.exists():
        path.unlink()
        print(f"Deleted: {path}")
    else:
        print("Plist was not installed.")
    print("Uninstall complete.")


# ── Entry point ───────────────────────────────────────────────────────────────

COMMANDS = {
    "install":   "Write plist from env file, then load the service",
    "load":      "Load (start) the service",
    "unload":    "Unload (stop) the service",
    "reload":    "Unload then load (restart) the service",
    "status":    "Show whether the service is running",
    "uninstall": "Stop and delete the plist",
}


def usage():
    prog = Path(sys.argv[0]).name
    print(f"Usage: {prog} <service> <command> [env_file]\n")
    print("Services:")
    print("  ollama    Manage the Ollama server")
    print("  llama     Manage the llama-server\n")
    print("Commands:")
    for cmd, desc in COMMANDS.items():
        print(f"  {cmd:<12} {desc}")
    print()
    print("Default env files:")
    for name, svc in SERVICES.items():
        print(f"  {name:<8}  {svc['default_env']}")
    print()
    print("Examples:")
    print(f"  {prog} ollama install")
    print(f"  {prog} ollama status")
    print(f"  {prog} llama  install ~/.config/llama-server/env")
    print(f"  {prog} llama  reload")


def main():
    if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):
        usage()
        sys.exit(0)

    svc_name = sys.argv[1].lower()
    command  = sys.argv[2].lower()

    if svc_name not in SERVICES:
        print(f"Unknown service: {svc_name!r}  (choose: {', '.join(SERVICES)})\n")
        usage()
        sys.exit(1)

    svc = SERVICES[svc_name]

    if command == "install":
        env_file = Path(sys.argv[3]) if len(sys.argv) > 3 else svc["default_env"]
        cmd_install(svc, env_file)
    elif command == "load":
        cmd_load(svc)
    elif command == "unload":
        cmd_unload(svc)
    elif command == "reload":
        cmd_reload(svc)
    elif command == "status":
        cmd_status(svc)
    elif command == "uninstall":
        cmd_uninstall(svc)
    else:
        print(f"Unknown command: {command!r}\n")
        usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
