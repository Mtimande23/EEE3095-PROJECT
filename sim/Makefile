CC      ?= cc
CFLAGS  ?= -std=c11 -Wall -Wextra -Werror -O2
OUT     ?= .
FW      := ../firmware/Core
SRCS    := sim_main.c $(FW)/Src/game.c $(FW)/Src/protocol.c

$(OUT)/gamesim: $(SRCS) $(FW)/Inc/game.h $(FW)/Inc/protocol.h
	$(CC) $(CFLAGS) -I$(FW)/Inc -o $@ $(SRCS)

clean:
	rm -f $(OUT)/gamesim

.PHONY: clean
