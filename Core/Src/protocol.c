/*
 * protocol.c - Frame assembly and command handling for the serial game server.
 */
#include "protocol.h"

#include <stdio.h>
#include <string.h>

/* ------------------------------------------------------------- framing -- */

static void framer_clear(framer_t *f)
{
    f->len      = 0;
    f->overflow = 0;
    f->bad_char = 0;
    f->buf[0]   = '\0';
}

static int framer_busy(const framer_t *f)
{
    return f->len > 0 || f->overflow || f->bad_char;
}

static void reply(char *resp, size_t n, const char *text)
{
    snprintf(resp, n, "%s\n", text);
}

static void reply_board(char *resp, size_t n, const char *prefix,
                        const game_t *g)
{
    snprintf(resp, n, "%s%.9s\n", prefix, g->cells);
}

void server_init(server_t *s)
{
    game_init(&s->game);
    framer_clear(&s->framer);
    s->framer.last_ms = 0;
}

int server_feed(server_t *s, uint8_t byte, uint32_t now_ms,
                char *resp, size_t resp_len)
{
    framer_t *f = &s->framer;
    f->last_ms = now_ms;

    if (byte == '\r')
        return 0;

    if (byte == '\n') {
        int handled = 1;
        if (f->overflow) {
            reply(resp, resp_len, "NACK:TOOLONG");
        } else if (f->bad_char) {
            reply(resp, resp_len, "NACK:BADCMD");
        } else if (f->len == 0) {
            handled = 0;                      /* blank line: ignore */
        } else {
            f->buf[f->len] = '\0';
            server_handle_frame(s, f->buf, resp, resp_len);
        }
        framer_clear(f);
        return handled;
    }

    if (f->overflow)
        return 0;                             /* skip to the next '\n' */

    if (f->len >= FRAME_MAX) {
        f->overflow = 1;
        return 0;
    }

    if (byte < 0x20 || byte > 0x7E) {
        f->bad_char = 1;                      /* keep counting length */
        byte = '?';
    }
    f->buf[f->len++] = (char)byte;
    return 0;
}

int server_poll(server_t *s, uint32_t now_ms, char *resp, size_t resp_len)
{
    framer_t *f = &s->framer;
    if (framer_busy(f) && (uint32_t)(now_ms - f->last_ms) >= FRAME_TIMEOUT_MS) {
        framer_clear(f);
        reply(resp, resp_len, "NACK:TIMEOUT");
        return 1;
    }
    return 0;
}

/* ------------------------------------------------------------ checksum -- */

static int hex_val(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

/*
 * If frame ends in "*HH", verify it and strip it in place.
 * Returns 1 if there was no checksum or it matched, 0 if it was wrong.
 */
static int strip_checksum(char *frame)
{
    char *star = strchr(frame, '*');
    if (star == NULL)
        return 1;
    if (strlen(star) != 3)
        return 0;
    int hi = hex_val(star[1]), lo = hex_val(star[2]);
    if (hi < 0 || lo < 0)
        return 0;

    uint8_t sum = 0;
    for (const char *p = frame; p < star; p++)
        sum ^= (uint8_t)*p;
    if (sum != (uint8_t)((hi << 4) | lo))
        return 0;

    *star = '\0';
    return 1;
}

/* ------------------------------------------------------------ commands -- */

/*
 * Parse the argument of MOVE. Accepts "<n>" or "<P>:<n>" where P is X or O
 * and n is 1-3 decimal digits, optionally preceded by '-'.
 * Returns 1 on success, 0 if the text is malformed.
 */
static int parse_move(const char *arg, char *player, int *index)
{
    *player = 0;
    if ((arg[0] == 'X' || arg[0] == 'O') && arg[1] == ':') {
        *player = arg[0];
        arg += 2;
    }

    int neg = 0;
    if (*arg == '-') {
        neg = 1;
        arg++;
    }

    int digits = 0, value = 0;
    while (*arg >= '0' && *arg <= '9') {
        if (++digits > 3)
            return 0;
        value = value * 10 + (*arg - '0');
        arg++;
    }
    if (digits == 0 || *arg != '\0')
        return 0;

    *index = neg ? -value : value;
    return 1;
}

static void handle_move(game_t *g, const char *arg, char *resp, size_t n)
{
    char player;
    int  index;

    if (g->state != ST_IN_PROGRESS) {
        reply(resp, n, "NACK:NOGAME");
        return;
    }
    if (!parse_move(arg, &player, &index)) {
        reply(resp, n, "NACK:BADCMD");
        return;
    }

    switch (game_move(g, index, player)) {
    case MV_OK:       reply_board(resp, n, "OK:BOARD:", g);          break;
    case MV_WIN:      reply(resp, n, g->result == RES_WIN_X ? "WIN:X" : "WIN:O"); break;
    case MV_DRAW:     reply(resp, n, "DRAW");                        break;
    case MV_NOGAME:   reply(resp, n, "NACK:NOGAME");                 break;
    case MV_RANGE:    reply(resp, n, "NACK:RANGE");                  break;
    case MV_NOTURN:   reply(resp, n, "NACK:NOTURN");                 break;
    case MV_OCCUPIED: reply(resp, n, "NACK:OCCUPIED");               break;
    }
}

void server_handle_frame(server_t *s, const char *frame_in,
                         char *resp, size_t n)
{
    game_t *g = &s->game;
    char frame[FRAME_MAX + 1];

    strncpy(frame, frame_in, FRAME_MAX);
    frame[FRAME_MAX] = '\0';

    if (!strip_checksum(frame)) {
        reply(resp, n, "NACK:CHECKSUM");
        return;
    }

    if (strcmp(frame, "CONNECT") == 0) {
        /* Accepted in every state so a restarted client can resync. */
        reply(resp, n, "OK");
    } else if (strcmp(frame, "NEW") == 0) {
        if (g->state == ST_IN_PROGRESS) {
            reply(resp, n, "NACK:STATE");
        } else {
            game_new(g);
            reply_board(resp, n, "OK:BOARD:", g);
        }
    } else if (strncmp(frame, "MOVE:", 5) == 0) {
        handle_move(g, frame + 5, resp, n);
    } else if (strcmp(frame, "STATE") == 0) {
        if (g->state == ST_IDLE)
            reply(resp, n, "NACK:NOGAME");
        else
            reply_board(resp, n, "BOARD:", g);
    } else if (strcmp(frame, "RESIGN") == 0) {
        if (g->state != ST_IN_PROGRESS) {
            reply(resp, n, "NACK:NOGAME");
        } else {
            game_resign(g);
            reply(resp, n, "OK:GAMEOVER");
        }
    } else if (strcmp(frame, "DISCONNECT") == 0) {
        if (g->state == ST_IN_PROGRESS) {
            reply(resp, n, "NACK:STATE");
        } else {
            game_reset(g);
            reply(resp, n, "OK");
        }
    } else {
        reply(resp, n, "NACK:BADCMD");
    }
}

void server_button_reset(server_t *s)
{
    game_reset(&s->game);
    framer_clear(&s->framer);
}
