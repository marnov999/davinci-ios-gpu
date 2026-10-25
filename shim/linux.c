/*
 * MIUI's own kernel, started in ABL's place: what turns a charger-woken phone into MIUI's
 * off-mode charging (its battery picture, its percentage, off at unplug), and later the boot
 * menu's "Boot MIUI". tools/mkcombo.py packs, behind the XNU payload in the ramdisk, the
 * uncompressed arm64 Image, its ramdisk and command line, described by a trailer page at the
 * ramdisk's end ("SWEETLNX"). Here: the Image to a 2 MB-aligned address + text_offset in free RAM
 * above the carve-outs, the ramdisk and a rebuilt tree after it -- bootargs = MIUI's command line
 * + what ABL added to ours, initrd = the moved ramdisk -- then the jump with x0 = the tree, MMU
 * and caches off (arm64 booting.rst), as ABL does it.
 */
#include "linux.h"
#include "console.h"
#include "fdt.h"
#include "mmu.h"
#include "oops.h"

struct lnx_trailer {
	char magic[8];			/* "SWEETLNX" */
	uint64_t image_off, image_size;	/* from the ramdisk's start */
	uint64_t rd_off, rd_size;
	uint32_t cmdline_len;
	char cmdline[2048];
};

#define TRAILER_SIZE	4096
#define LOAD_BASES	2
static const uint64_t load_base[LOAD_BASES] = { 0xc0000000ULL, 0x140000000ULL };
#define SZ_2M		0x200000ULL

static char bootargs[4096];

static const volatile struct lnx_trailer *trailer(uintptr_t dtb, uint64_t *rd_lo, uint64_t *rd_hi)
{
	if (!fdt_chosen_u64(dtb, "linux,initrd-start", rd_lo) || !fdt_chosen_u64(dtb, "linux,initrd-end", rd_hi) ||
	    *rd_hi < *rd_lo + TRAILER_SIZE)
		return 0;
	const volatile struct lnx_trailer *t = (const volatile struct lnx_trailer *)(uintptr_t)(*rd_hi - TRAILER_SIZE);
	static const char want[] = "SWEETLNX";
	for (int i = 0; i < 8; i++)
		if (t->magic[i] != want[i])
			return 0;
	if (t->image_off + t->image_size > *rd_hi - *rd_lo || t->rd_off + t->rd_size > *rd_hi - *rd_lo ||
	    t->cmdline_len >= sizeof(t->cmdline))
		return 0;
	return t;
}

int linux_present(uintptr_t dtb)
{
	uint64_t lo, hi;
	return trailer(dtb, &lo, &hi) != 0;
}

static int overlaps(uint64_t a, uint64_t an, uint64_t b, uint64_t bn)
{
	return a < b + bn && b < a + an;
}

static void copy64(uint64_t dst, uint64_t src, uint64_t n)
{
	for (uint64_t i = 0; i < n; i += 8)
		*(volatile uint64_t *)(uintptr_t)(dst + i) = *(volatile uint64_t *)(uintptr_t)(src + i);
}

extern char _head[], _end[];

static uint32_t append_hex(char *buf, uint32_t n, uint32_t max, const char *label, uint64_t v)
{
	static const char hex[] = "0123456789abcdef";
	for (; *label && n + 1 < max; label++)
		buf[n++] = *label;
	for (int s = 60; s >= 0 && n + 1 < max; s -= 4)
		buf[n++] = hex[(v >> s) & 0xf];
	return n;
}

typedef void (*linux_entry_t)(uint64_t dtb, uint64_t x1, uint64_t x2, uint64_t x3);

