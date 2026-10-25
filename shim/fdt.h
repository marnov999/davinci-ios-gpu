#pragma once
#include <stdint.h>

/* Read a u32/u64 (cell-size agnostic) property of /chosen. Returns 0 if absent. */
int fdt_chosen_u64(uintptr_t fdt, const char *prop, uint64_t *out);
/* Does the /chosen string property prop contain word? 0 if not or absent. */
int fdt_chosen_has(uintptr_t fdt, const char *prop, const char *word);
/* The tree rebuilt at dst for a Linux kernel: bootargs and initrd replaced. New size, 0 on error. */
uint32_t fdt_rebuild_for_linux(uintptr_t src, uintptr_t dst, const char *cmdline, uint64_t rd_lo, uint64_t rd_hi,
    uint64_t oops_base, uint64_t oops_size);
/* A /chosen string property into out (NUL-terminated); its length, 0 if absent. */
uint32_t fdt_chosen_str(uintptr_t fdt, const char *prop, char *out, uint32_t max);
uint32_t fdt_size(uintptr_t fdt);
