/* ad7606_config.h — AD7606 driver configuration
 *
 * Target: STM32F401RCT6 @ 64 MHz
 *
 * Clock tree:
 *   HSE        =  8 MHz
 *   PLLM       =  8      → VCO input  = 1 MHz
 *   PLLN       = 256     → VCO output = 256 MHz
 *   PLLP       =  4      → SYSCLK     = 64 MHz
 *   PLLQ       =  6      → (USB not used)
 *
 *   AHB  /1  → HCLK  = 64 MHz
 *   APB1 /2  → PCLK1 = 32 MHz   (SPI2, SPI3, TIM2)
 *   APB2 /1  → PCLK2 = 64 MHz   (SPI1 → W5200)
 *
 *   TIM2_CLK = APB1 × 2 = 64 MHz  (APB1 prescaler ≠ 1 → ×2 rule)
 *   ARR      = 64 000 000 / 100 000 − 1 = 639  → 100 kHz exact
 *
 *   SPI1 (W5200):  APB2 / 4 = 16 MHz  ≤ W5200 max 33.33 MHz  ✓
 *   SPI2/3 (ADC):  APB1 / 2 = 16 MHz  ≤ AD7606 max 23 MHz    ✓
 *
 * Flash latency: FLASH_LATENCY_2
 *   F401 DS Table 6 (VCC 2.7–3.6 V):
 *     0 WS: 0–30 MHz | 1 WS: 30–64 MHz | 2 WS: 64–84 MHz
 *   64 MHz sits on the upper boundary of the 1 WS range.
 *   FLASH_LATENCY_2 used to guarantee correct operation at exactly 64 MHz.
 */

#ifndef AD7606_CONFIG_H
#define AD7606_CONFIG_H

/* ── Sample rate ─────────────────────────────────────────────────────────── */
#define AD7606_SAMPLE_RATE_HZ       100000u
#define AD7606_TIM2_CLK_HZ        64000000u   /* APB1(32 MHz) × 2 = 64 MHz   */
#define AD7606_TIM_ARR    ((AD7606_TIM2_CLK_HZ / AD7606_SAMPLE_RATE_HZ) - 1u) /* 639 */

/* ── Voltage reference ───────────────────────────────────────────────────── */
#define AD7606_VREF_MV              5000
#define AD7606_FULLSCALE_CODE      32767

/* ── Channel / batch config ─────────────────────────────────────────────── */
#define AD7606_NUM_CHANNELS           16u
#define AD7606_CHANNELS_PER_SPI_BURST  4u
#define AD7606_ROUNDS                  2u
#define AD7606_BATCH_FRAMES            4u

/* ── Frame / batch sizes ─────────────────────────────────────────────────── */
#define AD7606_SYNC_BYTES             4u
#define AD7606_FRAME_DATA_BYTES      (AD7606_NUM_CHANNELS * 2u)                     /* 32 */
#define AD7606_FRAME_SIZE            (AD7606_SYNC_BYTES + AD7606_FRAME_DATA_BYTES)  /* 36 */
#define AD7606_BATCH_SIZE            (AD7606_BATCH_FRAMES * AD7606_FRAME_SIZE)      /* 144 */

/* ── Control pins ────────────────────────────────────────────────────────── */
#define ADC_CS_PORT               GPIOA
#define ADC_CS_PIN                GPIO_PIN_4

#define ADC_CONVST_PORT           GPIOB
#define ADC_CONVST_PIN            GPIO_PIN_0

#define ADC_BUSY_PORT             GPIOB
#define ADC_BUSY_PIN              GPIO_PIN_1

#define ADC_RESET_PORT            GPIOB
#define ADC_RESET_PIN             GPIO_PIN_2

#define ADC_LED_PORT              GPIOC
#define ADC_LED_PIN               GPIO_PIN_13

/* ── SPI pins ────────────────────────────────────────────────────────────── */
#define ADC_SPI2_SCK_PORT         GPIOB
#define ADC_SPI2_SCK_PIN          GPIO_PIN_13   /* AF5 */
#define ADC_SPI2_MISO_PORT        GPIOB
#define ADC_SPI2_MISO_PIN         GPIO_PIN_14   /* AF5 */

#define ADC_SPI3_SCK_PORT         GPIOB
#define ADC_SPI3_SCK_PIN          GPIO_PIN_3    /* AF6 */
#define ADC_SPI3_MISO_PORT        GPIOB
#define ADC_SPI3_MISO_PIN         GPIO_PIN_4    /* AF6 */

/* ── DMA streams (F401 RM Table 20 — identical to F411) ─────────────────── */
#define ADC_DMA_SPI2_STREAM       DMA1_Stream3
#define ADC_DMA_SPI2_CHANNEL      DMA_CHANNEL_0
#define ADC_DMA_SPI2_IRQn         DMA1_Stream3_IRQn

#define ADC_DMA_SPI3_STREAM       DMA1_Stream0
#define ADC_DMA_SPI3_CHANNEL      DMA_CHANNEL_0
#define ADC_DMA_SPI3_IRQn         DMA1_Stream0_IRQn

/* ── NVIC priorities ─────────────────────────────────────────────────────── */
#define ADC_DMA_NVIC_PRIORITY     0
#define ADC_EXTI1_NVIC_PRIORITY   1
#define ADC_TIM2_NVIC_PRIORITY    2

/* ── CONVST pulse: 4 NOPs @ 64 MHz = 62.5 ns ≥ 25 ns min ───────────────── */
#define ADC_CONVST_NOP_COUNT      4u

#endif /* AD7606_CONFIG_H */
