"""Private local control socket for the bridge UI and its command-line client."""

import json
import os
import socket
import socketserver
import stat
import threading
from bridge_paths import data_directory


SOCKET_PATH = data_directory() / ".bridge-control.sock"


def start_server(callback):
    if SOCKET_PATH.exists():
        if not stat.S_ISSOCK(SOCKET_PATH.lstat().st_mode):
            raise RuntimeError("Bridge control path is occupied by a non-socket file")
        SOCKET_PATH.unlink()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                line = self.rfile.readline(8193)
                if len(line) > 8192:
                    raise ValueError("Control request is too large")
                request = json.loads(line)
                result = callback(request)
                response = {"ok": True, "result": result}
            except Exception as error:
                response = {"ok": False, "error": str(error)}
            self.wfile.write(json.dumps(response).encode() + b"\n")

    server = socketserver.ThreadingUnixStreamServer(str(SOCKET_PATH), Handler)
    server.daemon_threads = True
    os.chmod(SOCKET_PATH, 0o600)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def request(action):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(15)
        client.connect(str(SOCKET_PATH))
        client.sendall(json.dumps(action).encode() + b"\n")
        with client.makefile("rb") as stream:
            response = json.loads(stream.readline(262144))
    if not response["ok"]:
        raise RuntimeError(response["error"])
    return response["result"]
