/* Supplied format/contained-filesystem helpers. No runtime or layer policy. */
#include <errno.h>
#include <ftw.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#include "runner.h"
static int helper(const char *action, const char *a, const char *b)
{
    char script[PATH_MAX];
    ssize_t n = readlink("/proc/self/exe", script, sizeof(script)-1);
    if (n < 0) return -1;
    script[n] = 0;
    char *slash = strrchr(script, '/');
    if (!slash) { errno = EINVAL; return -1; }
    *slash = 0;
    size_t len = strlen(script);
    if (len + sizeof("/src/image_helper.py") > sizeof(script)) { errno = ENAMETOOLONG; return -1; }
    strcpy(script + len, "/src/image_helper.py");
    pid_t p = fork();
    if (p < 0) return -1;
    if (!p) {
        execl("/usr/bin/python3", "python3", script, action, a, b, (char *)NULL);
        _exit(1);
    }
    int status;
    while (waitpid(p, &status, 0) < 0) if (errno != EINTR) return -1;
    if (!WIFEXITED(status) || WEXITSTATUS(status)) { errno = EINVAL; return -1; }
    return 0;
}
static int number(FILE *f, uint32_t *out)
{
    unsigned char b[4];
    if (fread(b, 1, 4, f) != 4) return -1;
    *out = (uint32_t)b[0] | ((uint32_t)b[1]<<8) | ((uint32_t)b[2]<<16) | ((uint32_t)b[3]<<24);
    return 0;
}
static char *read_string(FILE *f)
{
    uint32_t n;
    if (number(f, &n) || n > 1048576) return NULL;
    char *s = calloc((size_t)n+1, 1);
    if (!s) return NULL;
    if (fread(s, 1, n, f) != n) { free(s); return NULL; }
    return s;
}
static char **array(FILE *f)
{
    uint32_t n;
    if (number(f, &n) || n > 4096) return NULL;
    char **a = calloc((size_t)n+1, sizeof(*a));
    if (!a) return NULL;
    for (uint32_t k = 0; k < n; ++k) {
        if (!(a[k] = read_string(f))) {
            for (uint32_t j = 0; j < k; ++j) free(a[j]);
            free(a); return NULL;
        }
    }
    return a;
}
int support_image_open(const char *path, struct image_data *image)
{
    memset(image, 0, sizeof(*image));
    const char *base = getenv("LANGAR_STATE_DIR");
    if (!base) base = "/tmp";
    if (snprintf(image->workspace, sizeof(image->workspace), "%s/langar-image-XXXXXX", base) >= (int)sizeof(image->workspace)) return -1;
    if (!mkdtemp(image->workspace)) { image->workspace[0] = 0; return -1; }
    if (helper("prepare", path, image->workspace)) return -1;
    char config[PATH_MAX];
    if (snprintf(config, sizeof(config), "%s/config.bin", image->workspace) >= (int)sizeof(config)) return -1;
    FILE *f = fopen(config, "rb");
    if (!f) return -1;
    uint32_t count;
    if (number(f, &count)) { fclose(f); return -1; }
    image->layers = count;
    image->cwd = read_string(f); image->env = array(f);
    image->entrypoint = array(f); image->cmd = array(f);
    fclose(f);
    if (snprintf(image->rootfs, sizeof(image->rootfs), "%s/rootfs", image->workspace) >= (int)sizeof(image->rootfs)) return -1;
    return image->cwd && image->env && image->entrypoint && image->cmd ? 0 : -1;
}
static int remove_entry(const char *path, const struct stat *st, int type, struct FTW *walk)
{
    (void)st; (void)type; (void)walk;
    return remove(path);
}
void support_image_close(struct image_data *image)
{
    /* CLONE_NEWPID changes the namespace for later children of this launcher.
     * After its PID 1 exits, another fork there can fail ENOMEM. Cleanup must
     * therefore not start another helper. Never follow image symlinks here. */
    if (image->workspace[0] && nftw(image->workspace, remove_entry, 32,
            FTW_DEPTH|FTW_PHYS|FTW_MOUNT) < 0) perror("image cleanup");
    free(image->cwd);
    char **arrays[] = {image->env, image->entrypoint, image->cmd};
    for (size_t i = 0; i < 3; ++i) if (arrays[i]) {
        for (size_t j = 0; arrays[i][j]; ++j) free(arrays[i][j]);
        free(arrays[i]);
    }
}
int support_whiteouts(struct image_data *image, size_t layer,
    int (*visit)(const char *, const char *, int))
{
    char name[PATH_MAX];
    if (snprintf(name, sizeof(name), "%s/whiteouts-%zu", image->workspace, layer) >= (int)sizeof(name)) return -1;
    FILE *f = fopen(name, "rb");
    if (!f) return -1;
    char *line = NULL; size_t capacity = 0; int result = 0;
    while (getdelim(&line, &capacity, 0, f) > 0)
        if (visit(image->rootfs, line+1, line[0] == '1')) { result = -1; break; }
    if (ferror(f)) result = -1;
    free(line); fclose(f); return result;
}
int support_copy_layer(struct image_data *image, size_t layer)
{
    char number_string[32]; (void)snprintf(number_string, sizeof(number_string), "%zu", layer);
    return helper("copy", image->workspace, number_string);
}
int support_remove(const char *root, const char *relative)
{ return helper("remove", root, relative); }
int support_clear_directory(const char *root, const char *relative)
{ return helper("clear", root, relative); }
