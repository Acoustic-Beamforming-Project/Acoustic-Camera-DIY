/* wiz5500.h — WIZ850io (W5500) SPI1 DMA TX driver
 *
 * Drop-in replacement for wiz5200.h / wiz5200.c (WIZ820io W5200).
 * Public API is identical — no changes needed in main.c, ad7606.c,
 * or any other file except renaming the include and the function calls.
 *
 * ── W5500 vs W5200 key differences ──────────────────────────────────────────
 *
 *  SPI frame layout:
 *    W5200: [ADDR_H][ADDR_L][RW|LEN_H][LEN_L][DATA...]   4-byte header
 *    W5500: [ADDR_H][ADDR_L][BSB|RW|OM]      [DATA...]   3-byte header
 *
 *  W5500 3rd header byte:
 *    bits[7:3] = Block Select Bits (BSB)
 *      0x00 = Common registers
 *      0x08 = Socket 0 registers   (BSB = 0b00001 << 3)
 *      0x10 = Socket 0 TX buffer   (BSB = 0b00010 << 3)
 *      0x18 = Socket 0 RX buffer   (BSB = 0b00011 << 3)
 *    bit[2]   = Read/Write  (1=Write, 0=Read)
 *    bits[1:0]= Operating Mode (0b00=VDM variable length)
 *
 *  Register address differences:
 *    RTR:      W5200=0x0017  W5500=0x0019
 *    RCR:      W5200=0x0019  W5500=0x001B
 *    VERSIONR: W5200=0x001F  W5500=0x0039  (W5500 returns 0x04)
 *    MEMSIZE:  W5200=0x001B  W5500=none (per-socket TXBUF_SIZE/RXBUF_SIZE)
 *    Socket registers: W5200 offset from 0x4000, W5500 offset from 0x0000
 *
 *  TX buffer access:
 *    W5200: physical_addr = (S0_TX_WR & 0x1FFF) + 0x8000  (fixed base)
 *    W5500: use BSB=0x10, addr = S0_TX_WR & 0x3FFF         (16 KB window)
 *
 *  Memory allocation:
 *    W5200: global MEMSIZE register
 *    W5500: S0_TXBUF_SIZE (0x001E in socket block) — set to 16 for 16 KB
 *
 *  Hardware RESET:
 *    W5200: software-only (MR bit7)
 *    W5500: hardware RSTn pin (active LOW, ≥500 µs, then wait 50 ms)
 *           + software reset via MR bit7 (used as secondary/fallback)
 *
 *  SPI speed:
 *    W5200: max 33.33 MHz → prescaler /2 @ 64 MHz = 32 MHz (within spec)
 *    W5500: max 80 MHz    → prescaler /2 @ 64 MHz = 32 MHz (well within spec)
 *           Can use /1 = 64 MHz but /2 = 32 MHz is safe and sufficient.
 *
 * ── Hardware connections (WIZ850io → STM32F401RCT6) ─────────────────────────
 *
 *  WIZ850io J1:          STM32 Pin     Function
 *    J1-1  GND        →  GND
 *    J1-2  GND        →  GND
 *    J1-3  MOSI       →  PA7  (SPI1_MOSI, AF5)
 *    J1-4  SCLK       →  PA5  (SPI1_SCK,  AF5)
 *    J1-5  SCNn (CS)  →  PA8  (GPIO output, active LOW)
 *    J1-6  INTn       →  NC   (interrupt not used in this driver)
 *
 *  WIZ850io J2:          STM32 Pin     Function
 *    J2-1  GND        →  GND
 *    J2-2  3.3V       →  3.3V
 *    J2-3  3.3V       →  3.3V
 *    J2-4  NC         →  NC
 *    J2-5  RSTn       →  PB5  (GPIO output, active LOW)   ← NEW vs W5200
 *    J2-6  MISO       →  PA6  (SPI1_MISO, AF5)
 *
 * Target : STM32F401RCT6 @ 64 MHz
 * SPI    : SPI1  (APB2=64 MHz → prescaler /2 → 32 MHz)
 * DMA    : DMA2 Stream3 Channel3  (SPI1_TX — same as W5200 driver)
 */

#ifndef WIZ5500_H
#define WIZ5500_H

#include "stm32f4xx_hal.h"
#include "ad7606_config.h"
#include <stdint.h>

/* ═══════════════════════════════════════════════════════════════════
 * W5500 Common Register addresses
 * (used with BSB = 0x00, i.e. control byte = BSB|RW|OM = 0x00|rw|0x00)
 * ═══════════════════════════════════════════════════════════════════ */
