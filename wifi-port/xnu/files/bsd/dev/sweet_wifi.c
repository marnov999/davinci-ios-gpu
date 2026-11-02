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

int
hakios_wifi_network(unsigned char *name, unsigned *name_length, unsigned char *passphrase, unsigned *passphrase_length)
{
	/* The SSID/passphrase come from iOS Settings via apple80211 (Phase D); none is baked in. */
	(void)name; (void)passphrase;
	*name_length = 0;
	*passphrase_length = 0;
	return 0;
}

/* ---- the radio's DMA memory through the WLAN SMMU ---------------------------------------------- */

bool
hakios_wifi_radio_map(uint64_t physical, unsigned long size, unsigned long long *address)
{
	/* davinci's WLAN apps-smmu stream (0x240) is stage-1 bypass, so the address the radio uses is
	 * the physical address. (If a fault shows the stream is not bypassed, program a context here.) */
	(void)size;
	*address = physical;
	return true;
}

/* ---- modem state: wired to sweet_gpu.c in a later phase ---------------------------------------- */

int  hakios_wifi_dsp_is_up(void)   { return 0; }   /* B1: not yet wired -> driver stays down */
bool hakios_wifi_icnss_ready(void) { return false; }

const uint8_t *
hakios_wifi_driver_file(const char *name, uint64_t *size)
{
	(void)name;
	*size = 0;
	return NULL;   /* B1: firmware fetch wired to wfw_read in a later phase */
}

/* ---- network + station bridges to iOS: Phase D (harmless stubs for now) ------------------------ */

bool hakios_net_attach(const struct hakios_net_link *link)      { (void)link; return false; }
void hakios_net_input(const uint8_t *frame, size_t length)      { (void)frame; (void)length; }
void hakios_net_link_state(bool up)                             { (void)up; }
void hakios_sta_attach(const struct hakios_sta_ops *ops)        { (void)ops; }
void hakios_sta_lost(int error)                                 { (void)error; }

/* ---- orchestration ----------------------------------------------------------------------------- */

void
sweet_wifi_driver_up(void)
{
	if (!hakios_wifi_icnss_ready()) {
		hakios_wifi_tell("SWEET WIFI: [lx] radio not powered yet -- ath10k not started (B1)\n");
		return;
	}
	/* B1c: hakios_qmi_set_transport(sweet_wifi_qrtr_ops()); hakios_lx_prepare(); hakios_lx_start(); */
}
