/*
 * protocol.h - Frame assembly and command handling for the serial game server.
 *
 * Pure logic: bytes in, response lines out. The caller supplies the time in
 * milliseconds (HAL_GetTick() on the board, a monotonic clock in the sim).
 *
 * Framing rules (see docs/PROTOCOL.md):
 *   - A frame is printable ASCII ending in '\n'. '\r' is ignored.
 *   - At most FRAME_MAX bytes before the '\n'; longer frames are discarded
 *     whole and answered with NACK:TOOLONG.
 *   - An incomplete frame older than FRAME_TIMEOUT_MS is discarded and
 *     answered with NACK:TIMEOUT.
 *   - Optional checksum suffix "*HH": XOR of every byte before '*', two
 *     upper-case hex digits. A wrong checksum gives NACK:CHECKSUM.
 */
#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#include "game.h"

#define FRAME_MAX        32u
#define FRAME_TIMEOUT_MS 1000u
#define RESP_MAX         32u     /* longest reply is "OK:BOARD:" + 9 + "\n" */

typedef struct {
    char     buf[FRAME_MAX + 1];
    uint8_t  len;
    uint8_t  overflow;    /* frame passed FRAME_MAX: drop until '\n'      */
    uint8_t  bad_char;    /* frame holds a non-printable byte              */
    uint32_t last_ms;     /* time of the last byte of the current frame    */
} framer_t;

typedef struct {
    game_t   game;
    framer_t framer;
} server_t;

void server_init(server_t *s);

/*
 * Feed one received byte. Returns 1 and writes a '\n'-terminated reply into
 * resp when the byte completes a frame (or an oversized frame), else 0.
 */
int server_feed(server_t *s, uint8_t byte, uint32_t now_ms,
                char *resp, size_t resp_len);

/*
 * Call regularly from the main loop. Returns 1 and writes NACK:TIMEOUT into
 * resp if a partial frame has gone stale, else 0.
 */
int server_poll(server_t *s, uint32_t now_ms, char *resp, size_t resp_len);

/*
 * Handle one complete frame (without '\n'). Exposed for unit tests.
 * Always writes exactly one reply line into resp.
 */
void server_handle_frame(server_t *s, const char *frame,
                         char *resp, size_t resp_len);

/* Local reset from the on-board button: abandon any game, back to IDLE. */
void server_button_reset(server_t *s);

#endif /* PROTOCOL_H */
