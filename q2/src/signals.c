/* Supplied HW8 primitives; students implement the supervisor policy in run.c. */
#include <errno.h>
#include <signal.h>
#include <time.h>
#include "runner.h"
static void wake_handler(int sig) { (void)sig; }
int support_block_signals(void)
{
    sigset_t set; sigemptyset(&set);
    int signals[] = {SIGINT, SIGTERM, SIGCHLD};
    struct sigaction sa = {0}; sa.sa_handler = wake_handler;
    sigemptyset(&sa.sa_mask);
    for (size_t i = 0; i < sizeof(signals)/sizeof(signals[0]); ++i) {
        if (sigaction(signals[i], &sa, NULL) < 0) return -1;
        sigaddset(&set, signals[i]);
    }
    /* A non-default disposition is intentional for Linux namespace PID 1. */
    return sigprocmask(SIG_BLOCK, &set, NULL);
}
void support_reset_signals(void)
{
    sigset_t empty; sigemptyset(&empty);
    struct sigaction sa = {0}; sa.sa_handler = SIG_DFL; sigemptyset(&sa.sa_mask);
    (void)sigaction(SIGINT, &sa, NULL); (void)sigaction(SIGTERM, &sa, NULL);
    (void)sigaction(SIGCHLD, &sa, NULL);
    (void)sigprocmask(SIG_SETMASK, &empty, NULL);
}
int support_wait_signal(int timeout_ms)
{
    sigset_t set; sigemptyset(&set);
    sigaddset(&set, SIGINT); sigaddset(&set, SIGTERM); sigaddset(&set, SIGCHLD);
    struct timespec t = {timeout_ms/1000, (timeout_ms%1000)*1000000L};
    int n;
    do { n = sigtimedwait(&set, NULL, &t); } while (n < 0 && errno == EINTR);
    return n < 0 && errno == EAGAIN ? 0 : n;
}
long long support_now_ms(void)
{
    struct timespec t; (void)clock_gettime(CLOCK_MONOTONIC, &t);
    return (long long)t.tv_sec*1000 + t.tv_nsec/1000000;
}
