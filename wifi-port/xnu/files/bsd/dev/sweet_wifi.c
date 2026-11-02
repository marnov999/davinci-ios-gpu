/*
 * davinci WiFi graft (M5): the platform seam between the Linux-compat ath10k host glue
 * (hakios.lx.c + the ath10k.o object) and our own modem bring-up in sweet_gpu.c.
 *
 * Phase B1: provide every symbol the glue needs so the kernel links the driver object and boots.
 * The modem-tied answers (firmware, "is the radio powered") and the QRTR transport are wired to
 * sweet_gpu.c in a later phase; here they report not-ready, so the driver stays down and a normal
 * boot is unaffected. The network/station bridges to iOS (hakios.net.c/sta.c/apple80211.c) come
 * in Phase D; until then they are harmless stubs.
 */
#include <sys/sweet_wifi.h>
#include <sys/hakios.net.h>
#include <sys/hakios.sta.h>
#include <sys/hakios.qrtr.h>
#include <libkern/libkern.h>
#include <pexpert/pexpert.h>
#include <stdarg.h>
#include <string.h>

/* The driver object (ath10k.o) and the glue export these; declared here so the orchestration can
 * call them without pulling in the whole lx header set. */
extern int  hakios_lx_prepare(void);
extern int  hakios_lx_start(void);
extern void hakios_lx_stop(void);

/* ---- logging ------------------------------------------------------------------------------------ */

static void
wsay(const char *format, va_list args)
{
	char line[256];
	vsnprintf(line, sizeof(line), format, args);
	printf("%s", line);
}

void
hakios_wifi_say(const char *format, ...)
{
	va_list args;
	va_start(args, format);
	wsay(format, args);
	va_end(args);
}

void
hakios_wifi_tell(const char *format, ...)
{
	va_list args;
	va_start(args, format);
	wsay(format, args);
	va_end(args);
}

/* ---- boot-args --------------------------------------------------------------------------------- */

unsigned
hakios_wifi_option(const char *name)
{
	unsigned value = 0;
	return PE_parse_boot_argn(name, &value, sizeof(value)) ? value : 0;
}

int
hakios_wifi_radio_address(unsigned char *address)
{
	uint64_t mac = 0;   /* boot-arg wifi_mac=0x0203040506 style; 0 = none */
	if (!PE_parse_boot_argn("wifi_mac", &mac, sizeof(mac)) || mac == 0) {
		return 0;
	}
	for (int i = 0; i < 6; i++) {
		address[5 - i] = (unsigned char)(mac >> (8 * i));
	}
	return 1;
}

/* Copy a "key=value" boot-arg's value (up to the next space) out of the raw boot command line.
 * We do NOT use PE_parse_boot_argn for this: it parses an all-digit value as an integer and writes
 * the number's bytes into the buffer (e.g. wifi_pass=11111111 -> the int 0x00A98AC7, strlen 3),
 * which silently corrupts a numeric passphrase. Returns the value length (0 if the arg is absent). */
static unsigned
wifi_bootarg(const char *key, char *out, unsigned outsz)
{
	extern char *PE_boot_args(void);
	const char *a = PE_boot_args();
	if (a == NULL || outsz == 0) {
		return 0;
	}
	unsigned klen = (unsigned)strlen(key);
	for (const char *p = a; *p != '\0'; p++) {
		if (p != a && p[-1] != ' ') {
			continue;                       /* only match at a token boundary */
		}
		unsigned i = 0;
		while (i < klen && p[i] == key[i]) {
			i++;
		}
		if (i != klen || p[klen] != '=') {
			continue;
		}
		const char *v = p + klen + 1;
		unsigned n = 0;
		while (v[n] != '\0' && v[n] != ' ' && n < outsz - 1) {
			out[n] = v[n];
			n++;
		}
		out[n] = '\0';
		return n;
	}
	return 0;
}

