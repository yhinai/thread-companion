"""Cancellable subprocesses with process-group cleanup and bounded diagnostics."""
import os
import signal
import subprocess
import tempfile
import time


class Cancelled(Exception):
    pass


def terminate(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def execute(args, cwd=None, stop=None, input_text=None, timeout=None):
    # Never propagate a shell-stored sudo password into agent/check subprocesses.
    env = {k: v for k, v in os.environ.items() if k != "SUDO_PASSWORD"}
    # Python verification must not dirty experimental repositories with cache files.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as inp:
        if input_text:
            inp.write(input_text.encode())
        inp.seek(0)
        process = subprocess.Popen(args, cwd=cwd, stdin=inp, stdout=out, stderr=err, env=env, start_new_session=True)
        started = time.monotonic()
        try:
            while process.poll() is None:
                if stop and stop.is_set():
                    raise Cancelled("Stopped by user")
                if timeout and time.monotonic() - started > timeout:
                    raise TimeoutError("Command exceeded its timeout")
                time.sleep(0.08)
        except BaseException:
            terminate(process)
            raise
        out.seek(max(0, out.tell() - 100000))
        err.seek(max(0, err.tell() - 20000))
        return {"exit_code": process.returncode, "stdout": out.read().decode(errors="replace"),
                "stderr": err.read().decode(errors="replace"), "seconds": round(time.monotonic() - started, 2)}
