/*
 * davinci graft seam: what hakios.lx.c (the Linux-compat host glue for ath10k) asks of the
 * platform. On HackiOS these are answered by their modem orchestration (hakios.wifi.c); here
 * they are answered by sweet_wifi.c, which bridges to our own modem bring-up in sweet_gpu.c
 * (M1-M3: MPSS + wlan_pd + WLFW up) and to wfw_read for firmware. Declared in one place so the
 * upstream glue sees real prototypes, not implicit int-returning declarations.
 */
#ifndef _SYS_SWEET_WIFI_H_
#define _SYS_SWEET_WIFI_H_

#include <stdbool.h>
#include <stdint.h>
#include <sys/cdefs.h>
#include <sys/hakios.qrtr.h>

__BEGIN_DECLS

/* Provided by sweet_gpu.c (which owns the modem + QRTR): the bridge the glue is wired to. */
int             sweet_wifi_radio_powered(void);                                /* our modem + wlan_pd + WLFW are up */
const uint8_t  *sweet_wifi_read_firmware(const char *name, uint64_t *size);    /* firmware from WFW_DIR (wfw_read) */
const struct hakios_qrtr_ops *sweet_wifi_qrtr_ops(void);                        /* our wqrtr wrapped for the QMI engine */

void            hakios_wifi_say(const char *format, ...) __printflike(1, 2);   /* debug log (may be held back) */
void            hakios_wifi_tell(const char *format, ...) __printflike(1, 2);  /* always logged */
const uint8_t  *hakios_wifi_driver_file(const char *name, uint64_t *size);     /* firmware by Linux name; NULL = ENOENT */
int             hakios_wifi_dsp_is_up(void);                                   /* the WLAN DSP/PD is running */
bool            hakios_wifi_icnss_ready(void);                                 /* modem + wlan_pd + WLFW up (our M3) */
unsigned        hakios_wifi_option(const char *name);                          /* boot-arg "name" as a number; 0 if absent */
int             hakios_wifi_radio_address(unsigned char *address);             /* the radio's MAC: 1 and 6 bytes, or 0 */
int             hakios_wifi_network(unsigned char *name, unsigned *name_length,
                    unsigned char *passphrase, unsigned *passphrase_length);   /* network to join: 1, or 0 */
/* Map `size` bytes at host physical `physical` so the radio sees them (through the WLAN SMMU); the
 * device address the radio uses goes in *address. The davinci WLAN stream is stage-1 bypass, so the
 * device address is the physical address. true on success. */
bool            hakios_wifi_radio_map(uint64_t physical, unsigned long size, unsigned long long *address);

/* Orchestration entry (sweet_wifi.c): once our modem + wlan_pd + WLFW are up, install the QRTR
 * transport and bring the ath10k driver up (hakios_lx_prepare + hakios_lx_start). A no-op until
 * the radio is powered. Called from sweet_gpu.c's WiFi path on the boot-arg. */
void            sweet_wifi_driver_up(void);

__END_DECLS

#endif /* _SYS_SWEET_WIFI_H_ */
