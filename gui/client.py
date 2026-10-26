"""Thin Tkinter client for the STM32 Tic-Tac-Toe server.

The client never decides whether a move is legal. It sends one request at a
time, waits for the server's reply, and redraws the board only from a valid
BOARD reply. Lines starting with "EVT:" are unsolicited events from the board
(the button reset) and are handled separately from replies.

Everything else here is presentation: themes, player names, the scoreboard
and highlighting the winning line all work from what the server reported.

    pip install pyserial
    python client.py [PORT]
"""
import queue
import re
import sys
import threading
import tkinter as tk
from collections import deque
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import serial
import serial.tools.list_ports

import ai

BAUD = 115200
REPLY_TIMEOUT_MS = 2000
AI_DELAY_MS = 500          # a short pause so the AI's move is visible
BOARD_RE = re.compile(r"^(?:OK:)?BOARD:([.XO]{9})$")
EMPTY = "." * 9
WIN_LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8),
             (0, 3, 6), (1, 4, 7), (2, 5, 8),
             (0, 4, 8), (2, 4, 6)]

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

# ------------------------------------------------------------------ themes --

THEMES = {
    "Classic": {
        "title": "Tic-Tac-Toe",
        "subtitle": "STM32 serial game server",
        "names": ("Player X", "Player O"),
        "tags": ("goes first", "goes second"),
        "light": dict(bg="#eef1f6", panel="#ffffff", cell="#ffffff", hover="#dde6f5",
                      win="#cfe9d4", fg="#1b2330", muted="#5c6676", x="#1565c0",
                      o="#c62828", accent="#1565c0", ok="#2e7d32", err="#c62828",
                      border="#c3ccda", button="#1565c0", button_fg="#ffffff"),
        "dark": dict(bg="#171a21", panel="#212630", cell="#262c38", hover="#333b4a",
                     win="#24503a", fg="#eceff4", muted="#95a0b2", x="#4fa3f7",
                     o="#ff6b6b", accent="#4fa3f7", ok="#5ec46b", err="#ff6b6b",
                     border="#333b4a", button="#2f6fd0", button_fg="#ffffff"),
    },
    "Zoro vs King": {
        "title": "Zoro vs King",
        "subtitle": "Showdown on Onigashima",
        "names": ("Zoro", "King"),
        "tags": ("Three-Sword Style", "Lunarian flames"),
        "light": dict(bg="#f0f2f5", panel="#ffffff", cell="#ffffff", hover="#e3e8ef",
                      win="#cfe9d4", fg="#1b2026", muted="#5d6672", x="#1e8e4a",
                      o="#e8601c", accent="#1e8e4a", ok="#1e8e4a", err="#d6391f",
                      border="#c9cfd8", button="#1e8e4a", button_fg="#ffffff"),
        "dark": dict(bg="#15181c", panel="#1f242a", cell="#252b32", hover="#323a43",
                     win="#1f4a31", fg="#eef1f5", muted="#949caa", x="#3ad17a",
                     o="#ff9340", accent="#3ad17a", ok="#3ad17a", err="#ff7a6a",
                     border="#333b45", button="#1e8e4a", button_fg="#ffffff"),
    },
}


def with_checksum(frame: str) -> str:
    x = 0
    for ch in frame.encode("ascii"):
        x ^= ch
    return f"{frame}*{x:02X}"


def winning_line(board: str):
    for line in WIN_LINES:
        a, b, c = (board[i] for i in line)
        if a != "." and a == b == c:
            return line
    return None


