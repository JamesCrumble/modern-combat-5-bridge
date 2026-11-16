"""Entry of the server inside the bridge (documentation/architecture.md): runs server/mc5server.py of the unpacked serverroot with the arguments given by the app.
The server log goes to logcat (stdout) and to the file MC5_LOGFILE, which the settings screen shows."""
import os
import sys

root = os.environ["MC5_SERVERROOT"]
sys.path.insert(0, os.path.join(root, "server"))


class Tee:
    def __init__(self, stream, path):
        self.stream = stream
        self.path = path

    def write(self, s):
        self.stream.write(s)
        try:
            if os.path.isfile(self.path) and os.path.getsize(self.path) > 512 * 1024:
                os.replace(self.path, self.path + ".1")
            with open(self.path, "a", encoding="utf-8", errors="replace") as f:
                f.write(s)
        except OSError:
            pass
        return len(s)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


if os.environ.get("MC5_LOGFILE"):
    sys.stdout = Tee(sys.stdout, os.environ["MC5_LOGFILE"])

import mc5server  # noqa: E402

mc5server.main()
