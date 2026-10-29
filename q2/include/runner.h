#ifndef LANGAR_RUNNER_H
#define LANGAR_RUNNER_H
#include <stddef.h>
#include <limits.h>
struct runner_options {
    int isolate;
    const char *hostname, *cpus, *rootfs, *image;
    unsigned long long as_mib;
};
/* HW3 changes this signature: retain your own HW2 fork/exec/wait logic. */
int run_command(char *const argv[], const struct runner_options *options);
#endif