#define W5500_MR            0x0000u  /* Mode Register                         */
#define W5500_GAR           0x0001u  /* Gateway IP Address (4 bytes)          */
#define W5500_SUBR          0x0005u  /* Subnet Mask (4 bytes)                 */
#define W5500_SHAR          0x0009u  /* Source MAC Address (6 bytes)          */
#define W5500_SIPR          0x000Fu  /* Source IP Address (4 bytes)           */
#define W5500_RTR           0x0019u  /* Retry Time (2 bytes) — was 0x0017 on W5200 */
#define W5500_RCR           0x001Bu  /* Retry Count (1 byte) — was 0x0019 on W5200 */
#define W5500_PHYCFGR       0x002Eu  /* PHY Config Register                   */
#define W5500_VERSIONR      0x0039u  /* Chip Version — always returns 0x04    */

/* ═══════════════════════════════════════════════════════════════════
 * W5500 Socket 0 Register addresses
 * (used with BSB = 0x08, i.e. control byte = 0x08|rw|0x00)
 * Socket register offsets are the same as W5200 but base is 0x0000
 * not 0x4000 — the BSB selects the block instead.
 * ═══════════════════════════════════════════════════════════════════ */
#define W5500_S0_MR         0x0000u  /* Socket Mode                           */
#define W5500_S0_CR         0x0001u  /* Socket Command                        */
#define W5500_S0_SR         0x0003u  /* Socket Status                         */
#define W5500_S0_PORT       0x0004u  /* Socket Source Port (2 bytes)          */
#define W5500_S0_DHAR       0x0006u  /* Destination MAC (6 bytes)             */
#define W5500_S0_DIPR       0x000Cu  /* Destination IP (4 bytes)              */
#define W5500_S0_DPORT      0x0010u  /* Destination Port (2 bytes)            */
#define W5500_S0_TXBUF_SIZE 0x001Eu  /* TX Buffer Size — write 16 for 16 KB   */
#define W5500_S0_RXBUF_SIZE 0x001Fu  /* RX Buffer Size — write 0  (no RX needed) */
#define W5500_S0_TX_FSR     0x0020u  /* TX Free Size (2 bytes)                */
#define W5500_S0_TX_RD      0x0022u  /* TX Read Pointer (2 bytes)             */
#define W5500_S0_TX_WR      0x0024u  /* TX Write Pointer (2 bytes)            */
#define W5500_S0_RX_RSR     0x0026u  /* RX Received Size (2 bytes)            */
#define W5500_S0_RX_RD      0x0028u  /* RX Read Pointer (2 bytes)             */

/* ═══════════════════════════════════════════════════════════════════
 * W5500 BSB (Block Select Bits) — upper 5 bits of control byte
 * ═══════════════════════════════════════════════════════════════════ */
#define W5500_BSB_COMMON    0x00u    /* Common registers  (0b00000 << 3)      */
#define W5500_BSB_S0_REG    0x08u    /* Socket 0 registers(0b00001 << 3)      */
#define W5500_BSB_S0_TX     0x10u    /* Socket 0 TX buffer(0b00010 << 3)      */
#define W5500_BSB_S0_RX     0x18u    /* Socket 0 RX buffer(0b00011 << 3)      */

/* ═══════════════════════════════════════════════════════════════════
 * W5500 control byte helpers
 * ctrl = BSB | RW | OM
 *   RW:  0x04 = Write,  0x00 = Read
 *   OM:  0x00 = VDM (variable length — used for all burst transfers)
 * ═══════════════════════════════════════════════════════════════════ */
#define W5500_CTRL_WRITE    0x04u
#define W5500_CTRL_READ     0x00u
#define W5500_CTRL_VDM      0x00u    /* Variable Data Mode                    */

/* Convenience macros */
#define W5500_CTRL_CMN_W    (W5500_BSB_COMMON | W5500_CTRL_WRITE | W5500_CTRL_VDM)
#define W5500_CTRL_CMN_R    (W5500_BSB_COMMON | W5500_CTRL_READ  | W5500_CTRL_VDM)
#define W5500_CTRL_S0R_W    (W5500_BSB_S0_REG | W5500_CTRL_WRITE | W5500_CTRL_VDM)
#define W5500_CTRL_S0R_R    (W5500_BSB_S0_REG | W5500_CTRL_READ  | W5500_CTRL_VDM)
#define W5500_CTRL_S0TX_W   (W5500_BSB_S0_TX  | W5500_CTRL_WRITE | W5500_CTRL_VDM)

/* ═══════════════════════════════════════════════════════════════════
 * Socket mode / command / status codes
 * These are identical between W5200 and W5500.
 * ═══════════════════════════════════════════════════════════════════ */
#define W5500_MR_UDP        0x02u
#define W5500_CR_OPEN       0x01u
#define W5500_CR_CLOSE      0x10u
#define W5500_CR_SEND       0x20u
#define W5500_SR_SOCK_UDP   0x22u
#define W5500_SR_SOCK_CLOSED 0x00u

