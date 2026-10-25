#pragma once

/* The battery: percent (estimated), millivolts, mA (+ charging); 0 if read. */
int battery_read(unsigned *percent, unsigned *mv, int *ma);
