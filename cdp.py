"""Minimal Chrome DevTools Protocol client using only the Python standard library.

Chrome is the only HTTP client that gets past the FCC's Akamai Bot Manager, so we
drive a real Chrome and run our fetches *inside* a broadbandmap.fcc.gov page --
same origin, real cookies, no CORS.
"""
import base64, json, os, socket, ssl, struct, subprocess, tempfile, time, urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
]


def chrome_path():
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    raise RuntimeError("Chrome not found")


class WS:
    """Just enough RFC 6455 for CDP: text frames, masking, fragmentation, ping."""

    def __init__(self, url, timeout=120):
        assert url.startswith("ws://")
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        port = int(port or 80)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               f"Sec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        if b"101" not in buf.split(b"\r\n")[0]:
            raise RuntimeError("WebSocket handshake failed: " + buf[:200].decode("latin1"))
        self.buf = buf.split(b"\r\n\r\n", 1)[1]

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(max(65536, n - len(self.buf)))
            if not chunk:
                raise ConnectionError("socket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text):
        payload = text.encode()
        n = len(payload)
        hdr = bytearray([0x81])                       # FIN + text
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126); hdr += struct.pack(">H", n)
        else:
            hdr.append(0x80 | 127); hdr += struct.pack(">Q", n)
        mask = os.urandom(4)
        hdr += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(hdr) + masked)

    def recv(self):
        parts, opcode = [], None
        while True:
            b0, b1 = self._read(2)
            fin, op = b0 & 0x80, b0 & 0x0F
            ln = b1 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._read(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._read(8))[0]
            data = self._read(ln) if ln else b""
            if op == 0x9:                              # ping -> pong
                self.sock.sendall(b"\x8a\x80" + os.urandom(4))
                continue
            if op == 0x8:
                raise ConnectionError("websocket closed by peer")
            if op in (0x1, 0x2):
                opcode = op
            parts.append(data)
            if fin:
                return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


class Chrome:
    def __init__(self, port=9222, profile=None, headless=True):
        self.port = port
        self.profile = profile or os.path.join(tempfile.gettempdir(), "nbm_cdp_profile")
        args = [chrome_path(), f"--remote-debugging-port={port}",
                f"--user-data-dir={self.profile}", f"--user-agent={UA}",
                "--no-first-run", "--no-default-browser-check", "--disable-gpu",
                "--disable-background-timer-throttling", "--window-size=1280,900",
                "about:blank"]
        if headless:
            args.insert(1, "--headless=new")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        ws_url = None
        for _ in range(60):
            time.sleep(0.5)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as r:
                    tabs = json.load(r)
                cand = [t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if cand:
                    ws_url = cand[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
        if not ws_url:
            raise RuntimeError("Could not attach to Chrome DevTools")
        self.ws = WS(ws_url)
        self._id = 0

    def cmd(self, method, params=None, timeout=180):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(method)

    def navigate(self, url, settle=6.0):
        self.cmd("Page.enable")
        self.cmd("Page.navigate", {"url": url})
        time.sleep(settle)

    def eval(self, expr, timeout=180):
        r = self.cmd("Runtime.evaluate",
                     {"expression": expr, "awaitPromise": True,
                      "returnByValue": True, "timeout": timeout * 1000},
                     timeout=timeout + 20)
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"])[:400])
        return r["result"].get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass
