#pragma once
#include <stdint.h>

/* Is an Android kernel packed behind the XNU payload? */
int linux_present(uintptr_t dtb);
/* Start it as ABL would (returns only on error, with the reason). */
const char *linux_boot(uintptr_t dtb);
