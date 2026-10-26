/*
 * Boot menu, at every power-on that is not a charger's: "Boot iOS / Boot MIUI / Power off" on a black
 * screen. Volume up and down move (and stop the countdown), power picks; with no key for 10 s the
 * phone boots iOS. A power key still held from switching the phone on counts only once let go. Keys
 * over SPMI as bsd/dev/sweet_keys.c reads them. Without readable keys: iOS at once.
 */
#include "menu.h"
#include "console.h"
#include "spmi.h"

#define BLACK		0xff000000U
#define GREY		0xff6e6e73U
#define DIM		0xff3a3a3cU
#define TIMEOUT_MS	10000
#define TICK_MS		20

#define ITEM_X		120
#define ITEM_Y0		980
#define ITEM_DY		170
#define ITEM_SCALE	5		/* 40 x 80 px a character */

static void item(int i, int sel, int have_miui)
{
	/* (no table of pointers: the shim is not relocated, and those would be absolute addresses) */
	const char *name = i == BOOT_IOS ? "Boot iOS" : i == BOOT_MIUI ? "Boot MIUI" : "Power off";
	int y = ITEM_Y0 + i * ITEM_DY;
	int off = i == BOOT_MIUI && !have_miui;
	con_rect(0, y - 30, FB_W, 80 * 1 + 60, BLACK);
	if (i == sel)
		con_rect(ITEM_X - 60, y + 20, 24, 40, WHITE);
	con_text(ITEM_X, y, name, ITEM_SCALE, off ? DIM : (i == sel ? WHITE : GREY), BLACK);
	if (off)
		con_text(ITEM_X, y + 84, "needs its own data partition", 2, DIM, BLACK);
}

static void footer(int left_s)
{
	char line[40] = "vol: move   power: select";
	con_rect(0, 1600, FB_W, 120, BLACK);
	con_text(ITEM_X, 1620, line, 3, GREY, BLACK);
	if (left_s > 0) {
		char c[24] = "iOS in 0 s";
		c[7] = (char)('0' + left_s);
		con_text(ITEM_X, 1680, c, 3, GREY, BLACK);
	}
}

enum boot_choice boot_menu(int have_miui)
{
	int pon = spmi_apid(PPID_PON), volup = spmi_apid(PPID_VOLUP);
	uint8_t p, g = 1;
	if (spmi_rd(pon, PMIC_RT_STS, &p) != 0)
		return BOOT_IOS;
	int sel = BOOT_IOS, waited = 0, counting = 1, last_s = -1;
	int pw_was = 1, dn_was = 1, up_was = 1;		/* a key down at the start counts once let go */
	con_clear(BLACK);
	for (int i = 0; i < 3; i++)
		item(i, sel, have_miui);
	for (;;) {
		int s = counting ? (TIMEOUT_MS - waited + 999) / 1000 : 0;
		if (s != last_s) {
			footer(s);
			last_s = s;
		}
		sleep_ms(TICK_MS);
		if (spmi_rd(pon, PMIC_RT_STS, &p) != 0)
			continue;
		if (volup >= 0 && spmi_rd(volup, PMIC_RT_STS, &g) != 0)
			g = 1;
		int pw = p & 1, dn = !!(p & 2), up = volup >= 0 ? !(g & 1) : 0;
		int old = sel;
		if (up && !up_was)
			sel = sel > 0 ? sel - 1 : 2;
		if (dn && !dn_was)
			sel = sel < 2 ? sel + 1 : 0;
		if (sel != old) {
			counting = 0;
			item(old, sel, have_miui);
			item(sel, sel, have_miui);
		}
		if (pw && !pw_was && (sel != BOOT_MIUI || have_miui)) {
			con_clear(BLACK);
			return (enum boot_choice)sel;
		}
		pw_was = pw;
		dn_was = dn;
		up_was = up;
		if (counting && (waited += TICK_MS) >= TIMEOUT_MS) {
			con_clear(BLACK);
			return BOOT_IOS;
		}
	}
}
