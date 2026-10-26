/*
 * main.c - STM32F051 Tic-Tac-Toe serial game server.
 *
 * Super-loop: drain received bytes into the protocol, expire stale frames,
 * debounce the button, drive the LED. Nothing in the loop waits for input.
 */
#include "board.h"
#include "protocol.h"

#define DEBOUNCE_MS 30u

static server_t server;

/* Returns 1 once per debounced press. */
static int button_pressed(uint32_t now)
{
    static uint8_t  stable, last_raw;
    static uint32_t changed_ms;

    uint8_t raw = (uint8_t)board_button_down();
    if (raw != last_raw) {
        last_raw   = raw;
        changed_ms = now;
        return 0;
    }
    if (raw != stable && (uint32_t)(now - changed_ms) >= DEBOUNCE_MS) {
        stable = raw;
        return raw;
    }
    return 0;
}

/*
 * IDLE: off.  IN_PROGRESS: solid on for X to move, 1 Hz blink for O.
 * GAME_OVER: fast 5 Hz blink.
 */
static void led_update(uint32_t now)
{
    const game_t *g = &server.game;
    int on;

    switch (g->state) {
    case ST_IN_PROGRESS: on = (g->turn == 'X') ? 1 : (int)((now / 500u) & 1u); break;
    case ST_GAME_OVER:   on = (int)((now / 100u) & 1u);                        break;
    default:             on = 0;                                               break;
    }
    board_led(on);
}

int main(void)
{
    char resp[RESP_MAX];
    uint8_t b;

    board_init();
    board_lcd_clear();      /* wipe whatever an earlier project left on the LCD */
    server_init(&server);

    for (;;) {
        uint32_t now = board_millis();

        if (board_uart_take_error()) {
            /* Bytes were lost, so the current frame cannot be trusted.
               Poison it: it is answered with NACK:BADCMD at its '\n'. */
            server_feed(&server, 0x00, now, resp, sizeof resp);
        }

        /* Bounded: at most 64 bytes per pass, then service the rest. */
        for (unsigned i = 0; i < 64u && board_uart_getc(&b); i++) {
            if (server_feed(&server, b, now, resp, sizeof resp))
                board_uart_puts(resp);
        }

        if (server_poll(&server, now, resp, sizeof resp))
            board_uart_puts(resp);

        if (button_pressed(now)) {
            server_button_reset(&server);
            board_uart_puts("EVT:RESET\n");
        }

        led_update(now);
    }
}
