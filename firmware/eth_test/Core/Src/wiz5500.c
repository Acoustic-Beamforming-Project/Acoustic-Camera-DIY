/* wiz5500.c — WIZ850io (W5500) application driver
 *
 * Public API is UNCHANGED (same function signatures as before).
 * SPI I/O is now routed through the WIZnet ioLibrary (w5500.c / w5500.h)
 * instead of calling HAL_SPI_Transmit / HAL_SPI_Receive directly.
 *
 * Integration pattern
 * ───────────────────
 *  ┌──────────────┐      ┌──────────────────────────────────────────┐
 *  │   main.c     │──►   │  wiz5500.c  (this file)                  │
 *  │ WIZ5500_Init │      │  WIZ5500_SetupSocket0 / SendBatch / …    │
 *  └──────────────┘      │  uses ioLibrary macros: setSn_MR(),       │
 *                        │  getSn_TX_FSR(), wiz_send_data(), …       │
 *                        └──────────────┬───────────────────────────┘
 *                                       │ calls WIZCHIP_READ/WRITE
 *                                       ▼
 *                        ┌──────────────────────────────────────────┐
 *                        │  w5500.c  (WIZnet ioLibrary)             │
 *                        │  WIZCHIP_READ / WIZCHIP_WRITE / …        │
 *                        └──────────────┬───────────────────────────┘
 *                                       │ calls WIZCHIP.IF.SPI._xxx()
 *                                       ▼
 *                        ┌──────────────────────────────────────────┐
 *                        │  STM32 HAL  (SPI1 blocking)              │
 *                        │  HAL_SPI_Transmit / HAL_SPI_Receive      │
 *                        └──────────────────────────────────────────┘
 *
 * STM32F401RCT6 @ 64 MHz | SPI1 @ 32 MHz (APB2/2) | polling (no DMA)
 */

#include "wiz5500.h"
#include "w5500.h"          /* WIZnet ioLibrary: WIZCHIP_READ/WRITE, setSn_*, … */
#include "wizchip_conf.h"   /* _WIZCHIP_ struct and WIZCHIP extern               */
#include <string.h>

/* ── HAL handle (defined in main.c / MX-generated) ─────────────────────── */
extern SPI_HandleTypeDef  hspi1;

/* ── Global ioLibrary handle — filled in _Wizchip_Conf_Init() ───────────── */
WIZCHIPHandle_t WIZCHIP;

/* ── Driver state ────────────────────────────────────────────────────────── */
static WIZ5500_Config    _cfg;
static volatile uint32_t _dropped_packets = 0u;
static volatile uint8_t  _tx_busy         = 0u;

/* ═══════════════════════════════════════════════════════════════════════════
 * Low-level SPI callbacks — registered into WIZCHIP struct and called by
 * the ioLibrary (w5500.c) via WIZCHIP.IF.SPI._xxx() / WIZCHIP.CS._xxx().
 * All are blocking (polling), matching the project's original behaviour.
 * ═══════════════════════════════════════════════════════════════════════════ */

static void _cs_select(void)
{
    HAL_GPIO_WritePin(ETH_CS_PORT, ETH_CS_PIN, GPIO_PIN_RESET);
}

static void _cs_deselect(void)
{
    HAL_GPIO_WritePin(ETH_CS_PORT, ETH_CS_PIN, GPIO_PIN_SET);
}

static void _spi_write_byte(uint8_t wb)
{
    HAL_SPI_Transmit(&hspi1, &wb, 1u, 10u);
}

static uint8_t _spi_read_byte(void)
{
    uint8_t rb = 0u;
    HAL_SPI_Receive(&hspi1, &rb, 1u, 10u);
    return rb;
}

static void _spi_write_burst(uint8_t *pBuf, uint16_t len)
{
    HAL_SPI_Transmit(&hspi1, pBuf, len, 20u);
}

static void _spi_read_burst(uint8_t *pBuf, uint16_t len)
{
    HAL_SPI_Receive(&hspi1, pBuf, len, 20u);
}

/* Critical section — bare-metal, no RTOS */
static void _cris_enter(void) { __disable_irq(); }
static void _cris_exit(void)  { __enable_irq();  }

/* ═══════════════════════════════════════════════════════════════════════════
 * _Wizchip_Conf_Init() — register all callbacks into the ioLibrary handle
 * ═══════════════════════════════════════════════════════════════════════════ */
