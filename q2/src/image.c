#include <errno.h>
#include <stdlib.h>
#include "runner.h"
/* HW7: apply whiteouts before copying each layer. Use support_remove and
 * support_clear_directory for contained filesystem operations. */
int support_apply_image(struct image_data *image)
{
    (void)image; errno = ENOSYS; return -1;
}
/* HW7: allocate a NULL-terminated argv; entrypoint + override-or-Cmd. */
char **support_image_argv(struct image_data *image, char *const override[])
{
    (void)image; (void)override; errno = ENOSYS; return NULL;
}
/* HW7: start a clean image environment, then apply Env. */
int support_image_environment(struct image_data *image)
{
    (void)image; errno = ENOSYS; return -1;
}
