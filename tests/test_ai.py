"""Tests for the GUI's AI opponent.

The brief (p. 4): "if an AI opponent is implemented, it never makes an
illegal move". TestAIOnServer checks exactly that through the real link: the
AI's moves are sent as MOVE:<P>:<n> and the server must accept every one.
TestAILogic checks the levels themselves, offline.
"""
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui"))
import ai  # noqa: E402

EMPTY = "." * 9


# -------------------------------------------------------- offline logic ---

class TestAILogic:
    @pytest.mark.parametrize("me", ["X", "O"])
    def test_hard_never_loses_against_any_opponent(self, me):
        """Explore every possible opponent reply; Hard must never lose."""
        def explore(board, to_move):
            w = ai.winner(board)
            if w is not None:
                assert w == me, f"Hard lost as {me}: {board}"
                return
            if "." not in board:
                return
            if to_move == me:
                i = ai.pick_move(board, me, "hard")
                explore(board[:i] + me + board[i + 1:], ai.other(me))
            else:
                for i in ai.empty_cells(board):
                    explore(board[:i] + to_move + board[i + 1:], me)
        explore(EMPTY, "X")

    def test_hard_and_medium_take_a_win(self):
        board = "XX.OO...."           # X to move, 2 wins
        for level in ("medium", "hard"):
            assert ai.pick_move(board, "X", level) == 2

    def test_medium_blocks(self):
        board = "OO..X...X"           # X to move must block cell 2
        assert ai.pick_move(board, "X", "medium") == 2

    @pytest.mark.parametrize("level", ai.LEVELS)
    def test_always_picks_an_empty_cell(self, level):
        rng = random.Random(1)
        for _ in range(500):
            board = EMPTY
            player = "X"
            while ai.winner(board) is None and "." in board:
                i = ai.pick_move(board, player, level, rng)
                assert board[i] == "."
                board = board[:i] + player + board[i + 1:]
                player = ai.other(player)

    def test_no_move_when_game_over(self):
        with pytest.raises(ValueError):
            ai.pick_move("XXXOO....", "O", "hard")


# ------------------------------------------------- through the server -----

class TestAIOnServer:
    @pytest.mark.parametrize("level", ai.LEVELS)
    @pytest.mark.parametrize("ai_side", ["X", "O"])
    def test_ai_never_makes_an_illegal_move(self, link, level, ai_side):
        """AI vs a random player, 5 games; the server must accept every AI move."""
        rng = random.Random(f"{level}{ai_side}")
        for _ in range(5):
            reply = link.cmd("NEW")
            assert reply == "OK:BOARD:" + EMPTY
            board, to_move = EMPTY, "X"
            while True:
                if to_move == ai_side:
                    i = ai.pick_move(board, ai_side, level, rng)
                    reply = link.cmd(f"MOVE:{ai_side}:{i}")
                    assert not reply.startswith("NACK"), \
                        f"AI ({level}) made an illegal move {i} on {board}: {reply}"
                else:
                    i = rng.choice(ai.empty_cells(board))
                    reply = link.cmd(f"MOVE:{to_move}:{i}")
                    assert not reply.startswith("NACK"), reply
                if reply in ("WIN:X", "WIN:O", "DRAW"):
                    break
                board = reply[len("OK:BOARD:"):]
                to_move = ai.other(to_move)

    def test_hard_ai_never_loses_on_the_server(self, link):
        rng = random.Random(7)
        for game in range(10):
            ai_side = "X" if game % 2 == 0 else "O"
            assert link.cmd("NEW") == "OK:BOARD:" + EMPTY
            board, to_move = EMPTY, "X"
            while True:
                if to_move == ai_side:
                    i = ai.pick_move(board, ai_side, "hard", rng)
                else:
                    i = rng.choice(ai.empty_cells(board))
                reply = link.cmd(f"MOVE:{to_move}:{i}")
                if reply in ("WIN:X", "WIN:O", "DRAW"):
                    assert reply != f"WIN:{ai.other(ai_side)}", "Hard AI lost"
                    break
                board = reply[len("OK:BOARD:"):]
                to_move = ai.other(to_move)
