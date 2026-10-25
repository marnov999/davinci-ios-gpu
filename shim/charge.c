/*
 * Off-mode charging. A charger plugged into a switched-off phone -- and switching the phone off
 * with the charger in, since the PMIC powers it straight back on then (PON reason USB charger) --
 * makes ABL boot the boot partition with androidboot.mode=charger in /chosen/bootargs. That is
 * MIUI's own charger mode, 1:1: its kernel and ramdisk (packed behind the XNU payload, linux.c)
 * started with that word, which run its battery picture and percentage, its power key, and its
 * power-off at unplug. Without them: a black screen until the power key is held 1 s (iOS) or the
 * charger is gone 2 s (off).
 *
 * Also undoes an earlier experiment: PON TRIGGER_EN bit 4 (USB_CHG) cleared, which did not keep
 * the charger from waking the phone; any boot puts it back.
 */
#include "charge.h"
#include "console.h"
#include "fdt.h"
#include "linux.h"
#include "spmi.h"

#define PON_TRIGGER_EN		0x80
#define PON_TRIGGER_USB_CHG	0x10
#define USBIN_PLUGIN		0x10

void charge_mode(uintptr_t dtb)
{
	int pon = spmi_apid(PPID_PON), usb = spmi_apid(PPID_USBIN);
	uint8_t v, trig;
	if (spmi_rd(pon, PON_TRIGGER_EN, &trig) == 0 && !(trig & PON_TRIGGER_USB_CHG))
		(void)spmi_wr(pon, PON_TRIGGER_EN, trig | PON_TRIGGER_USB_CHG);
	if (!fdt_chosen_has(dtb, "bootargs", "androidboot.mode=charger"))
		return;
	if (linux_present(dtb)) {
		const char *why = linux_boot(dtb);
		con_clear(0xff000000U);
		con_str("CHARGER", why);			/* only if MIUI's kernel could not start */
		delay_ms(3000);
	}
	if (spmi_rd(pon, PMIC_RT_STS, &v) != 0)
		return;
	con_clear(0xff000000U);
	unsigned held = 0, gone = 0;
	for (;;) {
		sleep_ms(50);
		if (spmi_rd(pon, PMIC_RT_STS, &v) == 0 && (v & 1)) {
			if (++held >= 20)			/* 1 s */
				break;
		} else {
			held = 0;
		}
		if (spmi_rd(usb, PMIC_RT_STS, &v) == 0 && !(v & USBIN_PLUGIN)) {
			if (++gone >= 40)			/* 2 s */
				spmi_power_off();
		} else {
			gone = 0;
		}
	}
	con_clear(0xff000000U);
}
