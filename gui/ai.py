"""Tic-Tac-Toe AI opponent for the GUI client.

The AI only *suggests* a move. The GUI sends it to the STM32 as an ordinary
MOVE:<P>:<n>, so the board still validates every AI move exactly as it does a
human's; the AI cannot change the game state by itself.

Levels:
    easy    a random empty cell
    medium  win if it can, else block the opponent's win, else random
    hard    perfect play (minimax): never loses
"""
import random
from functools import lru_cache

LEVELS = ("easy", "medium", "hard")
WIN_LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8),
             (0, 3, 6), (1, 4, 7), (2, 5, 8),
             (0, 4, 8), (2, 4, 6))


def other(player: str) -> str:
    return "O" if player == "X" else "X"


def winner(board: str):
    for a, b, c in WIN_LINES:
        if board[a] != "." and board[a] == board[b] == board[c]:
            return board[a]
    return None


def empty_cells(board: str):
    return [i for i, c in enumerate(board) if c == "."]


def _play(board: str, i: int, player: str) -> str:
    return board[:i] + player + board[i + 1:]


def _winning_move(board: str, player: str):
    for i in empty_cells(board):
        if winner(_play(board, i, player)) == player:
            return i
    return None


@lru_cache(maxsize=None)
def _score(board: str, to_move: str, me: str) -> int:
    """Minimax value of `board` for `me`: >0 win, <0 loss, 0 draw; quicker wins score higher."""
    w = winner(board)
    if w is not None:
        depth = board.count(".")
        return (1 + depth) if w == me else -(1 + depth)
    cells = empty_cells(board)
    if not cells:
        return 0
    scores = [_score(_play(board, i, to_move), other(to_move), me) for i in cells]
    return max(scores) if to_move == me else min(scores)


def _best_moves(board: str, me: str):
    cells = empty_cells(board)
    scored = [(_score(_play(board, i, me), other(me), me), i) for i in cells]
    best = max(s for s, _ in scored)
    return [i for s, i in scored if s == best]


def pick_move(board: str, me: str, level: str, rng: random.Random = random) -> int:
    """Return the index (0-8) of the AI's move for player `me` on `board`."""
    cells = empty_cells(board)
    if not cells or winner(board):
        raise ValueError("no move possible: game is over")
    if level == "easy":
        return rng.choice(cells)
    if level == "medium":
        for player in (me, other(me)):          # win first, then block
            i = _winning_move(board, player)
            if i is not None:
                return i
        return rng.choice(cells)
    if level == "hard":
        return rng.choice(_best_moves(board, me))
    raise ValueError(f"unknown level {level!r}")
