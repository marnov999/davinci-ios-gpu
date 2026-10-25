/*
 * Milestone 3: EL1 stage-1 MMU with the 16K granule XNU uses.
 *
 * T0SZ=28 gives a 36-bit VA whose walk starts at level 2: one 16K table of
 * 2048 x 32MB blocks covers 64GB, identity mapped (VA == PA).
 *
 * Qualcomm XPUs fault on speculative reads of protected carve-outs (TZ,
 * hyp, modem...), so nothing is mapped cacheable except our own image:
 *   - default: Device-nGnRnE, execute-never (same as MMU off)
 *   - the 32MB block(s) holding the image get an L3 table: image pages are
 *     Normal write-back, the rest of the block stays Device
 *   - the splash framebuffer block is Normal non-cacheable (write-combining)
 */
#include <stdint.h>
#include "mmu.h"

#define PG_SHIFT	14
#define PG_SIZE		(1UL << PG_SHIFT)		/* 16K */
#define BLK_SHIFT	25
#define BLK_SIZE	(1UL << BLK_SHIFT)		/* 32MB level-2 block */
#define NENT		2048

#define ATTR_DEV	0	/* MAIR attr0 = 0x00 Device-nGnRnE */
#define ATTR_WB		1	/* MAIR attr1 = 0xff Normal WB RW-alloc */
#define ATTR_NC		2	/* MAIR attr2 = 0x44 Normal non-cacheable */
#define MAIR_VAL	0x44ff00UL

#define D_BLOCK		1UL
#define D_TABLE		3UL
#define D_PAGE		3UL
#define D_ATTR(i)	((uint64_t)(i) << 2)
#define D_SH_OUTER	(2UL << 8)
#define D_SH_INNER	(3UL << 8)
#define D_AF		(1UL << 10)
#define D_PXN		(1UL << 53)
#define D_UXN		(1UL << 54)

#define DEV_FLAGS	(D_ATTR(ATTR_DEV) | D_AF | D_PXN | D_UXN)
#define WB_FLAGS	(D_ATTR(ATTR_WB) | D_SH_INNER | D_AF | D_UXN)
#define NC_FLAGS	(D_ATTR(ATTR_NC) | D_SH_OUTER | D_AF | D_PXN | D_UXN)

/* TCR: T0SZ=28, IRGN0/ORGN0=WBWA, SH0=inner, TG0=16K, EPD1, TG1=16K, IPS=36 bit */
#define TCR_VAL		(28UL | (1UL << 8) | (1UL << 10) | (3UL << 12) | (2UL << 14) | \
			 (28UL << 16) | (1UL << 23) | (1UL << 30) | (1UL << 32))

#define SCTLR_M		(1UL << 0)
#define SCTLR_A		(1UL << 1)
#define SCTLR_C		(1UL << 2)
#define SCTLR_I		(1UL << 12)
#define SCTLR_WXN	(1UL << 19)

#define rsr(r) ({ uint64_t _v; __asm__ volatile("mrs %0, " r : "=r"(_v)); _v; })
#define wsr(r, v) __asm__ volatile("msr " r ", %0" : : "r"((uint64_t)(v)))

extern char _head[], _end[];

/* 1 L2 + up to 2 L3 tables, plus slack to align to 16K at runtime */
static uint64_t pt_pool[4 * NENT] __attribute__((aligned(4096)));

static void dcache_inval_range(uintptr_t start, uintptr_t end)
{
	uint64_t line = 4UL << ((rsr("ctr_el0") >> 16) & 0xf);

	for (uintptr_t a = start & ~(line - 1); a < end; a += line)
		__asm__ volatile("dc ivac, %0" : : "r"(a) : "memory");
	__asm__ volatile("dsb sy" ::: "memory");
}

static void zero_table(uint64_t *t)
{
	for (int i = 0; i < NENT; i++)
		t[i] = 0;
}

