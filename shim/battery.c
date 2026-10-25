/*
 * The battery for the charging screen, as iokit/Kernel/arm/SweetBattery.cpp reads it: the PM6150
 * fuel gauge's last voltage (QG 0x48c0, 194.637 uV a step) and current (0x48c2, signed, 152.588
 * or 305.176 uA a step by subtype; negative = charging), the voltage taken back to open circuit
 * through ~0.12 ohm, then a generic single-cell curve. An estimate, not Linux's QG algorithm.
 */
#include "battery.h"
#include "spmi.h"

#define PPID_QG		0x048
#define RBATT_MOHM	120

static int word(int qg, unsigned reg, unsigned *out)
{
	uint8_t lo, hi, lo2;
	for (int i = 0; i < 4; i++) {
		if (spmi_rd(qg, reg, &lo) || spmi_rd(qg, reg + 1, &hi) || spmi_rd(qg, reg, &lo2))
			return -1;
		if (lo == lo2) {
			*out = (unsigned)hi << 8 | lo;
			return 0;
		}
	}
	return -1;
}

static unsigned percent_of(unsigned mv)
{
	static const unsigned volts[] = { 3400, 3500, 3600, 3700, 3800, 3900, 4000, 4100, 4200, 4350 };
	static const unsigned soc[] = { 1, 5, 10, 20, 40, 60, 75, 85, 93, 100 };
	if (mv <= volts[0])
		return soc[0];
	for (unsigned i = 1; i < sizeof(volts) / sizeof(volts[0]); i++)
		if (mv < volts[i])
			return soc[i - 1] + (mv - volts[i - 1]) * (soc[i] - soc[i - 1]) / (volts[i] - volts[i - 1]);
	return 100;
}

int battery_read(unsigned *percent, unsigned *mv, int *ma)
{
	int qg = spmi_apid(PPID_QG);
	uint8_t type, present, subtype;
	unsigned rv, ri;
	if (spmi_rd(qg, 0x04, &type) || type != 0x0d || spmi_rd(qg, 0x08, &present) || !(present & 1) ||
	    word(qg, 0xc0, &rv) || rv == 0x8000)
		return -1;
	*mv = (unsigned)(((uint64_t)rv * 194637u) / 1000000u);
	if (*mv < 2800 || *mv > 4600)
		return -1;
	*ma = 0;
	if (!spmi_rd(qg, 0x05, &subtype) && (subtype == 3 || subtype == 4) && !word(qg, 0xc2, &ri) && ri != 0x8000) {
		int raw = (ri & 0x8000) ? (int)ri - 65536 : (int)ri;
		*ma = (int)(-((int64_t)raw * (subtype == 3 ? 152588 : 305176)) / 1000000);	/* + charging */
	}
	int ocv = (int)*mv - *ma * RBATT_MOHM / 1000;
	*percent = percent_of(ocv > 0 ? (unsigned)ocv : 0);
	return 0;
}
