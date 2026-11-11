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
/* Supplied image transport/format primitives, available from HW7. */
struct image_data {
    char workspace[PATH_MAX], rootfs[PATH_MAX];
    char *cwd, **env, **entrypoint, **cmd;
    size_t layers;
};
int support_image_open(const char *path, struct image_data *image);
void support_image_close(struct image_data *image);
int support_whiteouts(struct image_data *image, size_t layer,
    int (*visit)(const char *root, const char *path, int opaque));
int support_copy_layer(struct image_data *image, size_t layer);
int support_remove(const char *root, const char *relative);
int support_clear_directory(const char *root, const char *relative);
int support_apply_image(struct image_data *image); /* student: HW7 */
char **support_image_argv(struct image_data *image, char *const override[]); /* student: HW7 */
int support_image_environment(struct image_data *image); /* student: HW7 */
/* Supplied HW8 signal-wait scaffolding: no forwarding/reaping policy here. */
int support_block_signals(void);
void support_reset_signals(void);
int support_wait_signal(int timeout_ms);
long long support_now_ms(void);
#endif
