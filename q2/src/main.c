#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "runner.h"
#ifndef LANGAR_HW
#define LANGAR_HW 3
#endif
static int usage(const char *name)
{
    fprintf(stderr, "Usage: %s run [--isolate] [--hostname NAME]", name);
#if LANGAR_HW >= 4
    fputs(" [--cpus LIST] [--as-limit-mib N]", stderr);
#endif
#if LANGAR_HW >= 6
    fputs(" [--rootfs DIR]", stderr);
#endif
#if LANGAR_HW >= 7
    fputs(" [--image DIR]", stderr);
#endif
    fputs(" -- COMMAND [ARG ...]\n", stderr);
    return 2;
}
int main(int argc, char **argv)
{
    struct runner_options o = {0};
    int i = 2;
    if (argc < 3 || strcmp(argv[1], "run")) return usage(argv[0]);
    while (i < argc && strcmp(argv[i], "--")) {
        const char *flag = argv[i++];
        if (!strcmp(flag, "--isolate")) {
            if (o.isolate) return usage(argv[0]);
            o.isolate = 1; continue;
        }
        if (i == argc) return usage(argv[0]);
        const char *value = argv[i++];
        if (!strcmp(flag, "--hostname") && !o.hostname && strlen(value) > 0 && strlen(value) <= 63)
            o.hostname = value;
        else if (LANGAR_HW >= 4 && !strcmp(flag, "--cpus") && !o.cpus && *value)
            o.cpus = value;
        else if (LANGAR_HW >= 4 && !strcmp(flag, "--as-limit-mib") && !o.as_mib) {
            char *end; errno = 0;
            unsigned long long n = strtoull(value, &end, 10);
            if (!*value || *end || errno || *value == '-' || n == 0 || n > 1048576)
                return usage(argv[0]);
            o.as_mib = n;
        } else if (LANGAR_HW >= 6 && !strcmp(flag, "--rootfs") && !o.rootfs && *value)
            o.rootfs = value;
        else if (LANGAR_HW >= 7 && !strcmp(flag, "--image") && !o.image && *value)
            o.image = value;
        else return usage(argv[0]);
    }
    if (i == argc || (o.hostname && !o.isolate) || (o.rootfs && o.image) ||
        ((o.rootfs || o.image) && !o.isolate)) return usage(argv[0]);
    ++i;
    if (i == argc && !o.image) return usage(argv[0]);
    return run_command(argv + i, &o);
}
