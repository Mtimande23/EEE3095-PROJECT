"""Fixtures for the serial game server tests.

Run against the real board:
    python -m pytest tests --port auto          (finds the board's ST-Link port)
    python -m pytest tests --port COM4          (or name the port yourself)
or set GAME_PORT. With no port, the PC simulator in ../sim is built and
started automatically (Linux/macOS, needs a C compiler and make).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import serial

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui"))
import ports  # noqa: E402

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent / "sim"
BAUD = 115200
READ_TIMEOUT_S = 2.0
POLL_S = 0.05


def pytest_addoption(parser):
    parser.addoption("--port", default=os.environ.get("GAME_PORT"),
                     help="serial port of the board, or 'auto' to find it; omit to use the simulator")
    parser.addoption("--baud", type=int, default=BAUD)


class Link:
    """One line out, one line back.

    The port's timeout is set once, when it is opened, and never changed:
    on Windows, changing pyserial's timeout reconfigures the port, which makes
    the USB virtual COM port (e.g. the ST-Link's) drop bytes already in flight.
    Reads are polled and lines assembled here instead.
    """

    def __init__(self, ser: serial.Serial):
        self.ser = ser
        self.buf = b""

    def _pull(self):
        self.buf += self.ser.read(self.ser.in_waiting or 1)   # waits <= POLL_S

    def send_raw(self, data: bytes):
        self.ser.write(data)
        self.ser.flush()

    def read_line(self, timeout=READ_TIMEOUT_S) -> str:
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buf:
            assert time.monotonic() < deadline, \
                f"no complete reply within {timeout}s (got {self.buf!r})"
            self._pull()
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode("ascii").rstrip("\r")

    def cmd(self, text: str) -> str:
        self.send_raw(text.encode("ascii") + b"\n")
        return self.read_line()

    def drain(self, quiet_s=0.2):
        """Discard everything until the link has been silent for quiet_s."""
        self.buf = b""
        last = time.monotonic()
        while time.monotonic() - last < quiet_s:
            if self.ser.read(self.ser.in_waiting or 1):
                last = time.monotonic()

    def expect_silence(self, seconds=0.3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self.buf:
            self._pull()
        assert self.buf == b"", f"unexpected extra output {self.buf!r}"


@pytest.fixture(scope="session")
def port(request, tmp_path_factory):
    explicit = request.config.getoption("--port")
    if explicit and explicit.lower() == "auto":
        explicit = ports.find_board()
        if explicit is None:
            pytest.exit("--port auto: no board found. Plug it in, or give the port, "
                        "e.g. --port COM4")
        print(f"\nusing the board on {explicit}")
    if explicit:
        yield explicit
        return

    if shutil.which("make") is None:
        pytest.exit("no --port given and 'make' is not available to build the simulator")

    build_dir = tmp_path_factory.mktemp("sim")
    subprocess.run(["make", "-s", f"OUT={build_dir}"], cwd=SIM_DIR, check=True)
    link = Path(tempfile.mkdtemp()) / "ttyGAME"
    proc = subprocess.Popen([str(build_dir / "gamesim"), "--link", str(link)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True)
    first = proc.stdout.readline()
    assert first.startswith("PORT "), f"simulator did not start: {first!r}"
    yield str(link)
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture(scope="session")
def link_session(port, request):
    ser = serial.Serial(port, request.config.getoption("--baud"), timeout=POLL_S)
    yield Link(ser)
    ser.close()


@pytest.fixture
def link(link_session):
    """A link to a server in IDLE with a fresh session, whatever the last test left."""
    link_session.drain()
    link_session.send_raw(b"\n")          # terminate any half-sent frame
    link_session.cmd("RESIGN")            # IN_PROGRESS -> GAME_OVER (else NACK)
    link_session.cmd("DISCONNECT")        # GAME_OVER -> IDLE (IDLE stays IDLE)
    assert link_session.cmd("CONNECT") == "OK"
    link_session.drain()
    return link_session


def checksum(frame: str) -> str:
    """Append the optional XOR checksum suffix."""
    x = 0
    for ch in frame.encode("ascii"):
        x ^= ch
    return f"{frame}*{x:02X}"
