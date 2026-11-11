#include <stdio.h>
#include <string.h>

#include "runner.h"

int main(int argc, char *argv[])
{
    if (argc < 4 || strcmp(argv[1], "run") != 0 ||
        strcmp(argv[2], "--") != 0) {
        fprintf(stderr, "Usage: %s run -- COMMAND [ARGUMENT ...]\n", argv[0]);
        return 2;
    }

    return run_command(&argv[3]);
}
