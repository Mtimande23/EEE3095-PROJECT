# STM32 Tic-Tac-Toe serial game server

EEE3095S CS Project 2026. The STM32F051 (UCT STM board) is the referee: it holds the
only copy of the game, validates every request and replies with the authoritative
result. A thin Tkinter client on the PC draws the board from those replies and
forwards clicks. The full protocol, state machine and diagrams are in
[docs/PROTOCOL.md](docs/PROTOCOL.md).

```
firmware/Core/Inc, Src   game.c (rules), protocol.c (framing + commands): pure C
                         board.c (registers: clock, GPIO, USART, SysTick), main.c (super-loop)
sim/                     PC simulator: the same game.c and protocol.c on a pseudo-terminal
gui/client.py            Tkinter + pyserial client
tests/                   pytest harness that drives the serial link
docs/                    protocol, FSM, sequence diagram, screenshot
```

## 1. Build and flash the firmware (STM32CubeIDE, no CubeMX)

The firmware uses direct register access (`board.c`) for the clock, GPIO,
USART and SysTick, so it needs no HAL, no CubeMX and no CMSIS headers.

1. In STM32CubeIDE create an **STM32CubeIDE Empty Project** for **STM32F051C8T6**
   (or copy an existing working project for this board).
2. Delete the project's own `main.c`. Copy `firmware/Core/Src/*.c` into its source
   folder and `firmware/Core/Inc/*.h` into its `Inc` folder (or next to the `.c` files).
3. Build (hammer) and flash (*Run > Run As > STM32 C/C++ Application*).

Pins are set at the top of `firmware/Core/Inc/board.h`:

| Setting | Default | Change |
|---|---|---|
| UART | `GAME_UART 1`: USART1, PA9 TX / PA10 RX, 115200 8N1 | `GAME_UART 2` for USART2 on PA2/PA3 |
| Button | PA0, active low, internal pull-up | `BTN_PORT_BASE`, `BTN_PIN` |
| LED | PB0, active high | `LED_PORT_BASE`, `LED_PIN` |

On the UCT board the UART reaches the PC through the ST-Link virtual COM port
(for example COM4 on Windows).

**For markers:** this repository's `GameServer` CubeIDE project imports with
*File > Import > General > Existing Projects into Workspace*, then build and flash.

## 2. Run the GUI

```
pip install -r requirements.txt
python gui/client.py COM5          # or pick the port in the window
```

Connect, *New game*, click cells. Rejected moves show the server's reason; after a
win or draw the cells are disabled until *New game*. Tick *Checksum* to send the
optional `*HH` suffix.

## 3. Run the automated tests

Against the board:
```
pytest tests --port COM5
```
Without hardware (Linux/macOS, needs `cc` and `make`), the tests build and start the
simulator themselves:
```
pytest tests
```
47 tests: the brief's required cases (class `TestRequired`), server authority
(all 8 win lines, out-of-turn, out-of-state, "no rejected request changes state")
and robustness (oversized, garbage, partial frame timeout, split frames, CRLF,
checksum). Each test starts from IDLE, whatever the previous one left.

## 4. Use the simulator by hand

```
cd sim && make
./gamesim --link /tmp/ttyGAME      # prints PORT /tmp/ttyGAME
python ../gui/client.py /tmp/ttyGAME
```
Type `b` + Enter in the simulator's terminal to press the virtual button. LED state
changes are printed there.

## Status

- Tested: all 47 tests pass on the PC simulator; the GUI was driven end to end
  against the simulator (screenshot in `docs/gui_simulator.png`).
- Firmware: compiles and links for Cortex-M0 with arm-none-eabi-gcc (about 7 KB of
  64 KB flash); register addresses checked against ST's CMSIS headers. Not yet run
  on a real board. Run the tests with `--port`
  on the board before reporting results.
