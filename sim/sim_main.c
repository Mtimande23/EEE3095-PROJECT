/*
 * sim_main.c - PC simulator of the STM32 game server (Linux / macOS).
 *
 * Builds the same game.c and protocol.c that run on the board and exposes
 * them on a pseudo-terminal, so the GUI and the pytest harness talk to it
 * exactly as they would to the board's serial port.
 *
 *   ./gamesim [--link PATH]
 *
 * Prints "PORT <path>" on stdout once ready. With --link, also creates a
 * symlink at PATH pointing to the pty. Type "b" + Enter on stdin to press
 * the simulated button. LED changes are logged on stderr.
 */
#define _DEFAULT_SOURCE
#define _XOPEN_SOURCE 600

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

#include "protocol.h"

static volatile sig_atomic_t running = 1;
static const char *link_path;

static void on_signal(int sig)
{
    (void)sig;
    running = 0;
}

static uint32_t now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)(ts.tv_sec * 1000u + ts.tv_nsec / 1000000u);
}

static void send_line(int fd, const char *line)
{
    size_t len = strlen(line);
    while (len > 0) {
        ssize_t w = write(fd, line, len);
        if (w < 0) {
            if (errno == EINTR || errno == EAGAIN)
                continue;
            return;
        }
        line += w;
        len  -= (size_t)w;
    }
}

static const char *led_text(const game_t *g)
{
    switch (g->state) {
    case ST_IN_PROGRESS: return g->turn == 'X' ? "ON (X to move)" : "SLOW BLINK (O to move)";
    case ST_GAME_OVER:   return "FAST BLINK (game over)";
    default:             return "OFF (idle)";
    }
}

int main(int argc, char **argv)
{
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--link") == 0 && i + 1 < argc)
            link_path = argv[++i];
    }

    int master = posix_openpt(O_RDWR | O_NOCTTY);
    if (master < 0 || grantpt(master) < 0 || unlockpt(master) < 0) {
        perror("pty");
        return 1;
    }
    const char *slave_name = ptsname(master);

    /* Raw mode on the slave side: no echo, no line editing, no CR/LF
       translation, so the client sees bytes exactly as sent. */
    int slave = open(slave_name, O_RDWR | O_NOCTTY);
    if (slave >= 0) {
        struct termios t;
        tcgetattr(slave, &t);
        cfmakeraw(&t);
        tcsetattr(slave, TCSANOW, &t);
        /* Keep slave open so the master does not see EOF/EIO between
           client connections. */
    }

    if (link_path) {
        unlink(link_path);
        if (symlink(slave_name, link_path) < 0)
            perror("symlink");
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);

    server_t server;
    server_init(&server);

    printf("PORT %s\n", link_path ? link_path : slave_name);
    fflush(stdout);

    const char *last_led = NULL;
    char resp[RESP_MAX];

    while (running) {
        struct pollfd fds[2] = {
            { .fd = master,       .events = POLLIN },
            { .fd = STDIN_FILENO, .events = POLLIN },
        };
        int n = poll(fds, 2, 10);
        uint32_t now = now_ms();

        if (n > 0 && (fds[0].revents & POLLIN)) {
            uint8_t buf[64];
            ssize_t r = read(master, buf, sizeof buf);
            for (ssize_t i = 0; i < r; i++) {
                if (server_feed(&server, buf[i], now, resp, sizeof resp))
                    send_line(master, resp);
            }
        }

        if (n > 0 && (fds[1].revents & POLLIN)) {
            char line[16];
            if (fgets(line, sizeof line, stdin) == NULL) {
                fds[1].fd = -1;     /* stdin closed: keep serving */
            } else if (line[0] == 'b') {
                server_button_reset(&server);
                send_line(master, "EVT:RESET\n");
                fprintf(stderr, "[sim] button pressed\n");
            }
        }

        if (server_poll(&server, now, resp, sizeof resp))
            send_line(master, resp);

        const char *led = led_text(&server.game);
        if (led != last_led) {
            fprintf(stderr, "[sim] LED %s\n", led);
            last_led = led;
        }
    }

    if (link_path)
        unlink(link_path);
    if (slave >= 0)
        close(slave);
    close(master);
    return 0;
}
