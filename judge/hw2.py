#!/usr/bin/env python3
"""Public HW02 functional tests. Python standard library only; no solution code."""

import argparse
import json
import os
from pathlib import Path
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CASES = []
TIMEOUT = 5


def case(name, points):
    def register(fn):
        CASES.append((name, points, fn))
        return fn
    return register


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def stop_group(process):
    # Children can keep stdout open even after an incorrect launcher exits.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


class Harness:
    def __init__(self, binary, directory, compiler):
        self.binary = binary
        self.directory = Path(directory)
        self.probe = self.directory / "probe"
        subprocess.run(
            [*shlex.split(compiler), "-std=c11", "-D_POSIX_C_SOURCE=200809L",
             "-Wall", "-Wextra", "-Werror", str(HERE / "probe.c"),
             "-o", str(self.probe)], check=True, timeout=30,
        )

    def start(self, command, **kwargs):
        return subprocess.Popen(
            [str(self.binary), *command], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True, **kwargs,
        )

    def run(self, command, data=None, **kwargs):
        p = self.start(command, **kwargs)
        try:
            out, err = p.communicate(data, timeout=TIMEOUT)
            return p.returncode, out, err, p.pid
        except subprocess.TimeoutExpired as exc:
            raise AssertionError(f"execution exceeded {TIMEOUT}s") from exc
        finally:
            stop_group(p)
            for stream in (p.stdin, p.stdout, p.stderr):
                stream.close()

    def probe_run(self, mode, *args, **kwargs):
        return self.run(["run", "--", str(self.probe), mode, *args], **kwargs)


@case("cli_usage", 5)
def cli_usage(h):
    for args in ([], ["run"], ["run", "--"], ["other", "--", "true"],
                 ["run", "true"]):
        status, out, err, _ = h.run(args)
        require(status == 2 and out == b"" and bool(err),
                f"invalid CLI {args!r}: expected status 2, stderr only")


@case("absolute_execution", 5)
def absolute_execution(h):
    status, out, err, _ = h.run(["run", "--", "/bin/echo", "Hello OS"])
    require((status, out, err) == (0, b"Hello OS\n", b""),
            "absolute command: expected exact output and status 0")


@case("path_lookup", 5)
def path_lookup(h):
    bindir = h.directory / "bin"
    bindir.mkdir()
    shutil.copy2(h.probe, bindir / "langar-test-probe")
    env = dict(os.environ, PATH=str(bindir))
    status, out, err, _ = h.run(
        ["run", "--", "langar-test-probe", "args", "found"], env=env)
    require((status, out, err) == (0, b"5:found\n", b""),
            "program name must be resolved through the supplied PATH")


@case("argument_boundaries", 10)
def argument_boundaries(h):
    args = ["one argument with spaces", "", "a;b", "*", "$(echo wrong)",
            "--flag", "line1\nline2", "سلام"]
    expected = b"".join(str(len(a.encode())).encode() + b":" + a.encode() + b"\n"
                        for a in args)
    status, out, err, _ = h.probe_run("args", *args)
    require((status, out, err) == (0, expected, b""),
            "arguments must retain boundaries, empty values, and literal data")


@case("stdin_inheritance", 5)
def stdin_inheritance(h):
    data = b"first line\nsecond line\x00end\n"
    status, out, err, _ = h.probe_run("stdin", data=data)
    require((status, out, err) == (0, data, b""), "stdin must reach the command")


@case("stdout_stderr", 5)
def stdout_stderr(h):
    status, out, err, _ = h.probe_run("streams")
    require((status, out, err) == (0, b"out\n", b"err\n"),
            "stdout and stderr must remain separate, without launcher banners")


@case("working_directory", 5)
def working_directory(h):
    cwd = h.directory / "working directory"
    cwd.mkdir()
    status, out, err, _ = h.probe_run("cwd", cwd=cwd)
    require(status == 0 and err == b"" and
            Path(os.fsdecode(out.rstrip(b"\n"))).resolve() == cwd.resolve(),
            "command must inherit the caller's working directory")


@case("environment", 5)
def environment(h):
    env = dict(os.environ, LANGAR_TEST_VALUE="inherited value")
    status, out, err, _ = h.probe_run("env", env=env)
    require((status, out, err) == (0, b"inherited value\n", b""),
            "command must inherit environment variables")


