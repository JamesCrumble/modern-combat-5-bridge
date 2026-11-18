"""Entry of the server inside the bridge (documentation/architecture.md): runs server/mc5server.py of the unpacked serverroot with the arguments given by the app.
The server log (stdout and stderr) goes to logcat and to the file MC5_LOGFILE (BridgeGames/<game>/server.log), which the log screen shows."""
import os
import sys
import threading

root = os.environ["MC5_SERVERROOT"]
sys.path.insert(0, os.path.join(root, "server"))


MAX = 5 * 1024 * 1024   # one log file; over it the older half goes (BridgeLog.java does the same with mc5.log)


def trim(path):
    """Keeps the newer half of the log, from the first line start in it."""
    with open(path, "rb") as f:
        f.seek(os.path.getsize(path) // 2)
        rest = f.read()
    nl = rest.find(b"\n")
    with open(path + ".tmp", "wb") as f:
        f.write(rest[nl + 1:] if nl >= 0 else b"")
    os.replace(path + ".tmp", path)


class Tee:
    """Copies a stream to the log file in whole lines: print() writes the text and the newline separately, and the server's threads (stdout
    and stderr) write to the same file, so partial writes would interleave."""
    lock = threading.Lock()

    def __init__(self, stream, path):
        self.stream = stream
        self.path = path
        self.buf = ""

    def write(self, s):
        self.stream.write(s)
        with Tee.lock:
            self.buf += s
            if "\n" not in self.buf:
                return len(s)
            lines, self.buf = self.buf.rsplit("\n", 1)
            try:
                if os.path.isfile(self.path) and os.path.getsize(self.path) > MAX:
                    trim(self.path)
                with open(self.path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(lines + "\n")
            except OSError:
                pass
        return len(s)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


if os.environ.get("MC5_LOGFILE"):
    # BridgeGames/<game>/server.log (BridgeLog.java); stderr too, so that tracebacks are in it
    sys.stdout = Tee(sys.stdout, os.environ["MC5_LOGFILE"])
    sys.stderr = Tee(sys.stderr, os.environ["MC5_LOGFILE"])

import mc5server  # noqa: E402

mc5server.main()
