/*
 * Just enough flattened-device-tree parsing to find what ABL put in
 * /chosen (initrd location, bootargs). Big-endian, 4-byte aligned tokens.
 */
#include "fdt.h"
#include "oops.h"

#define FDT_MAGIC	0xd00dfeed
#define FDT_BEGIN_NODE	1
#define FDT_END_NODE	2
#define FDT_PROP	3
#define FDT_NOP		4
#define FDT_END		9

static uint32_t be32(uintptr_t a)
{
	return __builtin_bswap32(*(volatile uint32_t *)a);
}

static int streq(const char *a, const char *b)
{
	while (*a && *a == *b)
		a++, b++;
	return *a == *b;
}

static uintptr_t align4(uintptr_t a)
{
	return (a + 3) & ~3UL;
}

static uintptr_t skip_str(uintptr_t p)
{
	/* byte loads are fine on Device memory as long as they are aligned to 1 */
	while (*(volatile char *)p)
		p++;
	return p + 1;
}

/* A /chosen property's value and length: 1 if found. */
static int chosen_prop(uintptr_t fdt, const char *prop, uintptr_t *val_out, uint32_t *len_out)
{
	if (!fdt || be32(fdt) != FDT_MAGIC)
		return 0;
	uintptr_t p = fdt + be32(fdt + 8);		/* off_dt_struct */
	uintptr_t strings = fdt + be32(fdt + 12);	/* off_dt_strings */
	int depth = 0, in_chosen = 0;

	for (;;) {
		uint32_t tok = be32(p);
		p += 4;
		switch (tok) {
		case FDT_BEGIN_NODE: {
			const char *name = (const char *)p;
			depth++;
			in_chosen = depth == 2 && streq(name, "chosen");
			p = align4(skip_str(p));
			break;
		}
		case FDT_END_NODE:
			if (in_chosen)
				return 0;
			depth--;
			break;
		case FDT_PROP: {
			uint32_t len = be32(p), nameoff = be32(p + 4);
			uintptr_t val = p + 8;
			if (in_chosen && streq((const char *)(strings + nameoff), prop)) {
				*val_out = val;
				*len_out = len;
				return 1;
			}
			p = align4(val + len);
			break;
		}
		case FDT_NOP:
			break;
		default:	/* FDT_END or garbage */
			return 0;
		}
	}
}

int fdt_chosen_has(uintptr_t fdt, const char *prop, const char *word)
{
	uintptr_t v;
	uint32_t len;
	if (!chosen_prop(fdt, prop, &v, &len))
		return 0;
	for (uint32_t i = 0; i < len; i++) {
		uint32_t k = 0;
		while (word[k] && i + k < len && *(volatile char *)(v + i + k) == word[k])
			k++;
		if (!word[k])
			return 1;
	}
	return 0;
}

int fdt_chosen_u64(uintptr_t fdt, const char *prop, uint64_t *out)
{
	if (!fdt || be32(fdt) != FDT_MAGIC)
		return 0;
	uintptr_t p = fdt + be32(fdt + 8);		/* off_dt_struct */
	uintptr_t strings = fdt + be32(fdt + 12);	/* off_dt_strings */
	int depth = 0, in_chosen = 0;

	for (;;) {
		uint32_t tok = be32(p);
		p += 4;
		switch (tok) {
		case FDT_BEGIN_NODE: {
			const char *name = (const char *)p;
			depth++;
			in_chosen = depth == 2 && streq(name, "chosen");
			p = align4(skip_str(p));
			break;
		}
		case FDT_END_NODE:
			if (in_chosen)
				return 0;
			depth--;
			break;
		case FDT_PROP: {
			uint32_t len = be32(p), nameoff = be32(p + 4);
			uintptr_t val = p + 8;
			if (in_chosen && streq((const char *)(strings + nameoff), prop)) {
				if (len == 4)
					*out = be32(val);
				else if (len == 8)
					*out = (uint64_t)be32(val) << 32 | be32(val + 4);
				else
					return 0;
				return 1;
			}
			p = align4(val + len);
			break;
		}
		case FDT_NOP:
			break;
		default:	/* FDT_END or garbage */
			return 0;
		}
	}
}

