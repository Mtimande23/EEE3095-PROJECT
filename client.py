"""Thin Tkinter client for the STM32 Tic-Tac-Toe server.

The client never decides whether a move is legal. It sends one request at a
time, waits for the server's reply, and redraws the board only from a valid
BOARD reply. Lines starting with "EVT:" are unsolicited events from the board
(the button reset) and are handled separately from replies.

    pip install pyserial
    python client.py [PORT]
"""
import queue
import re
import sys
import threading
import tkinter as tk
from collections import deque
from tkinter import ttk,messagebox

import serial
import serial.tools.list_ports

BAUD = 115200
REPLY_TIMEOUT_MS = 2000
BOARD_RE = re.compile(r"^(?:OK:)?BOARD:([.XO]{9})$")

NACK_TEXT = {
    "OCCUPIED": "That cell is already taken.",
    "RANGE": "That cell does not exist.",
    "NOTURN": "It is not that player's turn.",
    "NOGAME": "No game is in progress. Start a new game.",
    "STATE": "That is not allowed right now.",
    "BADCMD": "The server did not understand the request.",
    "TOOLONG": "The request was too long.",
    "TIMEOUT": "The request arrived incomplete and was discarded.",
    "CHECKSUM": "The request was corrupted (checksum mismatch).",
}


def with_checksum(frame: str) -> str:
    x = 0
    for ch in frame.encode("ascii"):
        x ^= ch
    return f"{frame}*{x:02X}"


class SerialReader(threading.Thread):
    """Reads lines from the port and posts them to a queue for the Tk thread."""

    def __init__(self, ser: serial.Serial, out: queue.Queue):
        super().__init__(daemon=True)
        self.ser = ser
        self.out = out
        self.running = True

    def run(self):
        buf = b""
        while self.running:
            try:
                chunk = self.ser.read(64)
            except (serial.SerialException, OSError, TypeError) as exc:
                if self.running:
                    self.out.put(("error", str(exc)))
                return
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("ascii", errors="replace").strip("\r")
                self.out.put(("line", text))

    def stop(self):
        self.running = False


