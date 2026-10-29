#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
static void die(const char *s) { perror(s); exit(99); }
static volatile sig_atomic_t received;
static void handled(int n) { received = n; }
static void pause_ready(void)
{
    puts("READY"); fflush(stdout);
    char c; if (read(0, &c, 1) != 1) exit(98);
}
int main(int argc, char **argv)
{
    if (argc < 2) return 99;
    if (!strcmp(argv[1], "identity")) {
        char name[256]; if (gethostname(name, sizeof(name))) die("hostname");
        printf("%ld %ld %s\n", (long)getpid(), (long)getppid(), name);
    } else if (!strcmp(argv[1], "resources")) {
        cpu_set_t set; CPU_ZERO(&set); if (sched_getaffinity(0, sizeof(set), &set)) die("affinity");
        for (int i = 0; i < CPU_SETSIZE; ++i) if (CPU_ISSET(i, &set)) printf("%d,", i);
        struct rlimit r; if (getrlimit(RLIMIT_AS, &r)) die("rlimit");
        printf(" %llu\n", (unsigned long long)r.rlim_cur);
    } else if (!strcmp(argv[1], "allocate")) {
        size_t n = (size_t)strtoull(argv[2], NULL, 10)*1024*1024;
        void *p = mmap(NULL, n, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
        if (p == MAP_FAILED) { puts("DENIED"); return 0; }
        puts("OK"); munmap(p, n);
    } else if (!strcmp(argv[1], "proc")) {
        FILE *f = fopen("/proc/self/status", "r"); if (!f) die("proc");
        char line[256]; int seen = -1;
        while (fgets(line, sizeof(line), f)) if (sscanf(line, "Pid: %d", &seen) == 1) break;
        fclose(f); printf("%ld %d\n", (long)getpid(), seen);
    } else if (!strcmp(argv[1], "hold")) {
        printf("%ld %ld\n", (long)getpid(), (long)getppid()); fflush(stdout); pause_ready();
    } else if (!strcmp(argv[1], "signal")) {
        struct sigaction sa = {0}; sa.sa_handler = handled; sigemptyset(&sa.sa_mask);
        if (sigaction(SIGTERM, &sa, NULL) || sigaction(SIGINT, &sa, NULL)) die("sigaction");
        puts("READY"); fflush(stdout);
        while (!received) pause();
        printf("GOT %d\n", received); return received == SIGTERM ? 23 : 24;
    } else if (!strcmp(argv[1], "group")) {
        int pipefd[2]; if (pipe(pipefd)) die("pipe");
        pid_t child = fork(); if (child < 0) die("fork");
        if (!child) {
            close(pipefd[0]); struct sigaction sa = {0}; sa.sa_handler = handled;
            sigemptyset(&sa.sa_mask); sigaction(SIGTERM, &sa, NULL);
            if (write(pipefd[1], "R", 1) != 1) die("ready");
            close(pipefd[1]);
            while (!received) pause();
            puts("GRANDCHILD-SIGNAL"); fflush(stdout); _exit(0);
        }
        close(pipefd[1]); char c; if (read(pipefd[0], &c, 1) != 1) die("child ready"); close(pipefd[0]);
        struct sigaction sa = {0}; sa.sa_handler = handled; sigemptyset(&sa.sa_mask);
        sigaction(SIGTERM, &sa, NULL); puts("READY"); fflush(stdout);
        while (!received) pause();
        int status; while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
        return 31;
    } else if (!strcmp(argv[1], "ignore")) {
        signal(SIGTERM, SIG_IGN); puts("READY"); fflush(stdout); for (;;) pause();
    } else if (!strcmp(argv[1], "orphan")) {
        int pfd[2]; if (pipe(pfd)) die("pipe");
        pid_t c = fork(); if (c < 0) die("fork");
        if (!c) {
            close(pfd[0]); pid_t g = fork(); if (g < 0) die("fork grandchild");
            if (!g) { close(pfd[1]); usleep(100000); _exit(17); }
            if (write(pfd[1], &g, sizeof(g)) != sizeof(g)) die("orphan pid");
            _exit(3);
        }
        close(pfd[1]); pid_t g;
        if (read(pfd[0], &g, sizeof(g)) != sizeof(g)) die("orphan read");
        close(pfd[0]);
        int status; while (waitpid(c, &status, 0) < 0 && errno == EINTR) {}
        char name[64]; snprintf(name, sizeof(name), "/proc/%ld/status", (long)g);
        int gone = 0;
        for (int i = 0; i < 200; ++i) {
            if (access(name, F_OK) < 0 && errno == ENOENT) { gone = 1; break; }
            usleep(10000);
        }
        puts(gone ? "REAPED" : "NOT-REAPED"); fflush(stdout);
        pause_ready(); return gone ? 42 : 43;
    } else if (!strcmp(argv[1], "exit-other")) {
        pid_t c = fork(); if (c < 0) die("fork");
        if (!c) { usleep(50000); _exit(9); }
        usleep(100000); return 42;
    } else if (!strcmp(argv[1], "cwd")) {
        char cwd[4096]; if (!getcwd(cwd, sizeof(cwd))) die("cwd"); puts(cwd);
    } else if (!strcmp(argv[1], "layer-check")) {
        char text[4] = {0}; FILE *f = fopen("/work/replaced", "r");
        if (!f || fread(text, 1, 3, f) != 3) return 80;
        fclose(f);
        if (strcmp(text, "new") || access("/work/deleted", F_OK) == 0 ||
            access("/opaque/old", F_OK) == 0 || access("/opaque/new", F_OK)) return 81;
        struct stat a, b;
        if (stat("/work/replaced", &a) || stat("/work/hard", &b) || a.st_ino != b.st_ino) return 82;
        char link[64]; ssize_t n = readlink("/work/link", link, sizeof(link)-1);
        if (n < 0) return 83;
        link[n] = 0;
        if (strcmp(link, "replaced")) return 84;
        puts("LAYERS-OK");
    } else if (!strcmp(argv[1], "write-check")) {
        FILE *f = fopen("/work/value", "r"); if (!f) return 85;
        char text[32]; if (!fgets(text, sizeof(text), f)) return 86;
        fclose(f); fputs(text, stdout);
        f = fopen("/work/value", "w"); if (!f) return 87;
        fputs("modified\n", f); fclose(f);
    } else if (!strcmp(argv[1], "mask")) {
        sigset_t set; sigprocmask(SIG_SETMASK, NULL, &set);
        printf("%d %d %d\n", sigismember(&set, SIGTERM), sigismember(&set, SIGINT), sigismember(&set, SIGCHLD));
    } else if (!strcmp(argv[1], "env")) {
        const char *x = getenv(argv[2]); if (x) puts(x); else return 4;
    } else return 99;
    return 0;
}