int mmu_enable(struct mmu_info *info)
{
	uintptr_t img_lo = (uintptr_t)_head & ~(PG_SIZE - 1);
	uintptr_t img_hi = ((uintptr_t)_end + PG_SIZE - 1) & ~(PG_SIZE - 1);
	uintptr_t pool = ((uintptr_t)pt_pool + PG_SIZE - 1) & ~(PG_SIZE - 1);
	uint64_t *l2 = (uint64_t *)pool;
	int n_l3 = 0;

	info->img_lo = img_lo;
	info->img_hi = img_hi;
	info->ttbr = pool;
	if (((img_hi - 1) >> BLK_SHIFT) - (img_lo >> BLK_SHIFT) > 1)
		return -1;	/* only room for two L3 tables */

	/* L2: Device everywhere RAM or MMIO can be (first 8GB), rest unmapped */
	zero_table(l2);
	for (uint64_t i = 0; i < (8UL << 30) >> BLK_SHIFT; i++)
		l2[i] = (i << BLK_SHIFT) | DEV_FLAGS | D_BLOCK;
	l2[FB_PHYS >> BLK_SHIFT] = (FB_PHYS & ~(BLK_SIZE - 1)) | NC_FLAGS | D_BLOCK;

	/* L3 for each block that holds part of the image */
	for (uint64_t blk = img_lo >> BLK_SHIFT; blk <= (img_hi - 1) >> BLK_SHIFT; blk++) {
		uint64_t *l3 = (uint64_t *)(pool + (1 + n_l3++) * PG_SIZE);
		uint64_t base = blk << BLK_SHIFT;
		for (int i = 0; i < NENT; i++) {
			uint64_t pa = base + ((uint64_t)i << PG_SHIFT);
			int ours = pa >= img_lo && pa < img_hi;
			l3[i] = pa | (ours ? WB_FLAGS : DEV_FLAGS) | D_PAGE;
		}
		l2[blk] = (uintptr_t)l3 | D_TABLE;
	}
	info->n_l3 = n_l3;

	/* Image lines may be stale in the cache from ABL; we wrote memory directly. */
	dcache_inval_range(img_lo, img_hi);
	__asm__ volatile("ic iallu; dsb sy; isb" ::: "memory");

	wsr("mair_el1", MAIR_VAL);
	wsr("tcr_el1", TCR_VAL);
	wsr("ttbr0_el1", pool);
	__asm__ volatile("isb; tlbi vmalle1; dsb nsh; isb" ::: "memory");

	uint64_t sctlr = rsr("sctlr_el1");
	info->sctlr_before = sctlr;
	sctlr &= ~(SCTLR_A | SCTLR_WXN);
	sctlr |= SCTLR_M | SCTLR_C | SCTLR_I;
	wsr("sctlr_el1", sctlr);
	__asm__ volatile("isb" ::: "memory");
	info->sctlr_after = rsr("sctlr_el1");
	return 0;
}

/* Translate a VA with AT S1E1R; returns PAR_EL1. */
uint64_t mmu_probe(uintptr_t va)
{
	__asm__ volatile("at s1e1r, %0; isb" : : "r"(va) : "memory");
	return rsr("par_el1");
}

/*
 * A big copy with the caches on (the Linux hand-off moves ~46 MB; with the MMU off every access is
 * Device-nGnRnE and that took 3.6 s). Only the shim's image and the copy's own ranges are mapped
 * cacheable, page by page -- they are plain RAM -- the rest stays Device as above, so nothing
 * speculates into a carve-out. Afterwards the destinations are cleaned to the point of coherency
 * (arm64 booting.rst: the kernel is entered with the MMU off and the image clean to PoC), the
 * shim's own lines (stack included) cleaned and invalidated, and the MMU and caches switched off
 * again in one sequence with no memory access in between.
 */
#define FC_TABLES	12
static uint64_t fc_pool[(FC_TABLES + 1) * NENT] __attribute__((aligned(PG_SIZE)));

static int fc_cacheable(uint64_t pa, const struct copy_job *j, int n, uintptr_t img_lo, uintptr_t img_hi)
{
	if (pa >= img_lo && pa < img_hi)
		return 1;
	for (int k = 0; k < n; k++)
		if ((pa + PG_SIZE > j[k].src && pa < j[k].src + j[k].len) ||
		    (pa + PG_SIZE > j[k].dst && pa < j[k].dst + j[k].len))
			return 1;
	return 0;
}