class App:
    def __init__(self, root: tk.Tk, initial_port: str = ""):
        self.root = root
        self.ser = None
        self.reader = None
        self.rx = queue.Queue()
        self.pending = deque()          # commands awaiting a reply, oldest first
        self.timeout_job = None
        self.game_active = False        # last known from server replies
        self.board = "." * 9

        root.title("Tic-Tac-Toe: STM32 serial game server")
        root.resizable(False, False)
        self._build(initial_port)
        self._refresh_controls()
        root.after(20, self._pump)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- UI --

    def _build(self, initial_port):
        top = ttk.Frame(self.root, padding=8)
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="Port").grid(row=0, column=0)
        self.port_var = tk.StringVar(value=initial_port)
        self.port_box = ttk.Combobox(top, textvariable=self.port_var, width=24)
        self.port_box.grid(row=0, column=1, padx=4)
        ttk.Button(top, text="Refresh", command=self._refresh_ports).grid(row=0, column=2)
        self.conn_btn = ttk.Button(top, text="Connect", command=self._toggle_connect)
        self.conn_btn.grid(row=0, column=3, padx=(8, 0))
        self._refresh_ports()

        grid = ttk.Frame(self.root, padding=8)
        grid.grid(row=1, column=0)
        self.cells = []
        for i in range(9):
            b = tk.Button(grid, text=" ", width=4, height=2, font=("Helvetica", 28, "bold"),
                          command=lambda i=i: self._move(i))
            b.grid(row=i // 3, column=i % 3, padx=2, pady=2)
            self.cells.append(b)

        actions = ttk.Frame(self.root, padding=(8, 0))
        actions.grid(row=2, column=0, sticky="ew")
        self.new_btn = ttk.Button(actions, text="New game", command=lambda: self._send("NEW"))
        self.new_btn.grid(row=0, column=0)
        self.resign_btn = ttk.Button(actions, text="Resign", command=lambda: self._send("RESIGN"))
        self.resign_btn.grid(row=0, column=1, padx=4)
        self.cksum_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(actions, text="Checksum", variable=self.cksum_var).grid(row=0, column=2)

        self.status = tk.StringVar(value="Not connected.")
        ttk.Label(self.root, textvariable=self.status, padding=8, wraplength=320,
                  font=("Helvetica", 11, "bold")).grid(row=3, column=0, sticky="w")

        self.log = tk.Listbox(self.root, height=8, width=48, font=("Courier", 9))
        self.log.grid(row=4, column=0, padx=8, pady=(0, 8))

    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_box["values"] = ports
        if not self.port_var.get() and ports:
            self.port_var.set(ports[0])

    def _refresh_controls(self):
        connected = self.ser is not None
        busy = bool(self.pending)
        self.conn_btn.config(text="Disconnect" if connected else "Connect")
        self.port_box.config(state="disabled" if connected else "normal")
        play = connected and self.game_active and not busy
        for i, b in enumerate(self.cells):
            b.config(text=self.board[i] if self.board[i] != "." else " ",
                     state="normal" if play else "disabled",
                     disabledforeground="#555")
        self.new_btn.config(state="normal" if connected and not self.game_active and not busy else "disabled")
        self.resign_btn.config(state="normal" if play else "disabled")

    def _log(self, text):
        self.log.insert(tk.END, text)
        self.log.see(tk.END)
        if self.log.size() > 200:
            self.log.delete(0)

    def _set_status(self, text):
        self.status.set(text)

    def _turn_text(self):
        x, o = self.board.count("X"), self.board.count("O")
        return "X to move." if x == o else "O to move."

    # -------------------------------------------------------- connection --

    def _toggle_connect(self):
        if self.ser is None:
            self._open()
        elif self.game_active:
            if messagebox.askyesno("Disconnect", "A game is in progress. Resign and disconnect?"):
                self._send("RESIGN")
                self._send("DISCONNECT")
        else:
            self._send("DISCONNECT")

    def _open(self):
        port = self.port_var.get().strip()
        if not port:
            self._set_status("Choose a serial port first.")
            return
        try:
            self.ser = serial.Serial(port, BAUD, timeout=0.05)
        except serial.SerialException as exc:
            self._set_status(f"Could not open {port}: {exc}")
            return
        self.ser.reset_input_buffer()
        self.reader = SerialReader(self.ser, self.rx)
        self.reader.start()
        self._set_status(f"Connecting to {port}...")
        self._send("CONNECT")

    def _close(self, why):
        if self.reader:
            self.reader.stop()
        if self.ser:
            try:
                self.ser.close()
            except serial.SerialException:
                pass
        self.ser = None
        self.reader = None
        self.pending.clear()
        self._cancel_timeout()
        self.game_active = False
        self._set_status(why)
        self._refresh_controls()

    # ----------------------------------------------------------- sending --

    def _send(self, cmd):
        if self.ser is None:
            return
        frame = with_checksum(cmd) if self.cksum_var.get() else cmd
        try:
            self.ser.write(frame.encode("ascii") + b"\n")
        except serial.SerialException as exc:
            self._close(f"Link lost: {exc}")
            return
        self._log(f"> {frame}")
        self.pending.append(cmd)
        self._arm_timeout()
        self._refresh_controls()

    def _move(self, index):
        if not self.pending:
            self._send(f"MOVE:{index}")

    def _arm_timeout(self):
        self._cancel_timeout()
        self.timeout_job = self.root.after(REPLY_TIMEOUT_MS, self._on_timeout)

    def _cancel_timeout(self):
        if self.timeout_job is not None:
            self.root.after_cancel(self.timeout_job)
            self.timeout_job = None

    def _on_timeout(self):
        self.timeout_job = None
        if self.pending:
            cmd = self.pending.popleft()
            self._set_status(f"No reply to {cmd} from the server.")
            if cmd == "CONNECT":
                self._close("The server did not answer. Check the port and the board.")
                return
            if self.pending:
                self._arm_timeout()
            self._refresh_controls()

    # --------------------------------------------------------- receiving --

    def _pump(self):
        try:
            while True:
                kind, payload = self.rx.get_nowait()
                if kind == "error":
                    self._close(f"Link lost: {payload}")
                else:
                    self._on_line(payload)
        except queue.Empty:
            pass
        self.root.after(20, self._pump)

    def _on_line(self, line):
        self._log(f"< {line}")
        if line.startswith("EVT:"):
            self._on_event(line)
            return
        if not self.pending:
            return                      # stray reply: ignore, never redraw from it
        cmd = self.pending.popleft()
        if self.pending:
            self._arm_timeout()
        else:
            self._cancel_timeout()
        self._on_reply(cmd, line)
        self._refresh_controls()

    def _on_event(self, line):
        if line == "EVT:RESET":
            self.game_active = False
            self.board = "." * 9
            self._set_status("The board's button reset the game. Start a new game.")
            self._refresh_controls()

    def _render(self, line):
        m = BOARD_RE.match(line)
        if not m:
            return False
        self.board = m.group(1)
        return True

    def _on_reply(self, cmd, line):
        if line.startswith("NACK:"):
            reason = line[5:]
            if cmd.startswith("MOVE") and reason == "NOGAME":
                self.game_active = False
            if cmd == "STATE" and reason == "NOGAME":
                self.game_active = False
                self.board = "." * 9
                self._set_status("Connected. No game in progress.")
                return
            self._set_status("Rejected: " + NACK_TEXT.get(reason, line))
            return

        if cmd == "CONNECT" and line == "OK":
            self._set_status("Connected.")
            self._send("STATE")          # resync with whatever the board holds
        elif cmd == "NEW" and self._render(line):
            self.game_active = True
            self._set_status("New game. X to move.")
        elif cmd.startswith("MOVE"):
            if self._render(line):
                self._set_status(self._turn_text())
            elif line in ("WIN:X", "WIN:O", "DRAW"):
                self.game_active = False
                self._set_status("Draw!" if line == "DRAW" else f"{line[4]} wins!")
                self._send("STATE")      # fetch the final board from the server
            else:
                self._set_status(f"Unexpected reply: {line}")
        elif cmd == "STATE" and self._render(line):
            if not self.status.get().endswith(("wins!", "Draw!")):
                self.game_active = True
                self._set_status("Connected. Game in progress: " + self._turn_text())
        elif cmd == "RESIGN" and line == "OK:GAMEOVER":
            self.game_active = False
            self._set_status("Game resigned.")
        elif cmd == "DISCONNECT" and line == "OK":
            self._close("Disconnected.")
        else:
            self._set_status(f"Unexpected reply to {cmd}: {line}")

    def _on_close(self):
        if self.ser is not None and not self.game_active:
            try:
                self.ser.write(b"DISCONNECT\n")
            except serial.SerialException:
                pass
        self._close("Closed.")
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root, sys.argv[1] if len(sys.argv) > 1 else "")
    root.mainloop()


if __name__ == "__main__":
    main()