/* clang (unlike gcc) turns ufs.c's __builtin_strcmp into a call: the one libc routine the shim needs. */
int strcmp(const char *a, const char *b)
{
	while (*a && *a == *b)
		a++, b++;
	return (unsigned char)*a - (unsigned char)*b;
}

static void put_be32(uintptr_t a, uint32_t v)
{
	*(volatile uint32_t *)a = __builtin_bswap32(v);
}

static uintptr_t copy_bytes(uintptr_t dst, uintptr_t src, uint32_t n)
{
	for (uint32_t i = 0; i < n; i++)
		*(volatile char *)(dst + i) = *(volatile char *)(src + i);
	return dst + n;
}

/*
 * The tree again at dst with /chosen's bootargs replaced by cmdline and linux,initrd-start/end set
 * to [rd_lo, rd_hi) (both as 8-byte cells, the way ABL writes them for Linux): what a Linux kernel
 * started in ABL's place expects. With oops_size, also a /reserved-memory/ramoops node there (the
 * kernel's pstore keeps its log in it across a warm reset). Returns the new total size, 0 if src
 * is not a tree.
 */
uint32_t fdt_rebuild_for_linux(uintptr_t src, uintptr_t dst, const char *cmdline, uint64_t rd_lo, uint64_t rd_hi,
    uint64_t oops_base, uint64_t oops_size)
{
	if (!src || be32(src) != FDT_MAGIC)
		return 0;
	uint32_t off_struct = be32(src + 8), off_strings = be32(src + 12), off_rsv = be32(src + 16);
	uint32_t size_strings = be32(src + 32);
	uintptr_t strings = src + off_strings;
	uintptr_t o = dst + 40;				/* header written last */

	/* memory reservations, up to and including the empty entry */
	o = (o + 7) & ~7UL;
	uintptr_t rsv_at = o;
	for (uintptr_t r = src + off_rsv;; r += 16) {
		o = copy_bytes(o, r, 16);
		if (!*(volatile uint64_t *)r && !*(volatile uint64_t *)(r + 8))
			break;
	}
	uintptr_t struct_at = o;
	uintptr_t p = src + off_struct;
	int depth = 0, chosen = 0, reserved = 0;	/* inside /chosen, /reserved-memory itself */
	for (;;) {
		uint32_t tok = be32(p);
		if (tok == FDT_BEGIN_NODE) {
			const char *name = (const char *)(p + 4);
			uintptr_t end = align4(skip_str(p + 4));
			depth++;
			if (depth == 2 && streq(name, "chosen"))
				chosen = 1;
			if (depth == 2 && streq(name, "reserved-memory"))
				reserved = 1;
			o = copy_bytes(o, p, (uint32_t)(end - p));
			p = end;
		} else if (tok == FDT_END_NODE) {
			if (depth == 2 && reserved && oops_size) {
				/* ramoops@<base> { compatible "ramoops"; reg; no-map; record/console/pmsg sizes } */
				static const char node[] = "ramoops";
				put_be32(o, FDT_BEGIN_NODE);
				o = copy_bytes(o + 4, (uintptr_t)node, sizeof(node));
				while (o & 3)
					*(volatile char *)o++ = 0;
				put_be32(o, FDT_PROP); put_be32(o + 4, 8); put_be32(o + 8, size_strings + 0);
				o = copy_bytes(o + 12, (uintptr_t)"ramoops", 8);
				put_be32(o, FDT_PROP); put_be32(o + 4, 16); put_be32(o + 8, size_strings + 11);
				put_be32(o + 12, (uint32_t)(oops_base >> 32)); put_be32(o + 16, (uint32_t)oops_base);
				put_be32(o + 20, (uint32_t)(oops_size >> 32)); put_be32(o + 24, (uint32_t)oops_size);
				o += 28;
				put_be32(o, FDT_PROP); put_be32(o + 4, 0); put_be32(o + 8, size_strings + 15);
				o += 12;
				put_be32(o, FDT_PROP); put_be32(o + 4, 4); put_be32(o + 8, size_strings + 22);
				put_be32(o + 12, OOPS_RECORD); o += 16;
				put_be32(o, FDT_PROP); put_be32(o + 4, 4); put_be32(o + 8, size_strings + 34);
				put_be32(o + 12, OOPS_CONSOLE); o += 16;
				put_be32(o, FDT_PROP); put_be32(o + 4, 4); put_be32(o + 8, size_strings + 47);
				put_be32(o + 12, OOPS_PMSG); o += 16;
				put_be32(o, FDT_END_NODE);
				o += 4;
			}
			if (depth == 2) {
				chosen = 0;
				reserved = 0;
			}
			depth--;
			o = copy_bytes(o, p, 4);
			p += 4;
		} else if (tok == FDT_PROP) {
			int in_chosen = chosen && depth == 2;
			uint32_t len = be32(p + 4), nameoff = be32(p + 8);
			const char *pname = (const char *)(strings + nameoff);
			uintptr_t val = p + 12, next = align4(val + len);
			if (in_chosen && streq(pname, "bootargs")) {
				uint32_t n = 0;
				while (cmdline[n])
					n++;
				put_be32(o, FDT_PROP);
				put_be32(o + 4, n + 1);
				put_be32(o + 8, nameoff);
				o = copy_bytes(o + 12, (uintptr_t)cmdline, n + 1);
				while (o & 3)
					*(volatile char *)o++ = 0;
			} else if (in_chosen && (streq(pname, "linux,initrd-start") || streq(pname, "linux,initrd-end"))) {
				uint64_t v = streq(pname, "linux,initrd-start") ? rd_lo : rd_hi;
				put_be32(o, FDT_PROP);
				put_be32(o + 4, 8);
				put_be32(o + 8, nameoff);
				put_be32(o + 12, (uint32_t)(v >> 32));
				put_be32(o + 16, (uint32_t)v);
				o += 20;
			} else {
				o = copy_bytes(o, p, (uint32_t)(next - p));
			}
			p = next;
		} else if (tok == FDT_NOP) {
			p += 4;
		} else {				/* FDT_END */
			o = copy_bytes(o, p, 4);
			break;
		}
	}
	uint32_t size_struct = (uint32_t)(o - struct_at);
	uintptr_t strings_at = o;
	o = copy_bytes(o, strings, size_strings);
	if (oops_size) {			/* the new node's names, at size_strings + 0, 11, 15, 22, 34, 47 */
		static const char names[] = "compatible\0reg\0no-map\0record-size\0console-size\0pmsg-size";
		o = copy_bytes(o, (uintptr_t)names, sizeof(names));
		size_strings += sizeof(names);
	}
	uint32_t total = (uint32_t)(o - dst);
	put_be32(dst + 0, FDT_MAGIC);
	put_be32(dst + 4, total);
	put_be32(dst + 8, (uint32_t)(struct_at - dst));
	put_be32(dst + 12, (uint32_t)(strings_at - dst));
	put_be32(dst + 16, (uint32_t)(rsv_at - dst));
	put_be32(dst + 20, 17);				/* version */
	put_be32(dst + 24, 16);				/* last compatible version */
	put_be32(dst + 28, be32(src + 28));		/* boot_cpuid_phys */
	put_be32(dst + 32, size_strings);
	put_be32(dst + 36, size_struct);
	return total;
}

/* /chosen's bootargs (up to max-1 bytes) into out; its length, 0 if absent. */
uint32_t fdt_chosen_str(uintptr_t fdt, const char *prop, char *out, uint32_t max)
{
	uintptr_t v;
	uint32_t len, i;
	if (!chosen_prop(fdt, prop, &v, &len))
		return 0;
	for (i = 0; i < len && i + 1 < max && *(volatile char *)(v + i); i++)
		out[i] = *(volatile char *)(v + i);
	out[i] = 0;
	return i;
}

/* The tree's total size. */
uint32_t fdt_size(uintptr_t fdt)
{
	return fdt && be32(fdt) == FDT_MAGIC ? be32(fdt + 4) : 0;
}

/* And the memcpy clang emits for initialised local arrays. */
void *memcpy(void *dst, const void *src, unsigned long n)
{
	char *d = dst;
	const char *s = src;
	while (n--)
		*d++ = *s++;
	return dst;
}
