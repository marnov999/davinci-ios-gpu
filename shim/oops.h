#pragma once
#include <stdint.h>

/* Measuring builds: where MIUI's kernel keeps its log (pstore ramoops) for the next boot to show: free
 * RAM above the kernel's copy (linux.c puts the kernel, ramdisk and tree at 0xc0000000..~0xc3800000),
 * clear of the container ABL loads and read before the XNU payload is copied anywhere. */
#define OOPS_BASE	0xc8000000ULL
#define OOPS_SIZE	0x400000ULL
#define OOPS_RECORD	0x10000		/* 16 oops dumps */
#define OOPS_CONSOLE	0x200000	/* the console log: after the dumps */
#define OOPS_PMSG	0x100000

/* If the last boot left a console log there: its longest pauses on screen for 15 s, then forgotten. */
void oops_report(void);


