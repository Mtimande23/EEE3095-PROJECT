"""Automated tests for the Tic-Tac-Toe serial game server.

The first block maps one-to-one to the required tests in the brief (p. 4).
The rest cover server authority, every win line and protocol robustness.
"""
import time

import pytest

from conftest import checksum

EMPTY = "........."
WIN_LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8),
             (0, 3, 6), (1, 4, 7), (2, 5, 8),
             (0, 4, 8), (2, 4, 6)]
# X then O alternately; ends in a full board with no line.
DRAW_SEQUENCE = [0, 1, 2, 4, 3, 5, 7, 6, 8]


def state(link):
    reply = link.cmd("STATE")
    assert reply.startswith("BOARD:"), reply
    return reply[len("BOARD:"):]


def new_game(link):
    assert link.cmd("NEW") == "OK:BOARD:" + EMPTY


def play(link, moves):
    """Play moves, asserting each non-final one is accepted; return the last reply."""
    reply = None
    for m in moves:
        reply = link.cmd(f"MOVE:{m}")
    return reply


def winning_sequence(line):
    """X takes the three cells of `line`; O plays elsewhere without winning."""
    others = [c for c in range(9) if c not in line]
    o_moves = []
    for c in others:
        trial = set(o_moves + [c])
        if not any(set(l) <= trial for l in WIN_LINES):
            o_moves.append(c)
        if len(o_moves) == 2:
            break
    return [line[0], o_moves[0], line[1], o_moves[1], line[2]]


# ------------------------------------------------- required by the brief --

class TestRequired:
    def test_connect_ok_and_new_returns_empty_board(self, link):
        assert link.cmd("CONNECT") == "OK"
        assert link.cmd("NEW") == "OK:BOARD:" + EMPTY

    def test_legal_move_changes_board_exactly(self, link):
        new_game(link)
        assert link.cmd("MOVE:4") == "OK:BOARD:....X...."
        assert link.cmd("MOVE:0") == "OK:BOARD:O...X...."
        assert state(link) == "O...X...."

    def test_occupied_cell_is_rejected_and_board_unchanged(self, link):
        new_game(link)
        link.cmd("MOVE:4")
        before = state(link)
        assert link.cmd("MOVE:4") == "NACK:OCCUPIED"
        assert state(link) == before
        # Turn is unchanged too: O is still to move.
        assert link.cmd("MOVE:0") == "OK:BOARD:O...X...."

    @pytest.mark.parametrize("index", ["9", "10", "99", "-1"])
    def test_out_of_range_move_is_rejected(self, link, index):
        new_game(link)
        assert link.cmd(f"MOVE:{index}") == "NACK:RANGE"
        assert state(link) == EMPTY

    def test_move_after_game_over_is_rejected(self, link):
        new_game(link)
        assert play(link, winning_sequence((0, 1, 2))) == "WIN:X"
        before = state(link)
        assert link.cmd("MOVE:8") == "NACK:NOGAME"
        assert state(link) == before

    def test_scripted_win_for_x(self, link):
        new_game(link)
        assert play(link, [0, 3, 1, 4, 2]) == "WIN:X"
        assert state(link) == "XXXOO...."

    def test_scripted_win_for_o(self, link):
        new_game(link)
        assert play(link, [0, 3, 1, 4, 8, 5]) == "WIN:O"
        assert state(link) == "XX.OOO..X"

    def test_scripted_draw(self, link):
        new_game(link)
        replies = [link.cmd(f"MOVE:{m}") for m in DRAW_SEQUENCE]
        assert all(r.startswith("OK:BOARD:") for r in replies[:-1]), replies
        assert replies[-1] == "DRAW"
        assert state(link) == "XOXXOOOXX"


# ---------------------------------------------------- server authority ----

