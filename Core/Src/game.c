/*
 * game.c - Tic-Tac-Toe rules and server state machine.
 */
#include "game.h"

#include <string.h>

/* The eight winning lines, as cell indices 0..8 (row-major). */
static const uint8_t LINES[8][3] = {
    {0, 1, 2}, {3, 4, 5}, {6, 7, 8},   /* rows      */
    {0, 3, 6}, {1, 4, 7}, {2, 5, 8},   /* columns   */
    {0, 4, 8}, {2, 4, 6}               /* diagonals */
};

static void clear_board(game_t *g)
{
    memset(g->cells, CELL_EMPTY, BOARD_CELLS);
    g->turn   = 'X';
    g->result = RES_NONE;
    g->moves  = 0;
}

void game_init(game_t *g)
{
    clear_board(g);
    g->state = ST_IDLE;
}

void game_new(game_t *g)
{
    clear_board(g);
    g->state = ST_IN_PROGRESS;
}

void game_reset(game_t *g)
{
    game_init(g);
}

char game_winner(const char cells[BOARD_CELLS])
{
    for (int i = 0; i < 8; i++) {
        char a = cells[LINES[i][0]];
        if (a != CELL_EMPTY &&
            a == cells[LINES[i][1]] &&
            a == cells[LINES[i][2]]) {
            return a;
        }
    }
    return 0;
}

move_status_t game_move(game_t *g, int index, char player)
{
    /* 1. Checks only. Nothing below writes until all of them pass. */
    if (g->state != ST_IN_PROGRESS)
        return MV_NOGAME;
    if (index < 0 || index >= BOARD_CELLS)
        return MV_RANGE;
    if (player != 0 && player != g->turn)
        return MV_NOTURN;
    if (g->cells[index] != CELL_EMPTY)
        return MV_OCCUPIED;

    /* 2. Commit. */
    char mover = g->turn;
    g->cells[index] = mover;
    g->moves++;

    if (game_winner(g->cells) == mover) {
        g->result = (mover == 'X') ? RES_WIN_X : RES_WIN_O;
        g->state  = ST_GAME_OVER;
        return MV_WIN;
    }
    if (g->moves == BOARD_CELLS) {
        g->result = RES_DRAW;
        g->state  = ST_GAME_OVER;
        return MV_DRAW;
    }
    g->turn = (mover == 'X') ? 'O' : 'X';
    return MV_OK;
}

void game_resign(game_t *g)
{
    g->result = RES_RESIGNED;
    g->state  = ST_GAME_OVER;
}