static void _Wizchip_Conf_Init(void)
{
    memset(&WIZCHIP, 0, sizeof(WIZCHIP));

    WIZCHIP.CRIS._enter  = _cris_enter;
    WIZCHIP.CRIS._exit   = _cris_exit;
    WIZCHIP.CS._select   = _cs_select;
    WIZCHIP.CS._deselect = _cs_deselect;

    /* Non-NULL burst pointers → ioLibrary uses burst path in w5500.c */
    WIZCHIP.IF.SPI._write_byte  = _spi_write_byte;
    WIZCHIP.IF.SPI._read_byte   = _spi_read_byte;
    WIZCHIP.IF.SPI._write_burst = _spi_write_burst;
    WIZCHIP.IF.SPI._read_burst  = _spi_read_burst;
}

/* ═══════════════════════════════════════════════════════════════════════════
 * _W5500_HardwareReset() — RSTn pin + software MR reset
 * ═══════════════════════════════════════════════════════════════════════════ */
static void _W5500_HardwareReset(void)
{
    ETH_RST_ASSERT();
    HAL_Delay(1u);
    ETH_RST_DEASSERT();
    HAL_Delay(55u);

    /* Software reset via ioLibrary MR register macro */
    setMR(MR_RST);
    HAL_Delay(5u);
}

/* ═══════════════════════════════════════════════════════════════════════════
 * _W5500_CommonConfig() — network parameters via ioLibrary setter macros
 * ═══════════════════════════════════════════════════════════════════════════ */
static void _W5500_CommonConfig(void)
{
    setSHAR(_cfg.mac);
    setGAR(_cfg.gateway);
    setSUBR(_cfg.subnet);
    setSIPR(_cfg.ip);
    setRTR(2000u);
    setRCR(8u);
}

/* ═══════════════════════════════════════════════════════════════════════════
 * Public API — identical signatures to the previous driver
 * ═══════════════════════════════════════════════════════════════════════════ */

void WIZ5500_Init(const WIZ5500_Config *cfg)
{
    if (cfg == NULL) return;

    _cfg             = *cfg;
    _dropped_packets = 0u;
    _tx_busy         = 0u;

    _Wizchip_Conf_Init();
    _W5500_HardwareReset();
    _W5500_CommonConfig();
}

WIZ5500_Status WIZ5500_SetupSocket0(void)
{
    uint8_t  sr;
    uint32_t timeout;

    setSn_CR(0, Sn_CR_CLOSE);
    HAL_Delay(5u);

    setSn_TXBUF_SIZE(0, 16u);
    setSn_RXBUF_SIZE(0, 0u);

    setSn_MR(0, Sn_MR_UDP);

    {
        uint8_t bcast[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
        setSn_DHAR(0, bcast);
    }

    setSn_DIPR(0, _cfg.dest_ip);
    setSn_DPORT(0, _cfg.dest_port);
    setSn_PORT(0, _cfg.src_port);

    setSn_CR(0, Sn_CR_OPEN);

    timeout = HAL_GetTick() + 10u;
    do {
        sr = getSn_SR(0);
        if (sr == SOCK_UDP) break;
    } while (HAL_GetTick() < timeout);

    if (sr != SOCK_UDP) return WIZ5500_ERR_SOCKET;

    return WIZ5500_OK;
}

WIZ5500_Status WIZ5500_SendBatch(const uint8_t *src_data, uint16_t len)
{
    if (src_data == NULL || len != WIZ5500_PAYLOAD_SIZE)
        return WIZ5500_ERR_PARAM;

    /* getSn_TX_FSR performs the double-read stability check internally */
    if (getSn_TX_FSR(0) < (uint16_t)WIZ5500_PAYLOAD_SIZE)
    {
        _dropped_packets++;
        return WIZ5500_ERR_NO_SPACE;
    }

    /* Write to TX buffer and advance Sn_TX_WR */
    wiz_send_data(0, (uint8_t *)src_data, WIZ5500_PAYLOAD_SIZE);

    /* Trigger UDP encapsulation + Ethernet TX */
    setSn_CR(0, Sn_CR_SEND);

    return WIZ5500_OK;
}

uint32_t WIZ5500_GetDroppedPackets(void) { return _dropped_packets; }
uint8_t  WIZ5500_IsTxBusy(void)         { return _tx_busy; }

void WIZ5500_OnDMATxComplete(void)
{
    /* Polling mode: DMA not used — kept for API compatibility only. */
    _tx_busy = 0u;
}