def pick_font(root, *families):
    available = set(tkfont.families(root))
    for f in families:
        if f in available:
            return f
    return "TkDefaultFont"


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
        self.board = EMPTY
        self.win_cells = ()
        self.hover = None
        self.score = {"X": 0, "O": 0, "D": 0}
        self.status_kind = "muted"
        self.ai_job = None

        self.opponent = tk.StringVar(value="Friend")      # "Friend" or "AI"
        self.level = tk.StringVar(value="Hard")
        self.human_side = tk.StringVar(value="X")

        self.theme_name = tk.StringVar(value="Zoro vs King")
        self.mode = tk.StringVar(value="dark")
        self.names = {"X": tk.StringVar(), "O": tk.StringVar()}
        self._set_default_names()
        self.committed_names = {p: v.get() for p, v in self.names.items()}

        sans = pick_font(root, "Segoe UI", "Helvetica Neue", "Helvetica", "DejaVu Sans")
        mono = pick_font(root, "Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono")
        self.f_title = tkfont.Font(family=sans, size=22, weight="bold")
        self.f_sub = tkfont.Font(family=sans, size=11, slant="italic")
        self.f_body = tkfont.Font(family=sans, size=11)
        self.f_bold = tkfont.Font(family=sans, size=11, weight="bold")
        self.f_sym = tkfont.Font(family=sans, size=26, weight="bold")
        self.f_score = tkfont.Font(family=sans, size=20, weight="bold")
        self.f_cell = tkfont.Font(family=sans, size=40, weight="bold")
        self.f_status = tkfont.Font(family=sans, size=13, weight="bold")
        self.f_mono = tkfont.Font(family=mono, size=9)

        root.title("Tic-Tac-Toe: STM32 serial game server")
        root.minsize(460, 0)
        self.style = ttk.Style(root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        self._build(initial_port)
        self._apply_theme()
        self._set_status("Not connected. Choose a port and press Connect.", "muted")
        self._refresh_controls()
        root.after(20, self._pump)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------- build --

    @property
    def pal(self):
        return THEMES[self.theme_name.get()][self.mode.get()]

    def _set_default_names(self):
        x, o = THEMES[self.theme_name.get()]["names"]
        self.names["X"].set(x)
        self.names["O"].set(o)

    def name(self, player):
        return self.names[player].get().strip() or f"Player {player}"

    def _build(self, initial_port):
        r = self.root
        r.columnconfigure(0, weight=1)

        # Header: title, subtitle, theme and light/dark.
        self.header = tk.Frame(r, padx=16, pady=12)
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.columnconfigure(0, weight=1)
        self.title_lbl = tk.Label(self.header, font=self.f_title, anchor="w")
        self.title_lbl.grid(row=0, column=0, sticky="w")
        self.sub_lbl = tk.Label(self.header, font=self.f_sub, anchor="w")
        self.sub_lbl.grid(row=1, column=0, sticky="w")
        right = tk.Frame(self.header)
        right.grid(row=0, column=1, rowspan=2, sticky="e")
        self.theme_box = ttk.Combobox(right, textvariable=self.theme_name, state="readonly",
                                      values=list(THEMES), width=13, font=self.f_body)
        self.theme_box.grid(row=0, column=0, padx=(0, 6))
        self.theme_box.bind("<<ComboboxSelected>>", lambda e: self._on_theme_change())
        self.mode_btn = tk.Button(right, command=self._toggle_mode, font=self.f_body,
                                  relief="flat", padx=10, cursor="hand2")
        self.mode_btn.grid(row=0, column=1)
        self.header_right = right

        # Connection bar.
        self.conn = tk.Frame(r, padx=16, pady=6)
        self.conn.grid(row=1, column=0, sticky="ew")
        self.port_lbl = tk.Label(self.conn, text="Port", font=self.f_bold)
        self.port_lbl.grid(row=0, column=0)
        self.port_var = tk.StringVar(value=initial_port)
        self.port_box = ttk.Combobox(self.conn, textvariable=self.port_var, width=18,
                                     font=self.f_body)
        self.port_box.grid(row=0, column=1, padx=6)
        self.refresh_btn = tk.Button(self.conn, text="Refresh", command=self._refresh_ports,
                                     font=self.f_body, relief="flat", padx=10, cursor="hand2")
        self.refresh_btn.grid(row=0, column=2)
        self.conn_btn = tk.Button(self.conn, command=self._toggle_connect, font=self.f_bold,
                                  relief="flat", padx=14, cursor="hand2")
        self.conn_btn.grid(row=0, column=3, padx=(8, 0))
        self.dot = tk.Label(self.conn, text="●", font=self.f_bold)
        self.dot.grid(row=0, column=4, padx=(8, 0))
        self._refresh_ports()

        # Players and score.
        self.players = tk.Frame(r, padx=16, pady=6)
        self.players.grid(row=2, column=0, sticky="ew")
        self.players.columnconfigure((0, 2), weight=1)
        self.card = {}
        for col, p in ((0, "X"), (2, "O")):
            card = tk.Frame(self.players, padx=10, pady=8, highlightthickness=2)
            card.grid(row=0, column=col, sticky="nsew")
            sym = tk.Label(card, text=p, font=self.f_sym, width=2)
            sym.grid(row=0, column=0, rowspan=2)
            entry = tk.Entry(card, textvariable=self.names[p], font=self.f_bold, width=12,
                             relief="flat", highlightthickness=1)
            entry.grid(row=0, column=1, sticky="w")
            entry.bind("<Return>", lambda e: self._commit_names())
            entry.bind("<FocusOut>", lambda e: self._commit_names())
            tag = tk.Label(card, font=self.f_sub, anchor="w")
            tag.grid(row=1, column=1, sticky="w")
            score = tk.Label(card, text="0", font=self.f_score, width=3)
            score.grid(row=0, column=2, rowspan=2, padx=(6, 0))
            self.card[p] = dict(frame=card, sym=sym, entry=entry, tag=tag, score=score)
        mid = tk.Frame(self.players, padx=8)
        mid.grid(row=0, column=1)
        self.draw_lbl = tk.Label(mid, text="Draws", font=self.f_body)
        self.draw_lbl.grid(row=0, column=0)
        self.draw_score = tk.Label(mid, text="0", font=self.f_score)
        self.draw_score.grid(row=1, column=0)
        self.reset_score_btn = tk.Button(mid, text="Reset score", command=self._reset_score,
                                         font=self.f_body, relief="flat", padx=6,
                                         cursor="hand2")
        self.reset_score_btn.grid(row=2, column=0, pady=(2, 0))
        self.mid = mid

        # Game mode: against a friend or the AI.
        self.modebar = tk.Frame(r, padx=16, pady=4)
        self.modebar.grid(row=3, column=0, sticky="ew")
        self.mode_lbls = []
        lbl = tk.Label(self.modebar, text="Opponent", font=self.f_bold)
        lbl.grid(row=0, column=0, padx=(0, 6))
        self.mode_lbls.append(lbl)
        self.opp_radios = []
        for col, val in ((1, "Friend"), (2, "AI")):
            rb = tk.Radiobutton(self.modebar, text=val, value=val, variable=self.opponent,
                                font=self.f_body, command=self._on_mode_change,
                                indicatoron=False, relief="flat", padx=12, pady=2,
                                cursor="hand2")
            rb.grid(row=0, column=col, padx=2)
            self.opp_radios.append(rb)
        lbl = tk.Label(self.modebar, text="Level", font=self.f_bold)
        lbl.grid(row=0, column=3, padx=(14, 6))
        self.mode_lbls.append(lbl)
        self.level_box = ttk.Combobox(self.modebar, textvariable=self.level, state="readonly",
                                      values=["Easy", "Medium", "Hard"], width=8,
                                      font=self.f_body)
        self.level_box.grid(row=0, column=4)
        self.level_box.bind("<<ComboboxSelected>>", lambda e: self._on_mode_change())
        lbl = tk.Label(self.modebar, text="You play", font=self.f_bold)
        lbl.grid(row=0, column=5, padx=(14, 6))
        self.mode_lbls.append(lbl)
        self.side_box = ttk.Combobox(self.modebar, textvariable=self.human_side,
                                     state="readonly", values=["X", "O"], width=3,
                                     font=self.f_body)
        self.side_box.grid(row=0, column=6)
        self.side_box.bind("<<ComboboxSelected>>", lambda e: self._on_mode_change())

        # Board.
        self.grid_frame = tk.Frame(r, padx=16, pady=10)
        self.grid_frame.grid(row=4, column=0)
        self.cells = []
        for i in range(9):
            c = tk.Label(self.grid_frame, text=" ", width=3, height=1, font=self.f_cell,
                         highlightthickness=2, cursor="hand2")
            c.grid(row=i // 3, column=i % 3, padx=4, pady=4, ipadx=6, ipady=4)
            c.bind("<Button-1>", lambda e, i=i: self._move(i))
            c.bind("<Enter>", lambda e, i=i: self._set_hover(i))
            c.bind("<Leave>", lambda e: self._set_hover(None))
            self.cells.append(c)

        # Actions.
        self.actions = tk.Frame(r, padx=16)
        self.actions.grid(row=5, column=0, sticky="ew")
        self.new_btn = tk.Button(self.actions, text="New game", font=self.f_bold,
                                 command=lambda: self._send("NEW"), relief="flat", padx=14,
                                 cursor="hand2")
        self.new_btn.grid(row=0, column=0)
        self.resign_btn = tk.Button(self.actions, text="Resign", font=self.f_body,
                                    command=self._resign, relief="flat", padx=12,
                                    cursor="hand2")
        self.resign_btn.grid(row=0, column=1, padx=6)
        self.cksum_var = tk.BooleanVar(value=False)
        self.cksum_chk = tk.Checkbutton(self.actions, text="Checksum", variable=self.cksum_var,
                                        font=self.f_body)
        self.cksum_chk.grid(row=0, column=2, padx=6)

        # Status.
        self.status = tk.StringVar()
        self.status_lbl = tk.Label(r, textvariable=self.status, font=self.f_status,
                                   anchor="w", justify="left", padx=16, pady=10,
                                   wraplength=440)
        self.status_lbl.grid(row=6, column=0, sticky="ew")

        # Protocol log: every frame sent (>) and received (<), always visible.
        self.log_lbl = tk.Label(r, text="Protocol log", font=self.f_bold, anchor="w", padx=16)
        self.log_lbl.grid(row=7, column=0, sticky="ew")
        self.log = tk.Listbox(r, height=8, font=self.f_mono, relief="flat",
                              highlightthickness=1)
        self.log.grid(row=8, column=0, padx=16, pady=(2, 12), sticky="ew")

    def _all_frames(self):
        return [self.root, self.header, self.header_right, self.conn, self.players,
                self.mid, self.modebar, self.grid_frame, self.actions]

    # ------------------------------------------------------------- theme --

    def _apply_theme(self):
        p = self.pal
        t = THEMES[self.theme_name.get()]
        for f in self._all_frames():
            f.configure(bg=p["bg"])
        for w in (self.title_lbl, self.sub_lbl, self.port_lbl, self.draw_lbl, self.draw_score,
                  self.status_lbl):
            w.configure(bg=p["bg"], fg=p["fg"])
        self.title_lbl.configure(text=t["title"], fg=p["accent"])
        self.sub_lbl.configure(text=t["subtitle"], fg=p["muted"])
        self.draw_lbl.configure(fg=p["muted"])

        flat = dict(bg=p["panel"], fg=p["fg"], activebackground=p["hover"],
                    activeforeground=p["fg"], highlightthickness=0, bd=0)
        for b in (self.refresh_btn, self.resign_btn, self.reset_score_btn):
            b.configure(**flat)
        self.mode_btn.configure(**flat, text="☀  Light" if self.mode.get() == "dark"
                                else "☾  Dark")
        strong = dict(bg=p["button"], fg=p["button_fg"], activebackground=p["accent"],
                      activeforeground=p["button_fg"], highlightthickness=0, bd=0,
                      disabledforeground=p["muted"])
        if self.game_active and self.status_kind == "fg":
            self.status.set(self._turn_text())
        self.conn_btn.configure(**strong)
        self.new_btn.configure(**strong)
        for lbl in self.mode_lbls:
            lbl.configure(bg=p["bg"], fg=p["fg"])
        for rb in self.opp_radios:
            rb.configure(bg=p["panel"], fg=p["fg"], selectcolor=p["button"],
                         activebackground=p["hover"], activeforeground=p["fg"],
                         highlightthickness=0, bd=0)
        self.log_lbl.configure(bg=p["bg"], fg=p["muted"])
        for c in (self.cksum_chk,):
            c.configure(bg=p["bg"], fg=p["fg"], activebackground=p["bg"],
                        activeforeground=p["fg"], selectcolor=p["panel"], highlightthickness=0)

        for pl, card in self.card.items():
            card["frame"].configure(bg=p["panel"], highlightbackground=p["border"])
            card["sym"].configure(bg=p["panel"], fg=p[pl.lower()])
            card["entry"].configure(bg=p["panel"], fg=p[pl.lower()], insertbackground=p["fg"],
                                    highlightbackground=p["border"],
                                    highlightcolor=p["accent"],
                                    disabledbackground=p["panel"],
                                    disabledforeground=p[pl.lower()])
            tag = t["tags"][0 if pl == "X" else 1]
            if self.ai_player() == pl:
                tag = f"AI \u00b7 {self.level.get()}"
            card["tag"].configure(bg=p["panel"], fg=p["muted"], text=tag)
            card["score"].configure(bg=p["panel"], fg=p[pl.lower()])

        self.log.configure(bg=p["panel"], fg=p["fg"], highlightbackground=p["border"],
                           selectbackground=p["hover"], selectforeground=p["fg"])

        self.style.configure("TCombobox", fieldbackground=p["panel"], background=p["panel"],
                             foreground=p["fg"], arrowcolor=p["fg"], bordercolor=p["border"],
                             lightcolor=p["panel"], darkcolor=p["panel"])
        self.style.map("TCombobox", fieldbackground=[("readonly", p["panel"]),
                                                     ("disabled", p["bg"])],
                       foreground=[("readonly", p["fg"]), ("disabled", p["muted"])])
        self.root.option_add("*TCombobox*Listbox.background", p["panel"])
        self.root.option_add("*TCombobox*Listbox.foreground", p["fg"])

        self._set_status(self.status.get(), self.status_kind)
        self._refresh_controls()

    def _on_theme_change(self):
        # Swap in the theme's default names only if the user kept the old defaults.
        old_defaults = {n for t in THEMES.values() for n in t["names"]}
        if not self.game_active and all(v.get().strip() in old_defaults
                                        for v in self.names.values()):
            self._set_default_names()
            self._commit_names()
        self._apply_theme()

    def _toggle_mode(self):
        self.mode.set("light" if self.mode.get() == "dark" else "dark")
        self._apply_theme()

    # --------------------------------------------------------------- AI --

    def ai_player(self):
        """'X' or 'O' when playing the AI, else None."""
        if self.opponent.get() != "AI":
            return None
        return ai.other(self.human_side.get())

    def _on_mode_change(self):
        self._reset_score()              # a different match-up, a fresh score
        self._apply_theme()

    def _maybe_ai_move(self):
        """If it is the AI's turn, play its move after a short pause."""
        me = self.ai_player()
        if not (self.game_active and me and self._turn() == me):
            return
        self._set_status(f"{self.name(me)} is thinking...", "muted")
        self._cancel_ai()
        self.ai_job = self.root.after(AI_DELAY_MS, self._ai_move)
        self._refresh_controls()

    def _ai_move(self):
        self.ai_job = None
        me = self.ai_player()
        if not (self.ser and self.game_active and me and self._turn() == me):
            return
        index = ai.pick_move(self.board, me, self.level.get().lower())
        # Sent like any player's move, naming the player, so the board
        # validates turn, range and occupancy for the AI too.
        self._send(f"MOVE:{me}:{index}")

    def _cancel_ai(self):
        if self.ai_job is not None:
            self.root.after_cancel(self.ai_job)
            self.ai_job = None

    # ------------------------------------------------------- names, score --

    def _commit_names(self):
        now = {p: self.name(p) for p in self.names}
        if now != self.committed_names:
            self.committed_names = now
            self._reset_score()          # new players, new score
        self._refresh_controls()

    def _reset_score(self):
        self.score = {"X": 0, "O": 0, "D": 0}
        self._show_score()

    def _show_score(self):
        self.card["X"]["score"].configure(text=str(self.score["X"]))
        self.card["O"]["score"].configure(text=str(self.score["O"]))
        self.draw_score.configure(text=str(self.score["D"]))

    # ---------------------------------------------------------- refresh ---

    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_box["values"] = ports
        if not self.port_var.get() and ports:
            self.port_var.set(ports[0])

    def _turn(self):
        x, o = self.board.count("X"), self.board.count("O")
        return "X" if x == o else "O"

    def _refresh_controls(self):
        p = self.pal
        connected = self.ser is not None
        busy = bool(self.pending)
        ai_turn = self.ai_player() == self._turn() or self.ai_job is not None
        play = connected and self.game_active and not busy and not ai_turn
        self.conn_btn.config(text="Disconnect" if connected else "Connect")
        self.port_box.config(state="disabled" if connected else "normal")
        self.dot.config(bg=p["bg"], fg=p["ok"] if connected else p["muted"])

        for i, c in enumerate(self.cells):
            mark = self.board[i]
            bg = p["cell"]
            if i in self.win_cells:
                bg = p["win"]
            elif play and self.hover == i and mark == ".":
                bg = p["hover"]
            c.config(text=mark if mark != "." else " ",
                     bg=bg, fg=p["x"] if mark == "X" else p["o"],
                     highlightbackground=p["border"], highlightcolor=p["border"],
                     cursor="hand2" if play else "arrow")

        turn = self._turn() if self.game_active else None
        for pl, card in self.card.items():
            card["frame"].configure(highlightbackground=p[pl.lower()] if pl == turn
                                    else p["border"])
            card["entry"].configure(state="disabled" if self.game_active else "normal")

        can_new = connected and not self.game_active and not busy
        self.new_btn.config(state="normal" if can_new else "disabled",
                            bg=p["button"] if can_new else p["panel"])
        self.conn_btn.config(bg=p["button"] if not busy else p["panel"])
        self.resign_btn.config(state="normal" if play else "disabled")
        locked = "disabled" if self.game_active else "normal"
        for rb in self.opp_radios:
            rb.config(state=locked)
        ai_on = self.opponent.get() == "AI" and not self.game_active
        self.level_box.config(state="readonly" if ai_on else "disabled")
        self.side_box.config(state="readonly" if ai_on else "disabled")

    def _set_hover(self, i):
        self.hover = i
        self._refresh_controls()

    def _log(self, text):
        self.log.insert(tk.END, text)
        self.log.see(tk.END)
        if self.log.size() > 200:
            self.log.delete(0)

    def _set_status(self, text, kind="fg"):
        self.status_kind = kind
        self.status.set(text)
        self.status_lbl.configure(fg=self.pal.get(kind, self.pal["fg"]), bg=self.pal["bg"])

    def _turn_text(self):
        t = self._turn()
        return f"{self.name(t)} to move ({t})."

    # -------------------------------------------------------- connection --

    def _toggle_connect(self):
        if self.ser is None:
            self._open()
        elif self.game_active:
            if messagebox.askyesno("Disconnect", "A game is in progress. Resign and disconnect?"):
                self._resign()
                self._send("DISCONNECT")
        else:
            self._send("DISCONNECT")

    def _open(self):
        port = self.port_var.get().strip()
        if not port:
            self._set_status("Choose a serial port first.", "err")
            return
        try:
            self.ser = serial.Serial(port, BAUD, timeout=0.05)
        except serial.SerialException as exc:
            self._set_status(f"Could not open {port}: {exc}", "err")
            return
        self.ser.reset_input_buffer()
        self.reader = SerialReader(self.ser, self.rx)
        self.reader.start()
        self._set_status(f"Connecting to {port}...", "muted")
        self._send("CONNECT")

    def _close(self, why, kind="muted"):
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
        self._cancel_ai()
        self.game_active = False
        self._set_status(why, kind)
        self._refresh_controls()

    # ----------------------------------------------------------- sending --

    def _send(self, cmd):
        if self.ser is None:
            return
        frame = with_checksum(cmd) if self.cksum_var.get() else cmd
        try:
            self.ser.write(frame.encode("ascii") + b"\n")
        except serial.SerialException as exc:
            self._close(f"Link lost: {exc}", "err")
            return
        self._log(f"> {frame}")
        self.pending.append(cmd)
        self._arm_timeout()
        self._refresh_controls()

    def _move(self, index):
        if (self.ser is not None and self.game_active and not self.pending
                and self.ai_job is None and self._turn() != self.ai_player()):
            self._send(f"MOVE:{index}")

    def _resign(self):
        self._send("RESIGN")

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
            self._set_status(f"No reply to {cmd} from the server.", "err")
            if cmd == "CONNECT":
                self._close("The server did not answer. Check the port and the board.", "err")
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
                    self._close(f"Link lost: {payload}", "err")
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
            self._cancel_ai()
            self.game_active = False
            self.board = EMPTY
            self.win_cells = ()
            self._set_status("The board's button reset the game. Start a new game.", "muted")
            self._refresh_controls()

    def _render(self, line):
        m = BOARD_RE.match(line)
        if not m:
            return False
        self.board = m.group(1)
        return True

    def _game_over(self, text, winner):
        self.game_active = False
        self.score[winner] += 1
        self._show_score()
        self._set_status(text, "ok")

    def _on_reply(self, cmd, line):
        if line.startswith("NACK:"):
            reason = line[5:]
            if cmd.startswith("MOVE") and reason == "NOGAME":
                self.game_active = False
            if cmd == "STATE" and reason == "NOGAME":
                self.game_active = False
                self.board = EMPTY
                self.win_cells = ()
                self._set_status("Connected. Press New game to start.", "ok")
                return
            self._set_status("Rejected: " + NACK_TEXT.get(reason, line), "err")
            return

        if cmd == "CONNECT" and line == "OK":
            self._set_status("Connected.", "ok")
            self._send("STATE")          # resync with whatever the board holds
        elif cmd == "NEW" and self._render(line):
            self._commit_names()
            self.game_active = True
            self.win_cells = ()
            self._set_status(f"New game. {self._turn_text()}", "fg")
            self._maybe_ai_move()
        elif cmd.startswith("MOVE"):
            if self._render(line):
                self._set_status(self._turn_text(), "fg")
                self._maybe_ai_move()
            elif line in ("WIN:X", "WIN:O"):
                w = line[4]
                self._game_over(f"{self.name(w)} wins!", w)
                self._send("STATE")      # fetch the final board from the server
            elif line == "DRAW":
                self._game_over("It's a draw.", "D")
                self._send("STATE")
            else:
                self._set_status(f"Unexpected reply: {line}", "err")
        elif cmd == "STATE" and self._render(line):
            line_cells = winning_line(self.board)
            if line_cells and not self.game_active:
                self.win_cells = line_cells
            elif not self.game_active and self.status_kind != "ok":
                # Reconnected to a game the board still holds.
                self.game_active = True
                self._set_status("Connected. Game in progress: " + self._turn_text(), "fg")
                self._maybe_ai_move()
        elif cmd == "RESIGN" and line == "OK:GAMEOVER":
            loser = self._turn()
            winner = "O" if loser == "X" else "X"
            self._game_over(f"{self.name(loser)} resigned. {self.name(winner)} wins!", winner)
        elif cmd == "DISCONNECT" and line == "OK":
            self._close("Disconnected.", "muted")
        else:
            self._set_status(f"Unexpected reply to {cmd}: {line}", "err")

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
