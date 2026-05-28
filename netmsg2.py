#!/usr/bin/env python3
"""
netmsg.py — Local Network Terminal Messenger
Send and receive messages to/from other machines on the same network.

Usage:
  python3 netmsg.py [--port PORT] [--name NAME]

Controls:
  <ip> <message>               Send using the current default port
  <ip>:<port> <message>        Send to a specific port on that host
  /send <ip>[:<port>] <msg>    Explicit send command (port optional)
  /port <number>               Change your default listen/send port
  /port                        Show the current default port
  /history                     Show message history
  /clear                       Clear the screen
  /quit                        Exit
"""

import socket
import threading
import argparse
import sys
import os
import json
from datetime import datetime

# ── ANSI colours ────────────────────────────────────────────────────────────
R  = "\033[0m"          # reset
BOLD = "\033[1m"
CYAN  = "\033[96m"
GREEN = "\033[92m"
YELLOW= "\033[93m"
MAGENTA="\033[95m"
RED   = "\033[91m"
DIM   = "\033[2m"
WHITE = "\033[97m"

DEFAULT_PORT = 55000
BUFFER_SIZE  = 4096

history: list[dict] = []
history_lock = threading.Lock()
my_name  = ""
my_port  = DEFAULT_PORT

# Live server socket — kept so we can close it when switching ports
_server_sock: socket.socket | None = None
_server_lock = threading.Lock()


# ── Helpers ──────────────────────────────────────────────────────────────────

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def print_banner(local_ip: str) -> None:
    w = os.get_terminal_size().columns if sys.stdout.isatty() else 60
    bar = "─" * w
    print(f"\n{CYAN}{BOLD}{bar}{R}")
    title = "  netmsg  —  Local Network Messenger"
    print(f"{CYAN}{BOLD}{title}{R}")
    print(f"{CYAN}{bar}{R}")
    print(f"  {DIM}Your IP   :{R} {BOLD}{WHITE}{local_ip}{R}")
    print(f"  {DIM}Your name :{R} {BOLD}{WHITE}{my_name}{R}")
    print(f"  {DIM}Port      :{R} {BOLD}{WHITE}{my_port}{R}")
    print(f"{CYAN}{bar}{R}")
    print(f"  {DIM}Commands:{R}")
    print(f"    {YELLOW}<ip> <message>{R}               — send (uses default port)")
    print(f"    {YELLOW}<ip>:<port> <message>{R}        — send to a specific port")
    print(f"    {YELLOW}/send <ip>[:<port>] <msg>{R}    — explicit send")
    print(f"    {YELLOW}/port <number>{R}               — change default port")
    print(f"    {YELLOW}/history{R}                     — show message log")
    print(f"    {YELLOW}/clear{R}                       — clear screen")
    print(f"    {YELLOW}/quit{R}                        — exit")
    print(f"{CYAN}{bar}{R}\n")


def log(direction: str, peer_ip: str, peer_name: str, text: str, port: int | None = None) -> None:
    entry = {
        "time": ts(),
        "direction": direction,   # "in" | "out"
        "peer_ip": peer_ip,
        "peer_name": peer_name,
        "text": text,
        "port": port or my_port,
    }
    with history_lock:
        history.append(entry)


def print_incoming(peer_ip: str, peer_name: str, text: str, port: int | None = None) -> None:
    port_tag = f":{port}" if port else ""
    tag   = f"{MAGENTA}▶ {peer_name} ({peer_ip}{port_tag}){R}"
    stamp = f"{DIM}[{ts()}]{R}"
    # Move to a fresh line so the prompt isn't garbled
    sys.stdout.write(f"\r{' ' * 2}\r")
    print(f"{stamp} {tag}: {WHITE}{text}{R}")
    print(f"{CYAN}>{R} ", end="", flush=True)


def print_outgoing(peer_ip: str, text: str, port: int | None = None) -> None:
    stamp = f"{DIM}[{ts()}]{R}"
    port_str = port or my_port
    tag   = f"{GREEN}◀ you → {peer_ip}:{port_str}{R}"
    print(f"{stamp} {tag}: {WHITE}{text}{R}")


def print_error(msg: str) -> None:
    print(f"{RED}[!] {msg}{R}")


def print_info(msg: str) -> None:
    print(f"{YELLOW}[i] {msg}{R}")


# ── Server (receive) ─────────────────────────────────────────────────────────

def handle_client(conn: socket.socket, addr: tuple, listen_port: int) -> None:
    peer_ip = addr[0]
    try:
        raw = b""
        while True:
            chunk = conn.recv(BUFFER_SIZE)
            if not chunk:
                break
            raw += chunk
        payload = json.loads(raw.decode("utf-8"))
        peer_name = payload.get("name", peer_ip)
        text      = payload.get("text", "")
        if text:
            log("in", peer_ip, peer_name, text, port=listen_port)
            print_incoming(peer_ip, peer_name, text, port=listen_port)
    except Exception as e:
        print_error(f"Failed to read from {peer_ip}: {e}")
    finally:
        conn.close()


def server_thread(port: int) -> None:
    global _server_sock
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("", port))
    except OSError as e:
        print_error(f"Cannot bind to port {port}: {e}")
        return
    srv.listen(10)
    with _server_lock:
        _server_sock = srv
    while True:
        try:
            conn, addr = srv.accept()
            t = threading.Thread(
                target=handle_client, args=(conn, addr, port), daemon=True
            )
            t.start()
        except Exception:
            break  # socket was closed (port change) or real error


def start_server(port: int) -> None:
    """Launch a fresh listener thread on the given port."""
    t = threading.Thread(target=server_thread, args=(port,), daemon=True)
    t.start()


