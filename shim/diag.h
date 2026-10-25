#pragma once
#include <stdint.h>

/* Power-off diagnosis when the bootargs carry "sweetdiag"; returns to boot on. */
void diag_mode(uintptr_t dtb);
