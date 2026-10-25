/*
 * Power-off diagnosis (bootargs word "sweetdiag", from a fastboot-booted image's cmdline): the
 * PON registers on screen, the reset type and USB trigger written and read back, then power
 * key = switch off (spmi_power_off), volume down = boot on. Nothing is left changed but the
 * reset type, which a boot of Linux or our kernel sets again anyway.
 */
#include "diag.h"
#include "console.h"
#include "fdt.h"
#include "spmi.h"

static void show(const char *label, int pon, unsigned a, unsigned b)
{
	uint8_t va = 0xee, vb = 0xee;
	int ra = spmi_rd(pon, a, &va), rb = spmi_rd(pon, b, &vb);
	con_hex2(label, "a=", ra ? 0xdead0000U | a : (a << 8) | va, "b=", rb ? 0xdead0000U | b : (b << 8) | vb);
}

void diag_mode(uintptr_t dtb)
{
	if (!fdt_chosen_has(dtb, "bootargs", "sweetdiag"))
		return;
	int pon = spmi_apid(PPID_PON);
	con_clear(0xff000000U);
	con_str("DIAG", "PON registers (reg<<8 | value)");
	con_hex2("APID", "pon=", (uint32_t)pon, "usb=", (uint32_t)spmi_apid(PPID_USBIN));
	show("RSTCTL", pon, 0x5a, 0x5b);
	show("TRIG", pon, 0x80, 0xd0);
	show("PONRSN", pon, 0xc0, 0xc1);
	show("WARMRS", pon, 0xc2, 0xc3);
	show("POFFRS", pon, 0xc5, 0xc6);
	show("FAULT", pon, 0xc8, 0xc9);
	show("S3RST", pon, 0xca, 0xcb);
	show("SPARE", pon, 0x8c, 0x8f);
	con_skip();
	uint8_t ctl = 0, ctl2 = 0, trig = 0;
	(void)spmi_rd(pon, 0x5a, &ctl);
	(void)spmi_rd(pon, 0x5b, &ctl2);
	int w1 = spmi_wr(pon, 0x5b, ctl2 & ~0x80);
	delay_ms(1);
	int w2 = spmi_wr(pon, 0x5a, (ctl & 0xf0) | 0x04);
	int w3 = spmi_wr(pon, 0x5b, ctl2 | 0x80);
	con_hex2("WRITES", "w1w2=", (uint32_t)((w1 & 0xff) << 8 | (w2 & 0xff)), "w3=", (uint32_t)w3);
	show("AFTER", pon, 0x5a, 0x5b);
	(void)spmi_rd(pon, 0x80, &trig);
	int w4 = spmi_wr(pon, 0x80, trig & ~0x10);
	show("TRIG-", pon, 0x80, 0x80);
	int w5 = spmi_wr(pon, 0x80, trig);
	con_hex2("TRIGW", "w4=", (uint32_t)w4, "w5=", (uint32_t)w5);
	show("TRIG=", pon, 0x80, 0x80);
	con_skip();
	con_str("KEYS", "power: switch off   vol-down: boot");
	uint8_t v;
	int was = 1;
	for (;;) {
		sleep_ms(20);
		if (spmi_rd(pon, 0x10, &v) != 0)
			continue;
		if ((v & 1) && !was)
			spmi_power_off();
		if (v & 2)
			break;
		was = v & 1;
	}
	con_clear(0xff000000U);
}