int mmu_fast_copy(const struct copy_job *jobs, int n)
{
	uintptr_t img_lo = (uintptr_t)_head & ~(PG_SIZE - 1);
	uintptr_t img_hi = ((uintptr_t)_end + PG_SIZE - 1) & ~(PG_SIZE - 1);
	uintptr_t pool = (uintptr_t)fc_pool;
	uint64_t *l2 = (uint64_t *)pool;
	int n_l3 = 0;

	zero_table(l2);
	for (uint64_t i = 0; i < (8UL << 30) >> BLK_SHIFT; i++)
		l2[i] = (i << BLK_SHIFT) | DEV_FLAGS | D_BLOCK;
	/* only the 32 MB blocks a range touches get an L3 table */
	uint64_t want[2 * 8 + 1][2];
	int nw = 0;
	want[nw][0] = img_lo, want[nw++][1] = img_hi;
	for (int k = 0; k < n && nw < 2 * 8 + 1; k++) {
		want[nw][0] = jobs[k].src, want[nw++][1] = jobs[k].src + jobs[k].len;
		want[nw][0] = jobs[k].dst, want[nw++][1] = jobs[k].dst + jobs[k].len;
	}
	for (uint64_t blk = 0; blk < (8UL << 30) >> BLK_SHIFT; blk++) {
		uint64_t base = blk << BLK_SHIFT;
		int touched = 0;
		for (int w = 0; w < nw && !touched; w++)
			touched = want[w][0] < base + BLK_SIZE && want[w][1] > base;
		if (!touched)
			continue;
		int any = 0;
		for (uint64_t pa = base; pa < base + BLK_SIZE && !any; pa += PG_SIZE)
			any = fc_cacheable(pa, jobs, n, img_lo, img_hi);
		if (!any)
			continue;
		if (n_l3 == FC_TABLES)
			return -1;
		uint64_t *l3 = (uint64_t *)(pool + (1 + n_l3++) * PG_SIZE);
		for (int i = 0; i < NENT; i++) {
			uint64_t pa = base + ((uint64_t)i << PG_SHIFT);
			l3[i] = pa | (fc_cacheable(pa, jobs, n, img_lo, img_hi) ? WB_FLAGS : DEV_FLAGS) | D_PAGE;
		}
		l2[blk] = (uintptr_t)l3 | D_TABLE;
	}

	/* nothing of ours may sit stale in the cache: we wrote memory with the MMU off */
	dcache_inval_range(img_lo, img_hi);
	for (int k = 0; k < n; k++) {
		dcache_inval_range(jobs[k].src, jobs[k].src + jobs[k].len);
		dcache_inval_range(jobs[k].dst, jobs[k].dst + jobs[k].len);
	}
	__asm__ volatile("ic iallu; dsb sy; isb" ::: "memory");
	wsr("mair_el1", MAIR_VAL);
	wsr("tcr_el1", TCR_VAL);
	wsr("ttbr0_el1", pool);
	__asm__ volatile("isb; tlbi vmalle1; dsb nsh; isb" ::: "memory");
	uint64_t sctlr = rsr("sctlr_el1");
	wsr("sctlr_el1", (sctlr & ~(SCTLR_A | SCTLR_WXN)) | SCTLR_M | SCTLR_C | SCTLR_I);
	__asm__ volatile("isb" ::: "memory");

	for (int k = 0; k < n; k++) {
		volatile uint64_t *d = (volatile uint64_t *)jobs[k].dst;
		const volatile uint64_t *s = (const volatile uint64_t *)jobs[k].src;
		for (uint64_t i = 0; i < (jobs[k].len + 7) / 8; i++)
			d[i] = s[i];
	}

	uint64_t line = 4UL << ((rsr("ctr_el0") >> 16) & 0xf);
	for (int k = 0; k < n; k++)
		for (uintptr_t a = jobs[k].dst & ~(line - 1); a < jobs[k].dst + jobs[k].len; a += line)
			__asm__ volatile("dc cvac, %0" : : "r"(a) : "memory");
	/* the shim's own lines (stack, tables) back to memory, then MMU and caches off at once */
	__asm__ volatile(
		"	dsb	sy\n"
		"1:	dc	civac, %[a]\n"
		"	add	%[a], %[a], %[l]\n"
		"	cmp	%[a], %[e]\n"
		"	b.lo	1b\n"
		"	dsb	sy\n"
		"	mrs	x9, sctlr_el1\n"
		"	bic	x9, x9, #1\n"		/* M */
		"	bic	x9, x9, #4\n"		/* C */
		"	bic	x9, x9, #0x1000\n"	/* I */
		"	msr	sctlr_el1, x9\n"
		"	isb\n"
		"	ic	iallu\n"
		"	dsb	sy\n"
		"	isb\n"
		: [a] "+r"(img_lo)
		: [l] "r"(line), [e] "r"(img_hi)
		: "x9", "memory");
	return 0;
}