class TestAuthority:
    @pytest.mark.parametrize("line", WIN_LINES)
    def test_every_win_line_is_detected(self, link, line):
        new_game(link)
        assert play(link, winning_sequence(line)) == "WIN:X"

    def test_out_of_turn_move_is_rejected(self, link):
        new_game(link)
        assert link.cmd("MOVE:O:4") == "NACK:NOTURN"
        assert state(link) == EMPTY
        assert link.cmd("MOVE:X:4") == "OK:BOARD:....X...."
        assert link.cmd("MOVE:X:0") == "NACK:NOTURN"
        assert state(link) == "....X...."

    def test_move_without_a_game_is_rejected(self, link):
        assert link.cmd("MOVE:0") == "NACK:NOGAME"
        assert link.cmd("STATE") == "NACK:NOGAME"
        assert link.cmd("RESIGN") == "NACK:NOGAME"

    def test_out_of_state_commands_leave_game_intact(self, link):
        new_game(link)
        link.cmd("MOVE:4")
        assert link.cmd("NEW") == "NACK:STATE"
        assert link.cmd("DISCONNECT") == "NACK:STATE"
        assert state(link) == "....X...."

    def test_resign_ends_game(self, link):
        new_game(link)
        link.cmd("MOVE:4")
        assert link.cmd("RESIGN") == "OK:GAMEOVER"
        assert link.cmd("MOVE:0") == "NACK:NOGAME"
        assert state(link) == "....X...."

    def test_new_game_after_game_over(self, link):
        new_game(link)
        play(link, [0, 3, 1, 4, 2])
        assert link.cmd("NEW") == "OK:BOARD:" + EMPTY

    def test_disconnect_after_game_over_returns_to_idle(self, link):
        new_game(link)
        link.cmd("RESIGN")
        assert link.cmd("DISCONNECT") == "OK"
        assert link.cmd("STATE") == "NACK:NOGAME"

    def test_no_rejected_request_changes_state(self, link):
        """Fire every kind of bad request mid-game; the board and turn survive."""
        new_game(link)
        link.cmd("MOVE:4")
        before = state(link)
        bad = ["MOVE:4", "MOVE:9", "MOVE:X:0",
               "MOVE:", "MOVE:a", "MOVE:1234", "NEW", "DISCONNECT", "move:0", "HELLO",
               "MOVE:0*00"]
        for b in bad:
            assert link.cmd(b).startswith("NACK:"), b
            assert state(link) == before, b
        assert link.cmd("MOVE:0") == "OK:BOARD:O...X...."


# ------------------------------------------------- protocol robustness ----

class TestRobustness:
    @pytest.mark.parametrize("text", ["HELLO", "move:1", "MOVE", "MOVE:X", "MOVE:1:2",
                                      "MOVE:a", "MOVE: 1", "CONNECT ", "OK"])
    def test_malformed_commands_get_badcmd(self, link, text):
        new_game(link)
        assert link.cmd(text) == "NACK:BADCMD"
        assert state(link) == EMPTY

    def test_oversized_frame_is_rejected_then_link_recovers(self, link):
        link.send_raw(b"MOVE:" + b"1" * 200 + b"\n")
        assert link.read_line() == "NACK:TOOLONG"
        link.expect_silence()
        assert link.cmd("CONNECT") == "OK"

    def test_garbage_bytes_are_rejected_then_link_recovers(self, link):
        link.send_raw(b"\x00\x01\x1b[2J\x7f\xff\xfe\x80\n")   # under FRAME_MAX bytes
        assert link.read_line() == "NACK:BADCMD"
        assert link.cmd("NEW") == "OK:BOARD:" + EMPTY

    def test_partial_frame_times_out(self, link):
        link.send_raw(b"MOV")
        assert link.read_line(timeout=3.0) == "NACK:TIMEOUT"
        # The stale "MOV" was discarded, so this frame parses on its own.
        assert link.cmd("NEW") == "OK:BOARD:" + EMPTY

    def test_frame_split_across_writes_is_assembled(self, link):
        for chunk in (b"NE", b"W", b"\n"):
            link.send_raw(chunk)
            time.sleep(0.05)
        assert link.read_line() == "OK:BOARD:" + EMPTY

    def test_crlf_is_accepted(self, link):
        link.send_raw(b"CONNECT\r\n")
        assert link.read_line() == "OK"

    def test_blank_lines_are_ignored(self, link):
        link.send_raw(b"\n\n\n")
        link.expect_silence()

    def test_back_to_back_frames_each_get_a_reply(self, link):
        link.send_raw(b"NEW\nMOVE:0\nMOVE:1\nSTATE\n")
        assert [link.read_line() for _ in range(4)] == [
            "OK:BOARD:" + EMPTY, "OK:BOARD:X........", "OK:BOARD:XO.......", "BOARD:XO......."]

    def test_valid_checksum_is_accepted(self, link):
        assert link.cmd(checksum("NEW")) == "OK:BOARD:" + EMPTY
        assert link.cmd(checksum("MOVE:4")) == "OK:BOARD:....X...."

    @pytest.mark.parametrize("suffix", ["*00", "*ZZ", "*1", "*123"])
    def test_bad_checksum_is_rejected(self, link, suffix):
        new_game(link)
        assert link.cmd("MOVE:4" + suffix) == "NACK:CHECKSUM"
        assert state(link) == EMPTY
