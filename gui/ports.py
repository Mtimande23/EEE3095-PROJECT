"""Find the UCT board's serial port, so nobody has to know its COM number.

The board's ST-Link programmer also provides the virtual COM port the game
runs on. It reports ST's USB vendor ID (0x0483) and calls itself an
"STLink Virtual COM Port", so it can be picked out of the PC's ports
whatever number Windows gave it (COM4, COM12, /dev/ttyACM0, ...).
"""
import serial.tools.list_ports

ST_VID = 0x0483        # STMicroelectronics


def is_board(p) -> bool:
    text = " ".join(filter(None, (p.description, p.manufacturer, p.product))).lower()
    return p.vid == ST_VID or "stlink" in text or "st-link" in text


def find_boards():
    """Ports that look like the board, best match first."""
    return [p.device for p in serial.tools.list_ports.comports() if is_board(p)]


def find_board():
    """The board's port, or None if no board is plugged in."""
    boards = find_boards()
    return boards[0] if boards else None
