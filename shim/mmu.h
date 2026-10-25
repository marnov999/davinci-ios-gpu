#pragma once
#include <stdint.h>

#define FB_PHYS	0x9c000000UL

struct mmu_info {
	uint64_t img_lo, img_hi, ttbr;
	uint64_t sctlr_before, sctlr_after;
	int n_l3;
};

int mmu_enable(struct mmu_info *info);
uint64_t mmu_probe(uintptr_t va);

/* Copies done with the caches on, left clean in memory, the MMU off again. 0, or -1 (nothing done). */
struct copy_job {
	uint64_t dst, src, len;
};
int mmu_fast_copy(const struct copy_job *jobs, int n);
