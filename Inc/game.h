/*
 * game.h - Tic-Tac-Toe rules and server state machine.
 *
 * Pure logic: no HAL, no I/O. The same file builds for the STM32 and for
 * the PC simulator, so the tests exercise exactly the code on the board.
 */
#ifndef GAME_H
#define GAME_H

#include <stdint.h>

#define BOARD_CELLS 9
#define CELL_EMPTY  '.'

typedef enum {
    ST_IDLE = 0,       /* boot and post-game: CONNECT, NEW            */
    ST_IN_PROGRESS,    /* MOVE, STATE, RESIGN                         */
    ST_GAME_OVER       /* NEW, STATE, DISCONNECT                      */
} server_state_t;

typedef enum {
    RES_NONE = 0,
    RES_WIN_X,
    RES_WIN_O,
    RES_DRAW,
    RES_RESIGNED
} game_result_t;

typedef enum {
    MV_OK = 0,         /* accepted, game continues                    */
    MV_WIN,            /* accepted, mover won                         */
    MV_DRAW,           /* accepted, board full                        */
    MV_NOGAME,         /* no game in progress                         */
    MV_RANGE,          /* index outside 0..8                          */
    MV_NOTURN,         /* named player is not the player to move      */
    MV_OCCUPIED        /* cell already taken                          */
} move_status_t;

typedef struct {
    char           cells[BOARD_CELLS];  /* '.', 'X' or 'O'           */
    char           turn;                /* 'X' or 'O': player to move */
    server_state_t state;
    game_result_t  result;
    uint8_t        moves;               /* moves played this game     */
} game_t;

/* Power-on state: IDLE with an empty board. */
void game_init(game_t *g);

/* Start a new game: empty board, X to move, IN_PROGRESS. */
void game_new(game_t *g);

/*
 * Validate and apply a move. `player` is 'X' or 'O' to name the mover
 * explicitly, or 0 to mean "whoever's turn it is".
 * Every check runs before the first write, so any status other than
 * MV_OK / MV_WIN / MV_DRAW leaves *g unchanged.
 */
move_status_t game_move(game_t *g, int index, char player);

/* The player to move forfeits. Only valid IN_PROGRESS (caller checks). */
void game_resign(game_t *g);

/* Return to IDLE after a finished game (DISCONNECT, button). */
void game_reset(game_t *g);

/* 'X' or 'O' if that player holds a full line, else 0. */
char game_winner(const char cells[BOARD_CELLS]);

#endif /* GAME_H */