const char *linux_boot(uintptr_t dtb)
{
	uint64_t rd_lo, rd_hi;
	const volatile struct lnx_trailer *t = trailer(dtb, &rd_lo, &rd_hi);
	if (!t)
		return "no SWEETLNX kernel";
	uint64_t img = rd_lo + t->image_off;
	if (*(volatile uint32_t *)(uintptr_t)(img + 56) != 0x644d5241)	/* "ARMd" */
		return "not an arm64 Image";
	uint64_t text_offset = *(volatile uint64_t *)(uintptr_t)(img + 8);
	uint64_t image_size = *(volatile uint64_t *)(uintptr_t)(img + 16);
	if (image_size < t->image_size)
		image_size = t->image_size;
	uint64_t span = ((text_offset + image_size + SZ_2M - 1) & ~(SZ_2M - 1)) + /* Image */
			((t->rd_size + SZ_2M - 1) & ~(SZ_2M - 1)) + SZ_2M;	     /* ramdisk, tree */
	uint64_t dtb_size = fdt_size(dtb), shim_lo = (uintptr_t)_head, shim_n = (uintptr_t)_end - (uintptr_t)_head;
	uint64_t base = 0;
	for (int i = 0; i < LOAD_BASES && !base; i++) {
		uint64_t b = load_base[i];
		if (!overlaps(b, span, rd_lo, rd_hi - rd_lo) && !overlaps(b, span, dtb, dtb_size + 0x10000) &&
		    !overlaps(b, span, shim_lo, shim_n) && !overlaps(b, span, FB_BASE, 0x1800000))
			base = b;
	}
	if (!base)
		return "no free place for the kernel";
	uint64_t kernel = base + text_offset;
	uint64_t rd = (base + text_offset + image_size + SZ_2M - 1) & ~(SZ_2M - 1);
	uint64_t tree = (rd + t->rd_size + SZ_2M - 1) & ~(SZ_2M - 1);

	/* bootargs: MIUI's command line, then what ABL appended to ours (after our own words) */
	char abl[2048];
	uint32_t n = 0, i = 0;
	for (; i < t->cmdline_len && n + 1 < sizeof(bootargs); i++)
		bootargs[n++] = t->cmdline[i];
	uint32_t alen = fdt_chosen_str(dtb, "bootargs", abl, sizeof(abl));
	/* ABL puts the image's own cmdline first; skip ours ("console=null sweet...") word by word */
	uint32_t a = 0;
	while (a < alen) {
		while (a < alen && abl[a] == ' ')
			a++;
		uint32_t w = a;
		while (a < alen && abl[a] != ' ')
			a++;
		int mine = (a - w >= 12 && abl[w] == 'c' && abl[w + 1] == 'o' && abl[w + 7] == '=' &&
			    abl[w + 8] == 'n' && abl[w + 11] == 'l') ||			/* console=null */
			   (a - w >= 5 && abl[w] == 's' && abl[w + 1] == 'w' && abl[w + 2] == 'e' &&
			    abl[w + 3] == 'e' && abl[w + 4] == 't');			/* sweet* */
		if (!mine && a > w && n + 1 + (a - w) + 1 < sizeof(bootargs)) {
			bootargs[n++] = ' ';
			for (uint32_t k = w; k < a; k++)
				bootargs[n++] = abl[k];
		}
	}
	bootargs[n] = 0;

	struct copy_job jobs[2] = {
		{ kernel, img, (t->image_size + 7) & ~7ULL },
		{ rd, rd_lo + t->rd_off, (t->rd_size + 7) & ~7ULL },
	};
	if (mmu_fast_copy(jobs, 2) != 0) {		/* (more tables than it has: the slow way) */
		copy64(kernel, img, jobs[0].len);
		copy64(rd, rd_lo + t->rd_off, jobs[1].len);
	}
	/* timer stamps for /proc/cmdline: shim entry and hand-off (ticks since the SoC came on), tick rate */
	{
		extern uint64_t shim_t0;
		uint64_t tc, f;
		__asm__ volatile("isb; mrs %0, cntpct_el0; mrs %1, cntfrq_el0" : "=r"(tc), "=r"(f));
		n = append_hex(bootargs, n, sizeof(bootargs), " sweet.t0=", shim_t0);
		n = append_hex(bootargs, n, sizeof(bootargs), " sweet.tc=", tc);
		n = append_hex(bootargs, n, sizeof(bootargs), " sweet.hz=", f);
		bootargs[n] = 0;
	}
	#ifdef SWEET_TIMING
#ifndef SWEET_OOPS
	uint64_t ob = 0, os = 0;		/* (a ramoops node stops MIUI's kernel: off unless asked) */
#else
	uint64_t ob = OOPS_BASE, os = OOPS_SIZE;
#endif
	if (overlaps(ob, os, rd_lo, rd_hi - rd_lo) || overlaps(ob, os, dtb, dtb_size + 0x10000) || overlaps(ob, os, shim_lo, shim_n))
		ob = os = 0;
#else
	uint64_t ob = 0, os = 0;
#endif
	uint32_t tsize = fdt_rebuild_for_linux(dtb, (uintptr_t)tree, bootargs, rd, rd + t->rd_size, ob, os);
	if (!tsize)
		return "tree not rebuilt";
#ifdef SWEET_TIMING
	{	/* measuring build: the times on screen for 2 s before the hand-off */
		extern uint64_t shim_t0;
		uint64_t tc, f;
		__asm__ volatile("isb; mrs %0, cntpct_el0; mrs %1, cntfrq_el0" : "=r"(tc), "=r"(f));
		char l1[40] = "power-on to shim  00.0 s", l2[40] = "shim              0.00 s";
		char l3[48] = "ramdisk 000000000-000000000 log 0";
		static const char hx[] = "0123456789abcdef";
		for (int i = 0; i < 9; i++) {
			l3[8 + i] = hx[(rd_lo >> (32 - 4 * i)) & 0xf];
			l3[18 + i] = hx[(rd_hi >> (32 - 4 * i)) & 0xf];
		}
		l3[32] = os ? '1' : '0';
		uint64_t a10 = shim_t0 * 10 / f, s100 = (tc - shim_t0) * 100 / f;
		l1[18] = (char)('0' + a10 / 100 % 10);
		l1[19] = (char)('0' + a10 / 10 % 10);
		l1[21] = (char)('0' + a10 % 10);
		l2[18] = (char)('0' + s100 / 100 % 10);
		l2[20] = (char)('0' + s100 / 10 % 10);
		l2[21] = (char)('0' + s100 % 10);
		con_clear(0xff000000U);
		con_text(60, 900, l1, 4, 0xffffffffU, 0xff000000U);
		con_text(60, 1000, l2, 4, 0xffffffffU, 0xff000000U);
		con_text(60, 1100, l3, 3, 0xffffffffU, 0xff000000U);
		for (volatile uint64_t end = tc + 2 * f, now = tc; now < end;)
			__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(now));
		con_clear(0xff000000U);
	}
#endif

	__asm__ volatile("dsb sy; ic iallu; dsb sy; isb" ::: "memory");
	((linux_entry_t)(uintptr_t)kernel)(tree, 0, 0, 0);
	return "linux returned";
}