/* W5500 TX buffer: 16 KB window (BSB=0x10, addr masked to 0x3FFF) */
#define W5500_S0_TX_MASK    0x3FFFu  /* 16 KB mask when TXBUF_SIZE=16         */

/* W5500 version register value */
#define W5500_EXPECTED_VERSION  0x04u

/* ═══════════════════════════════════════════════════════════════════
 * SPI1 GPIO — unchanged from W5200 driver
 * ═══════════════════════════════════════════════════════════════════ */
#define ETH_SPI_SCK_PIN     GPIO_PIN_5   /* PA5  AF5  SPI1_SCK   */
#define ETH_SPI_MISO_PIN    GPIO_PIN_6   /* PA6  AF5  SPI1_MISO  */
#define ETH_SPI_MOSI_PIN    GPIO_PIN_7   /* PA7  AF5  SPI1_MOSI  */

#define ETH_CS_PORT         GPIOA
#define ETH_CS_PIN          GPIO_PIN_8   /* PA8  GPIO output, active LOW  */

#define ETH_CS_ASSERT()     HAL_GPIO_WritePin(ETH_CS_PORT, ETH_CS_PIN, GPIO_PIN_RESET)
#define ETH_CS_DEASSERT()   HAL_GPIO_WritePin(ETH_CS_PORT, ETH_CS_PIN, GPIO_PIN_SET)

/* ── W5500 Hardware RESET pin (NEW — not present on W5200 module) ─── */
#define ETH_RST_PORT        GPIOB
#define ETH_RST_PIN         GPIO_PIN_5   /* PB5  GPIO output, active LOW */

#define ETH_RST_ASSERT()    HAL_GPIO_WritePin(ETH_RST_PORT, ETH_RST_PIN, GPIO_PIN_RESET)
#define ETH_RST_DEASSERT()  HAL_GPIO_WritePin(ETH_RST_PORT, ETH_RST_PIN, GPIO_PIN_SET)

/* ═══════════════════════════════════════════════════════════════════
 * DMA — identical to W5200 driver (same SPI1, same DMA stream)
 * ═══════════════════════════════════════════════════════════════════ */
#define ETH_DMA_STREAM      DMA2_Stream3
#define ETH_DMA_CHANNEL     DMA_CHANNEL_3
#define ETH_DMA_IRQn        DMA2_Stream3_IRQn
#define ETH_DMA_NVIC_PRIORITY  5u

/* ═══════════════════════════════════════════════════════════════════
 * TX frame layout
 * W5500 header = 3 bytes (vs W5200's 4 bytes)
 * Payload = 144 bytes (AD7606 batch, unchanged)
 * Total frame = 147 bytes
 * ═══════════════════════════════════════════════════════════════════ */
#define WIZ5500_HEADER_SIZE     3u
#define WIZ5500_PAYLOAD_SIZE    AD7606_BATCH_SIZE                      /* 144 */
#define WIZ5500_FRAME_SIZE      (WIZ5500_HEADER_SIZE + WIZ5500_PAYLOAD_SIZE)  /* 147 */

/* ═══════════════════════════════════════════════════════════════════
 * Driver status codes — identical to WIZ5200 for API compatibility
 * ═══════════════════════════════════════════════════════════════════ */
typedef enum {
    WIZ5500_OK            = 0,
    WIZ5500_ERR_BUSY      = 1,
    WIZ5500_ERR_NO_SPACE  = 2,
    WIZ5500_ERR_SOCKET    = 3,
    WIZ5500_ERR_PARAM     = 4
} WIZ5500_Status;

/* ═══════════════════════════════════════════════════════════════════
 * Network configuration — identical struct to WIZ5200_Config
 * ═══════════════════════════════════════════════════════════════════ */
typedef struct {
    uint8_t  mac[6];
    uint8_t  ip[4];
    uint8_t  subnet[4];
    uint8_t  gateway[4];
    uint8_t  dest_ip[4];
    uint16_t dest_port;
    uint16_t src_port;
} WIZ5500_Config;

/* ═══════════════════════════════════════════════════════════════════
 * Public API — same signatures as WIZ5200 driver
 * ═══════════════════════════════════════════════════════════════════ */
void           WIZ5500_Init(const WIZ5500_Config *cfg);
WIZ5500_Status WIZ5500_SetupSocket0(void);
WIZ5500_Status WIZ5500_SendBatch(const uint8_t *src_data, uint16_t len);
uint32_t       WIZ5500_GetDroppedPackets(void);
uint8_t        WIZ5500_IsTxBusy(void);
void           WIZ5500_OnDMATxComplete(void);

/* Exported handles needed by stm32f4xx_it.c */
extern SPI_HandleTypeDef  hspi1;
extern DMA_HandleTypeDef  hdma_spi1_tx;

#endif /* WIZ5500_H */
