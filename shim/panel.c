/*
 * The panel's brightness, as bsd/dev/sweet_gpu.c's panel_dcs_brightness() sends it: a DCS long
 * write 0x51 through DSI0's command DMA (test-pattern FIFO, no memory), between two frames -- the
 * display engine refreshes the panel by itself at every TE (INTF1 tear-check autorefresh, as ABL
 * leaves it), so autorefresh is paused, the frame in flight let finish, the command sent and
 * autorefresh put back. Level 0 is how the kernel switches the display "off".
 */
#include "panel.h"
#include "spmi.h"

#define DSI0			0x0ae94000UL
#define DSI_CTRL		0x004
#define DSI_STATUS		0x008
#define DSI_CMD_DMA_CTRL	0x03c
#define DSI_DMA_CMD_LENGTH	0x04c
#define DSI_DMA_SW_TRIGGER	0x090
#define DSI_INT_CTRL		0x110
#define DSI_TPG_CTRL		0x15c
#define DSI_TPG_DMA_INIT	0x17c
#define DSI_TPG_FIFO_RESET	0x1ec
#define INTF1_AUTOREFRESH	(0x0ae6b000UL + 0x800 + 0x2b4)

static inline uint32_t rd32(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline void wr32(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }

static void udelay_spin(unsigned n)
{
	for (volatile unsigned i = 0; i < n * 50; i++)
		;
}

int panel_brightness(uint32_t level)
{
	uint32_t reg, i, done = 0;
	if (level > 0x7ff)
		level = 0x7ff;
	if (!(rd32(DSI0 + DSI_CTRL) & 1))
		return -2;				/* the controller is off */
	uint32_t autorefresh = rd32(INTF1_AUTOREFRESH);
	if (autorefresh & (1U << 31)) {
		wr32(INTF1_AUTOREFRESH, 0);
		__asm__ volatile("dsb sy" ::: "memory");
	}
	for (i = 0; i < 40 && (rd32(DSI0 + DSI_STATUS) & (1U << 2)); i++)	/* CMD_MODE_MDP_BUSY, up to 40 ms */
		delay_ms(1);
	wr32(DSI0 + DSI_TPG_CTRL, (1U << 1) | (1U << 2) | (3U << 16));	/* CMD_DMA_TPG_EN, FIFO, custom */
	/* header {wc lo, wc hi, type 0x39 DCS long write, flags last|long}, payload padded with 0xff */
	wr32(DSI0 + DSI_TPG_DMA_INIT, 0x03U | 0x39U << 16 | 0xc0U << 24);
	wr32(DSI0 + DSI_TPG_DMA_INIT, 0x51U | (level >> 8) << 8 | (level & 0xff) << 16 | 0xffU << 24);
	reg = rd32(DSI0 + DSI_CMD_DMA_CTRL);
	reg &= ~((1U << 31) | (1U << 30));		/* not broadcast, not a master of two */
	reg |= 1U << 28;				/* embedded mode */
	wr32(DSI0 + DSI_CMD_DMA_CTRL, reg);
	wr32(DSI0 + DSI_DMA_CMD_LENGTH, 8);
	__asm__ volatile("dsb sy" ::: "memory");
	wr32(DSI0 + DSI_DMA_SW_TRIGGER, 1);
	for (i = 0; i < 20000; i++) {			/* CMD_MODE_DMA_DONE */
		if ((done = rd32(DSI0 + DSI_INT_CTRL)) & 1)
			break;
		udelay_spin(1);
	}
	if (done & 1)
		wr32(DSI0 + DSI_INT_CTRL, done);
	wr32(DSI0 + DSI_TPG_CTRL, 0);
	wr32(DSI0 + DSI_TPG_FIFO_RESET, 1);
	udelay_spin(1);
	wr32(DSI0 + DSI_TPG_FIFO_RESET, 0);
	if (autorefresh & (1U << 31)) {
		__asm__ volatile("dsb sy" ::: "memory");
		wr32(INTF1_AUTOREFRESH, autorefresh);
	}
	return (done & 1) ? 0 : -3;
}
