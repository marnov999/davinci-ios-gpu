#pragma once
#include <stdint.h>

#define PANEL_LEVEL_ON	0x218	/* the panel's dt bl-default-level */

/* The panel's brightness (0..2047; 0 = dark) by a DCS command; 0 if it was sent. */
int panel_brightness(uint32_t level);
