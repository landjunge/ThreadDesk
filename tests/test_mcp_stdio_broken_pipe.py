"""Real local stdio peer: the reader on stdout disconnects mid-serve.

Regression test for a real incident (found 2026-11-28 via KiraBridge's
installer readiness probe): when the process reading this server's stdout
closes early (e.g. a readiness check that gave up and disconnected), the
next write() hit a BrokenPipeError that propagated as an uncaught traceback,
crashing the whole stdio server instead of exiting quietly. A disconnected
reader is an ordinary way for this transport to end, not a crash.
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def test_real_stdio_peer_exits_cleanly_when_stdout_reader_disconnects(tmp_path):
    env = {
        **os.environ,
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "THREADDESK_HOME": str(tmp_path),
        "THREADDESK_STORAGE": "json",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "threaddesk.ui.mcp_stdio"],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}) + "\n"
        )
        process.stdin.flush()
        lines = []
        reader = threading.Thread(
            target=lambda: lines.append(process.stdout.readline()), daemon=True
        )
        reader.start()
        reader.join(timeout=10)
        assert not reader.is_alive(), "server never answered initialize"
        response = json.loads(lines[0])
        assert response["result"]["serverInfo"]["name"] == "threaddesk"

        process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        process.stdin.flush()

        # The reader disconnects: close our end of the child's stdout. The
        # next response the child tries to write now hits a closed pipe.
        process.stdout.close()

        process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}) + "\n"
        )
        process.stdin.flush()

        deadline = time.time() + 10
        while process.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        assert process.poll() is not None, "server did not exit after its stdout reader closed"
        assert process.returncode == 0, process.stderr.read()
        stderr = process.stderr.read()
        assert "BrokenPipeError" not in stderr, stderr
        assert "Traceback" not in stderr, stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
