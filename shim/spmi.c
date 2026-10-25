/*
 * The PMICs, for the shim's charger wait and boot menu. SPMI v5 (davinci DTB): core 0x0c440000
 * (APID map at +0x900), cnfg 0x0c40a000 (owner at +0x700), observer 0x0e600000 (reads: +0x80 *
 * apid), chnls 0x0c600000 (writes: +0x10000 * apid); CMD at +0, STATUS +8, WDATA0 +0x10,
 * RDATA0 +0x18 -- as bsd/dev/sweet_keys.c and sweet_gpu.c use them in the kernel.
 */
#include "spmi.h"

#define SPMI_CORE	0x0c440000UL
#define SPMI_CFG	0x0c40a000UL
#define SPMI_OBS	0x0e600000UL
#define SPMI_CHNLS	0x0c600000UL
#define PSHOLD		0x0c264000UL

#define PON_PS_HOLD_RST_CTL	0x5a
#define PON_PS_HOLD_RST_CTL2	0x5b
#define PON_RESET_EN	0x80
#define PON_SHUTDOWN	0x04

#define rsr(r) ({ uint64_t _v; __asm__ volatile("mrs %0, " r : "=r"(_v)); _v; })

static inline uint32_t rd32(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline void wr32(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }

static uint64_t now(void)
{
	__asm__ volatile("isb" ::: "memory");
	return rsr("cntpct_el0");
}

void delay_ms(unsigned ms)
{
	uint64_t end = now() + rsr("cntfrq_el0") / 1000 * ms;
	while (now() < end)
		;
}

/* As delay_ms, asleep: the timer's event stream (one event every 2^15 ticks, ~1.7 ms at 19.2 MHz)
 * wakes the core from wfe, so it does not spin hot for hours while the battery charges. */
void sleep_ms(unsigned ms)
{
	uint64_t end = now() + rsr("cntfrq_el0") / 1000 * ms;
	uint64_t k = rsr("cntkctl_el1");
	k = (k & ~0xf0UL) | (14UL << 4) | (1UL << 2);	/* EVNTI 14, EVNTEN */
	__asm__ volatile("msr cntkctl_el1, %0; isb" : : "r"(k));
	while (now() < end)
		__asm__ volatile("wfe");
}

/* The APID of a PPID, the one EE 0 owns if there are several; -1 if none. */
int spmi_apid(unsigned ppid)
{
	unsigned count = rd32(SPMI_CORE + 4) & 0x7ff, apid = 0xffff;
	if (count == 0 || count > 512)
		return -1;
	for (unsigned i = 0; i < count; i++) {
		uint32_t map = rd32(SPMI_CORE + 0x900 + 4 * i);
		if (!map || ((map >> 8) & 0xfff) != ppid)
			continue;
		if (apid == 0xffff || (rd32(SPMI_CFG + 0x700 + 4 * i) & 7) == 0)
			apid = i;
	}
	return apid == 0xffff ? -1 : (int)apid;
}

int spmi_rd(int apid, unsigned reg, uint8_t *out)
{
	if (apid < 0)
		return -1;
	uintptr_t ch = SPMI_OBS + 0x80UL * (unsigned)apid;
	wr32(ch, (1U << 27) | ((reg & 0xff) << 4));		/* EXT_READL, 1 byte */
	__asm__ volatile("dsb osh" ::: "memory");
	for (int i = 0; i < 100000; i++) {
		uint32_t st = rd32(ch + 8);
		if (st & 1) {
			if (st & 0x0e)
				return -1;
			*out = (uint8_t)rd32(ch + 0x18);
			return 0;
		}
	}
	return -1;
}

int spmi_wr(int apid, unsigned reg, uint8_t val)
{
	if (apid < 0)
		return -1;
	uintptr_t ch = SPMI_CHNLS + 0x10000UL * (unsigned)apid;
	wr32(ch + 0x10, val);
	__asm__ volatile("dsb osh" ::: "memory");
	wr32(ch, (0U << 27) | ((reg & 0xff) << 4));		/* EXT_WRITEL, 1 byte */
	__asm__ volatile("dsb osh" ::: "memory");
	for (int i = 0; i < 100000; i++) {
		uint32_t st = rd32(ch + 8);
		if (st & 1)
			return (st & 0x0e) ? -1 : 0;
	}
	return -1;
}

/* As Linux's qpnp-power-on and msm-poweroff: the reset type changes with its enable (0x5b
 * bit 7) off, then PS_HOLD drops and the PMIC switches the phone off. */
void spmi_power_off(void)
{
	int pon = spmi_apid(PPID_PON);
	uint8_t ctl = 0, ctl2 = 0;
	(void)spmi_rd(pon, PON_PS_HOLD_RST_CTL, &ctl);
	(void)spmi_rd(pon, PON_PS_HOLD_RST_CTL2, &ctl2);
	(void)spmi_wr(pon, PON_PS_HOLD_RST_CTL2, ctl2 & ~PON_RESET_EN);
	delay_ms(1);
	(void)spmi_wr(pon, PON_PS_HOLD_RST_CTL, (ctl & 0xf0) | PON_SHUTDOWN);
	(void)spmi_wr(pon, PON_PS_HOLD_RST_CTL2, ctl2 | PON_RESET_EN);
	delay_ms(1);
	wr32(PSHOLD, 0);
	__asm__ volatile("dsb sy" ::: "memory");
	for (;;)
		__asm__ volatile("wfe");
}