int
hakios_wifi_network(unsigned char *name, unsigned *name_length, unsigned char *passphrase, unsigned *passphrase_length)
{
	/* A baked network for a direct driver-driven join (wifi_join=1), bypassing wifid/apple80211:
	 * boot-args wifi_ssid=<name> and wifi_pass=<passphrase> (omit wifi_pass for an open network).
	 * The normal iOS path (Settings via apple80211) carries its own SSID/passphrase and does not use
	 * this. Returns 1 when a network is baked, 0 otherwise (then lx_station_join is a no-op). */
	char ssid[33] = {0};        /* 802.11 SSID is at most 32 bytes */
	char pass[65] = {0};        /* WPA passphrase is 8..63 bytes */

	*name_length = 0;
	*passphrase_length = 0;
	unsigned sl = wifi_bootarg("wifi_ssid", ssid, sizeof(ssid));
	if (sl == 0) {
		return 0;
	}
	if (sl > 32) {
		sl = 32;
	}
	memcpy(name, ssid, sl);
	*name_length = sl;
	unsigned pl = wifi_bootarg("wifi_pass", pass, sizeof(pass));
	if (pl > 0) {
		if (pl > 63) {
			pl = 63;
		}
		memcpy(passphrase, pass, pl);
		*passphrase_length = pl;
	}
	hakios_wifi_tell("SWEET WIFI: [lx] baked network \"%s\" (%u-byte key) from boot-args -- direct join\n",
	    ssid, *passphrase_length);
	return 1;
}

/* ---- the radio's DMA memory through the WLAN SMMU ---------------------------------------------- */

bool
hakios_wifi_radio_map(uint64_t physical, unsigned long size, unsigned long long *address)
{
	/* The radio reaches our memory through its apps-smmu context (sweet_wlan_smmu_prepare): hand out
	 * an IOVA and map host physical behind it. The boot chain leaves stream 0x240 faulting, so bypass
	 * is not an option -- a real context + page tables are required (else ath10k HTC times out). */
	return sweet_wlan_radio_map(physical, size, address);
}

/* ---- modem state: wired to sweet_gpu.c (our M1-M3 bring-up + firmware store) ------------------- */

int  hakios_wifi_dsp_is_up(void)   { return sweet_wifi_radio_powered(); }
bool hakios_wifi_icnss_ready(void) { return sweet_wifi_radio_powered() != 0; }

const uint8_t *
hakios_wifi_driver_file(const char *name, uint64_t *size)
{
	return sweet_wifi_read_firmware(name, size);
}

/* ---- network + station bridges to iOS now come from hakios.net.c / sta.c / apple80211.c (Phase D).
 * net.c's hakios_net_init() (which we do not call) references the QEMU virtio net; stub that one
 * symbol so the port links on davinci. */
void hakios_virtio_net_init(void) { }

/* davinci is not the raphael reference device (apple80211.c / lx.c branch on this). */
int hakios_is_raphael(void) { return 0; }

/* ---- orchestration ----------------------------------------------------------------------------- */

void
sweet_wifi_driver_up(void)
{
	static bool once;
	int ret;

	if (once) {
		return;
	}
	if (!hakios_wifi_icnss_ready()) {
		hakios_wifi_tell("SWEET WIFI: [lx] radio not powered yet -- ath10k not started\n");
		return;
	}
	once = true;
	hakios_qmi_set_transport(sweet_wifi_qrtr_ops());   /* run the QMI engine over our wqrtr */
	hakios_wifi_tell("SWEET WIFI: [lx] radio powered -- bringing ath10k up\n");
	if ((ret = hakios_lx_prepare()) != 0) {
		hakios_wifi_tell("SWEET WIFI: [lx] lx_prepare failed (%d)\n", ret);
		return;
	}
	ret = hakios_lx_start();
	hakios_wifi_tell("SWEET WIFI: [lx] lx_start returned %d%s\n", ret, ret == 0 ? " -- ath10k UP" : "");
}
