#pragma once
#include <stdint.h>

/* Off-mode charging: returns when iOS should boot (or at once when ABL did not boot for a charger). */
void charge_mode(uintptr_t dtb);
