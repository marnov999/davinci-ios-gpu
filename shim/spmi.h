#pragma once
#include <stdint.h>

/* The PMICs over the SPMI arbiter (see spmi.c). ppid = sid << 8 | peripheral. */
int spmi_apid(unsigned ppid);
int spmi_rd(int apid, unsigned reg, uint8_t *out);
int spmi_wr(int apid, unsigned reg, uint8_t val);
/* PON PS_HOLD reset type "shutdown", PS_HOLD dropped: the phone switches off. */
void __attribute__((noreturn)) spmi_power_off(void);

void delay_ms(unsigned ms);
void sleep_ms(unsigned ms);

#define PPID_PON	0x008	/* PM6150 power-on: RT_STS bit 0 power key, bit 1 volume down */
#define PPID_VOLUP	0x4c1	/* PM6150L GPIO2: RT_STS bit 0 low while volume up is held */
#define PPID_USBIN	0x013	/* PM6150 charger usb input: RT_STS bit 4 plugged */
#define PMIC_RT_STS	0x10
