#!/usr/bin/env python3
"""
ollama_service.py

Manages a custom launchd service for Ollama that is completely independent
of Homebrew — so brew upgrades and 'brew services' can never touch it.

The plist is written to:
  ~/Library/LaunchAgents/local.ollama.serve.plist

Usage:
  python3 ollama_service.py install [env_file]   # write plist (+ load it)
  python3 ollama_service.py load                 # launchctl load
  python3 ollama_service.py unload               # launchctl unload
  python3 ollama_service.py reload               # unload + load
  python3 ollama_service.py status               # show if running
  python3 ollama_service.py uninstall            # unload + delete plist

env_file defaults to ~/.ollama/env if not specified.

Env file format (lines starting with # are ignored):
  OLLAMA_HOST=0.0.0.0
  OLLAMA_ORIGINS=*
  OLLAMA_KEEP_ALIVE=5m
"""

import sys
import shutil
import subprocess
from pathlib import Path
from xml.etree.ElementTree import indent
import xml.etree.ElementTree as ET

# ── Configuration ────────────────────────────────────────────────────────────

SERVICE_LABEL   = "local.ollama.serve"
PLIST_PATH      = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
DEFAULT_ENV_FILE = Path.home() / ".ollama" / "env"
LOG_PATH        = Path.home() / ".ollama" / "ollama.log"

OLLAMA_CANDIDATES = [
    "/opt/homebrew/bin/ollama",   # Apple Silicon
    "/usr/local/bin/ollama",      # Intel Mac
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def find_ollama_bin() -> str:
    for path in OLLAMA_CANDIDATES:
        if Path(path).exists():
            return path
    found = shutil.which("ollama")
    if found:
        return found
    # Return Apple Silicon default and warn later
    return OLLAMA_CANDIDATES[0]


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


def build_plist(env_vars: dict, ollama_bin: str) -> ET.Element:
    plist = ET.Element("plist", version="1.0")
    root  = ET.SubElement(plist, "dict")

    def add(parent, key, tag, text=None):
        ET.SubElement(parent, "key").text = key
        el = ET.SubElement(parent, tag)
        if text is not None:
            el.text = text
        return el

    add(root, "Label",            "string", SERVICE_LABEL)

    ET.SubElement(root, "key").text = "ProgramArguments"
    args = ET.SubElement(root, "array")
    ET.SubElement(args, "string").text = ollama_bin
    ET.SubElement(args, "string").text = "serve"

    ET.SubElement(root, "key").text = "EnvironmentVariables"
    env_dict = ET.SubElement(root, "dict")
    for k, v in env_vars.items():
        ET.SubElement(env_dict, "key").text   = k
        ET.SubElement(env_dict, "string").text = v

    add(root, "RunAtLoad",        "true")
    add(root, "KeepAlive",        "true")
    add(root, "StandardOutPath",  "string", str(LOG_PATH))
    add(root, "StandardErrorPath","string", str(LOG_PATH))

    return plist


def write_plist(plist: ET.Element):
    indent(plist, space="    ")
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PLIST_PATH, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                b'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n')
        ET.ElementTree(plist).write(f, encoding="utf-8", xml_declaration=False)
        f.write(b"\n")


def launchctl(args: list[str], check=False) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl"] + args, capture_output=True, text=True, check=check)


def is_loaded() -> bool:
    result = launchctl(["list", SERVICE_LABEL])
    return result.returncode == 0


def ensure_plist_exists():
    if not PLIST_PATH.exists():
        print(f"Error: plist not found at {PLIST_PATH}")
        print("Run 'install' first.")
        sys.exit(1)

# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_install(env_file: Path):
    print(f"Reading env vars from: {env_file}")
    if not env_file.exists():
        print(f"Error: env file not found: {env_file}")
        print("Create it with lines like:  OLLAMA_HOST=0.0.0.0")
        sys.exit(1)

    env_vars = parse_env_file(env_file)
    if not env_vars:
        print("No variables found — check your env file.")
        sys.exit(1)

    print(f"Found {len(env_vars)} variable(s):")
    for k, v in env_vars.items():
        print(f"  {k} = {v}")

    ollama_bin = find_ollama_bin()
    if not Path(ollama_bin).exists():
        print(f"  Warning: ollama binary not found at {ollama_bin}.")
        print("  Edit OLLAMA_CANDIDATES in the script if your path differs.")

    # Unload existing service before overwriting plist
    if is_loaded():
        print("Unloading existing service before reinstalling...")
        cmd_unload(quiet=True)

    plist = build_plist(env_vars, ollama_bin)
    write_plist(plist)
    print(f"Wrote plist to: {PLIST_PATH}")
    print(f"Service label:  {SERVICE_LABEL}")

    cmd_load()


def cmd_load():
    ensure_plist_exists()
    if is_loaded():
        print("Service is already loaded.")
        return
    result = launchctl(["load", "-w", str(PLIST_PATH)])
    if result.returncode == 0:
        print("Service loaded and started.")
    else:
        print(f"Error loading service: {result.stderr.strip()}")
        sys.exit(1)


def cmd_unload(quiet=False):
    if not is_loaded():
        if not quiet:
            print("Service is not currently loaded.")
        return
    result = launchctl(["unload", "-w", str(PLIST_PATH)])
    if result.returncode == 0:
        if not quiet:
            print("Service unloaded and stopped.")
    else:
        print(f"Error unloading service: {result.stderr.strip()}")
        sys.exit(1)


def cmd_reload():
    ensure_plist_exists()
    cmd_unload(quiet=True)
    cmd_load()
    print("Service reloaded.")


def cmd_status():
    if not PLIST_PATH.exists():
        print(f"Plist:   not installed ({PLIST_PATH})")
        return

    print(f"Plist:   {PLIST_PATH}")

    result = launchctl(["list", SERVICE_LABEL])
    if result.returncode != 0:
        print("Status:  not loaded")
        return

    # Parse PID and last exit code from launchctl list output
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
        status = f"stopped (last exit code: {exit_code})" if exit_code else "stopped"
        print(f"Status:  {status}")

    print(f"Log:     {LOG_PATH}")


def cmd_uninstall():
    cmd_unload(quiet=True)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
        print(f"Deleted: {PLIST_PATH}")
    else:
        print("Plist was not installed.")
    print("Uninstall complete. Homebrew's ollama service is unaffected.")


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
    print(f"Usage: {Path(sys.argv[0]).name} <command> [env_file]\n")
    print("Commands:")
    for cmd, desc in COMMANDS.items():
        print(f"  {cmd:<12} {desc}")
    print(f"\nenv_file defaults to: {DEFAULT_ENV_FILE}")
    print(f"Plist written to:     {PLIST_PATH}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        usage()
        sys.exit(0)

    command = sys.argv[1].lower()

    if command == "install":
        env_file = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_ENV_FILE
        cmd_install(env_file)
    elif command == "load":
        cmd_load()
    elif command == "unload":
        cmd_unload()
    elif command == "reload":
        cmd_reload()
    elif command == "status":
        cmd_status()
    elif command == "uninstall":
        cmd_uninstall()
    else:
        print(f"Unknown command: {command!r}\n")
        usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
