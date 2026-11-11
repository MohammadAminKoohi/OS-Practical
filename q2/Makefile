.DEFAULT_GOAL := all
CC ?= gcc
CFLAGS ?= -O2
REQUIRED_CFLAGS := -std=c11 -Wall -Wextra -Werror
CPPFLAGS += -D_POSIX_C_SOURCE=200809L -Iinclude
SOURCES := $(wildcard src/*.c)
OBJECTS := $(SOURCES:.c=.o)

.PHONY: all clean
all: langar

langar: $(OBJECTS)
	$(CC) $(CFLAGS) $(REQUIRED_CFLAGS) $(LDFLAGS) -o $@ $(OBJECTS) $(LDLIBS)

src/%.o: src/%.c $(wildcard include/*.h)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(REQUIRED_CFLAGS) -c $< -o $@

clean:
	rm -f langar $(OBJECTS)