def switch_port(new_port: int) -> bool:
    """
    Close the current listener and open a new one on new_port.
    Returns True on success, False if the port is unusable.
    """
    global my_port, _server_sock
    # Attempt to pre-check the port before tearing down the old one
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("", new_port))
        probe.close()
    except OSError as e:
        print_error(f"Port {new_port} is unavailable: {e}")
        return False

    # Close the current server socket to unblock its accept() loop
    with _server_lock:
        if _server_sock:
            try:
                _server_sock.close()
            except Exception:
                pass
            _server_sock = None

    my_port = new_port
    start_server(new_port)
    return True


# ── Client (send) ────────────────────────────────────────────────────────────

def send_message(target_ip: str, text: str, port: int | None = None) -> None:
    target_port = port if port is not None else my_port
    payload = json.dumps({"name": my_name, "text": text}).encode("utf-8")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((target_ip, target_port))
        s.sendall(payload)
        s.close()
        log("out", target_ip, my_name, text, port=target_port)
        print_outgoing(target_ip, text, port=target_port)
    except socket.timeout:
        print_error(f"Connection to {target_ip}:{target_port} timed out.")
    except ConnectionRefusedError:
        print_error(f"{target_ip}:{target_port} refused the connection. Is netmsg running there?")
    except OSError as e:
        print_error(f"Could not reach {target_ip}: {e}")


# ── /history ─────────────────────────────────────────────────────────────────

def show_history() -> None:
    with history_lock:
        snap = list(history)
    if not snap:
        print_info("No messages yet.")
        return
    w = os.get_terminal_size().columns if sys.stdout.isatty() else 60
    print(f"\n{CYAN}{'─'*w}{R}")
    print(f"{CYAN}{BOLD}  Message History{R}")
    print(f"{CYAN}{'─'*w}{R}")
    for e in snap:
        stamp = f"{DIM}[{e['time']}]{R}"
        port_tag = f":{e.get('port', my_port)}"
        if e["direction"] == "in":
            who = f"{MAGENTA}{e['peer_name']} ({e['peer_ip']}{port_tag}){R}"
            arrow = "▶"
        else:
            who = f"{GREEN}you → {e['peer_ip']}{port_tag}{R}"
            arrow = "◀"
        print(f"  {stamp} {arrow} {who}: {e['text']}")
    print(f"{CYAN}{'─'*w}{R}\n")


# ── REPL ─────────────────────────────────────────────────────────────────────

def is_valid_ip(s: str) -> bool:
    parts = s.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


def is_valid_port(s: str) -> bool:
    try:
        p = int(s)
        return 1 <= p <= 65535
    except ValueError:
        return False


def parse_target(token: str) -> tuple[str, int | None]:
    """
    Parse 'ip' or 'ip:port' into (ip_str, port_or_None).
    Returns (token, None) if it doesn't look like a valid target.
    """
    if ":" in token:
        ip_part, port_part = token.rsplit(":", 1)
        if is_valid_ip(ip_part) and is_valid_port(port_part):
            return ip_part, int(port_part)
        return token, None
    if is_valid_ip(token):
        return token, None
    return token, None


def repl() -> None:
    while True:
        try:
            print(f"{CYAN}>{R} ", end="", flush=True)
            line = input().strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Goodbye.{R}")
            sys.exit(0)

        if not line:
            continue

        # /quit
        if line.lower() in ("/quit", "/exit", "/q"):
            print(f"{DIM}Goodbye.{R}")
            sys.exit(0)

        # /clear
        if line.lower() == "/clear":
            os.system("clear" if os.name == "posix" else "cls")
            print_banner(get_local_ip())
            continue

        # /history
        if line.lower() in ("/history", "/h"):
            show_history()
            continue

        # /port            — show current port
        # /port <number>   — change default listen/send port
        if line.lower().startswith("/port"):
            rest = line[5:].strip()
            if not rest:
                print_info(f"Current default port: {BOLD}{WHITE}{my_port}{R}")
                continue
            if not is_valid_port(rest):
                print_error(f"'{rest}' is not a valid port (1–65535).")
                continue
            new_port = int(rest)
            if new_port == my_port:
                print_info(f"Already on port {my_port}.")
                continue
            print_info(f"Switching listener from {my_port} → {new_port} …")
            if switch_port(new_port):
                print_info(f"Now listening on port {BOLD}{WHITE}{my_port}{R}.")
            continue

        # /send <ip>[:<port>] <message>
        if line.startswith("/send "):
            parts = line[6:].strip().split(" ", 1)
            if len(parts) < 2:
                print_error("Usage: /send <ip>[:<port>] <message>")
                continue
            ip, port = parse_target(parts[0])
            if not is_valid_ip(ip):
                print_error(f"'{parts[0]}' is not a valid IP (or ip:port).")
                continue
            send_message(ip, parts[1], port=port)
            continue

        # shorthand: <ip>[:<port>] <message>
        parts = line.split(" ", 1)
        if len(parts) == 2:
            ip, port = parse_target(parts[0])
            if is_valid_ip(ip):
                send_message(ip, parts[1], port=port)
                continue

        print_error("Unknown command or bad address. Type /quit to exit.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    global my_name, my_port

    parser = argparse.ArgumentParser(
        description="netmsg — send messages to other machines on your LAN"
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Port to listen/send on (default: {DEFAULT_PORT})")
    parser.add_argument("--name", type=str, default=None,
                        help="Your display name (defaults to hostname)")
    args = parser.parse_args()

    my_port = args.port
    my_name = args.name or socket.gethostname()
    local_ip = get_local_ip()

    # Start listener
    start_server(my_port)

    print_banner(local_ip)
    print_info(f"Listening for incoming messages on port {my_port} …\n")

    repl()


if __name__ == "__main__":
    main()