@case("direct_child", 15)
def direct_child(h):
    status, out, err, launcher_pid = h.probe_run("identity")
    require(status == 0 and err == b"", "identity probe must execute successfully")
    try:
        pid, ppid = map(int, out.split())
    except ValueError as exc:
        raise AssertionError("identity probe output was changed") from exc
    require(pid != launcher_pid and ppid == launcher_pid,
            "command must be a direct child; replacing the launcher is incorrect")


@case("parent_waits", 10)
def parent_waits(h):
    p = h.start(["run", "--", str(h.probe), "wait"])
    try:
        deadline = time.monotonic() + TIMEOUT
        data = b""
        with selectors.DefaultSelector() as selector:
            selector.register(p.stdout, selectors.EVENT_READ)
            while b"\n" not in data:
                remaining = deadline - time.monotonic()
                require(remaining > 0, "probe did not report readiness in time")
                require(selector.select(remaining), "probe readiness timed out")
                block = os.read(p.stdout.fileno(), 4096)
                require(bool(block), "command did not reach the readiness checkpoint")
                data += block
                require(len(data) <= 4096, "unexpected output before readiness")
        require(data == b"READY\n", "launcher added output before probe readiness")
        try:
            p.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass
        else:
            raise AssertionError("launcher exited while its child was awaiting input")
        out, err = p.communicate(b"x", timeout=TIMEOUT)
        require(p.returncode == 0 and out == b"" and err == b"",
                "launcher must complete successfully after the child is released")
    except subprocess.TimeoutExpired as exc:
        raise AssertionError("launcher did not finish after releasing its child") from exc
    finally:
        stop_group(p)
        for stream in (p.stdin, p.stdout, p.stderr):
            stream.close()


@case("normal_exit_status", 10)
def normal_exit_status(h):
    for value in (0, 7, 42, 255):
        status, out, err, _ = h.probe_run("exit", str(value))
        require((status, out, err) == (value, b"", b""),
                f"expected child exit status {value}, got {status}")


@case("signal_exit_status", 5)
def signal_exit_status(h):
    status, out, err, _ = h.probe_run("signal")
    require(status == 128 + signal.SIGTERM and out == b"" and err == b"",
            "SIGTERM termination must produce status 143")


@case("command_not_found", 5)
def command_not_found(h):
    for command in (str(h.directory / "missing"), "langar-no-such-command"):
        status, out, err, _ = h.run(["run", "--", command],
                                  env=dict(os.environ, PATH=str(h.directory)))
        require(status == 127 and out == b"" and bool(err),
                "missing command: expected status 127 and a stderr diagnostic")


@case("permission_denied", 5)
def permission_denied(h):
    path = h.directory / "not-executable"
    path.write_text("not executable\n")
    path.chmod(0o644)
    status, out, err, _ = h.run(["run", "--", str(path)])
    require(status == 126 and out == b"" and bool(err),
            "non-executable file: expected status 126 and stderr")


@case("not_a_directory", 5)
def not_a_directory(h):
    status, out, err, _ = h.run(["run", "--", str(h.probe / "missing")])
    require(status == 127 and out == b"" and bool(err),
            "ENOTDIR: expected status 127 and stderr")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path,
                        default=ROOT / "q2/langar")
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"))
    parser.add_argument("--json", type=Path, help="also save a machine-readable result")
    args = parser.parse_args()
    binary = args.binary.resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        parser.error(f"executable not found: {binary}; build q2 first")
    if os.name != "posix":
        parser.error("a Linux environment is required")
    results = []
    try:
        with tempfile.TemporaryDirectory(prefix="langar-tests-") as directory:
            h = Harness(binary, directory, args.cc)
            for name, points, fn in CASES:
                error = None
                try:
                    fn(h)
                except (AssertionError, OSError, subprocess.SubprocessError) as exc:
                    error = str(exc)
                earned = points if error is None else 0
                results.append(dict(id=name, points=points, earned=earned,
                                    passed=error is None, error=error))
                print(f"{'PASS' if error is None else 'FAIL'} {name}: {earned}/{points}")
                if error:
                    print(f"  {error}")
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Test setup failed: {exc}", file=sys.stderr)
        return 2
    report = dict(assignment="hw02-q2", score=sum(r["earned"] for r in results),
                  total=sum(r["points"] for r in results), results=results)
    print(f"Functional score: {report['score']}/{report['total']}")
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
