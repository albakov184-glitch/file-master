import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(not shutil.which("redis-server"), reason="нужен redis-server")
def test_bot_end_to_end(samples, tmp_path):
    redis_port = free_port()
    redis = subprocess.Popen(["redis-server", "--port", str(redis_port), "--save", "", "--appendonly", "no"],
                             stdout=subprocess.DEVNULL)
    try:
        time.sleep(0.5)
        env = {**os.environ, "BOT_TOKEN": "1:TEST", "FAKE_API_PORT": str(free_port()),
               "REDIS_URL": f"redis://127.0.0.1:{redis_port}/0", "DATA_DIR": str(tmp_path / "data"),
               "SAMPLES": json.dumps({k: str(v) for k, v in samples.items()}), "PYTHONPATH": str(ROOT)}
        env["BOT_API_URL"] = f"http://127.0.0.1:{env['FAKE_API_PORT']}"
        proc = subprocess.run([sys.executable, str(ROOT / "tests" / "e2e_flow.py")], env=env, cwd=ROOT,
                              capture_output=True, text=True, timeout=600)
        print(proc.stdout)
        assert proc.returncode == 0, proc.stdout + proc.stderr[-3000:]
    finally:
        redis.terminate()
