/*
 * The log MIUI's kernel left in its ramoops console zone (fs/pstore/ram.c: the dump records first,
 * then the console zone, a persistent_ram_buffer {sig "DBGC", start, size, data[]}, a ring): its
 * lines with printk time stamps "[    s.uuuuuu]" read back, and the six longest pauses between two
 * of them shown with the lines either side, plus the last line -- where a charger boot loses its
 * seconds. The zone is then marked read, so it shows once.
 */
#include "oops.h"
#include "console.h"

#define PRZ_SIG		0x43474244U	/* "DBGC" */
#define TOP		6
#define LINE		66
#define SCRATCH		0xc0000000UL	/* free RAM at this point of a boot: the log made linear there */

static inline uint32_t rd32(uintptr_t a) { return *(volatile uint32_t *)a; }

static int stamp(const char *p, const char *end, uint64_t *us)
{
	if (p >= end || *p != '[')
		return 0;
	p++;
	while (p < end && *p == ' ')
		p++;
	uint64_t s = 0, u = 0;
	int ds = 0, du = 0;
	while (p < end && *p >= '0' && *p <= '9' && ds < 6)
		s = s * 10 + (uint64_t)(*p++ - '0'), ds++;
	if (!ds || p >= end || *p++ != '.')
		return 0;
	while (p < end && *p >= '0' && *p <= '9' && du < 6)
		u = u * 10 + (uint64_t)(*p++ - '0'), du++;
	if (du != 6 || p >= end || *p != ']')
		return 0;
	*us = s * 1000000 + u;
	return 1;
}

static void show_line(int y, const char *l, const char *end, uint32_t fg)
{
	char buf[LINE + 1];
	int n = 0;
	while (l < end && *l != '\n' && n < LINE) {
		char c = *l++;
		buf[n++] = (c >= 0x20 && c <= 0x7e) ? c : '.';
	}
	buf[n] = 0;
	con_text(8, y, buf, 2, fg, 0xff000000U);
}

static void secs(char *out, uint64_t us)		/* "SS.ss" */
{
	uint64_t c = us / 10000;
	out[0] = (char)('0' + c / 1000 % 10);
	out[1] = (char)('0' + c / 100 % 10);
	out[2] = '.';
	out[3] = (char)('0' + c / 10 % 10);
	out[4] = (char)('0' + c % 10);
	out[5] = 0;
}

void oops_report(void)
{
	uintptr_t z = (uintptr_t)(OOPS_BASE + OOPS_SIZE - OOPS_CONSOLE - OOPS_PMSG);
	if (rd32(z) != PRZ_SIG) {
		/* say so, with what is there instead: written over, or never written */
		char l[48] = "no MIUI log: sig 00000000 size 00000000";
		static const char hex[] = "0123456789abcdef";
		uint32_t s = rd32(z), sz = rd32(z + 8);
		for (int i = 0; i < 8; i++) {
			l[17 + i] = hex[(s >> (28 - 4 * i)) & 0xf];
			l[31 + i] = hex[(sz >> (28 - 4 * i)) & 0xf];
		}
		con_clear(0xff000000U);
		con_text(8, 900, l, 3, 0xffffffffU, 0xff000000U);
		uint64_t f0, a0, b0;
		__asm__ volatile("isb; mrs %0, cntfrq_el0; mrs %1, cntpct_el0" : "=r"(f0), "=r"(a0));
		do
			__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(b0));
		while (b0 < a0 + 3 * f0);
		con_clear(0xff000000U);
		return;
	}
	uint32_t cap = OOPS_CONSOLE - 12, start = rd32(z + 4), size = rd32(z + 8);
	if (size > cap || start > cap)
		return;
	char *buf = (char *)SCRATCH;
	uint32_t n = 0;
	if (size == cap)				/* wrapped: oldest from start on */
		for (uint32_t i = start; i < cap; i++)
			buf[n++] = *(volatile char *)(z + 12 + i);
	for (uint32_t i = 0; i < (size == cap ? start : size); i++)
		buf[n++] = *(volatile char *)(z + 12 + i);
	const char *end = buf + n;

	uint64_t gap[TOP] = {0}, prev_us = 0, first_us = 0, last_us = 0;
	const char *before[TOP] = {0}, *after[TOP] = {0}, *prev = 0, *last = 0;
	for (const char *l = buf; l < end;) {
		uint64_t us;
		if (stamp(l, end, &us)) {
			if (!last)
				first_us = us;
			if (prev && us > prev_us) {
				uint64_t g = us - prev_us;
				for (int k = 0; k < TOP; k++)
					if (g > gap[k]) {
						for (int m = TOP - 1; m > k; m--)
							gap[m] = gap[m - 1], before[m] = before[m - 1], after[m] = after[m - 1];
						gap[k] = g, before[k] = prev, after[k] = l;
						break;
					}
			}
			prev = l, prev_us = us, last = l, last_us = us;
		}
		while (l < end && *l != '\n')
			l++;
		l++;
	}
	con_clear(0xff000000U);
	char t[8], hdr[64] = "MIUI log: first  00.00 s  last  00.00 s";
	secs(t, first_us);
	for (int i = 0; i < 5; i++) hdr[17 + i] = t[i];
	secs(t, last_us);
	for (int i = 0; i < 5; i++) hdr[32 + i] = t[i];
	con_text(8, 40, hdr, 3, 0xffffff00U, 0xff000000U);
	int y = 110;
	for (int k = 0; k < TOP && before[k]; k++) {
		char g[16] = "pause 00.00 s";
		secs(t, gap[k]);
		for (int i = 0; i < 5; i++) g[6 + i] = t[i];
		con_text(8, y, g, 2, 0xffffff00U, 0xff000000U);
		show_line(y + 34, before[k], end, 0xffa0a0a0U);
		show_line(y + 68, after[k], end, 0xffffffffU);
		y += 116;
	}
	if (last)
		show_line(y + 10, last, end, 0xff80ff80U);
	*(volatile uint32_t *)z = 0;			/* shown once */
	uint64_t f, t0, now;
	__asm__ volatile("isb; mrs %0, cntfrq_el0; mrs %1, cntpct_el0" : "=r"(f), "=r"(t0));
	do
		__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(now));
	while (now < t0 + 15 * f);
	con_clear(0xff000000U);
}
