/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : WIZ850io W5500 UDP test — STM32F401RCT6 @ 64 MHz
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "wiz5500.h"
#include <stdint.h>
#include <string.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */
/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define BATCH_FRAMES        4u
#define CHANNELS            16u
#define FRAME_SIZE          36u     /* 4 sync bytes + 16 ch * 2 bytes */
#define BATCH_SIZE          (BATCH_FRAMES * FRAME_SIZE)  /* 144 bytes */
#define SEND_INTERVAL_MS    10u     /* 100 pkt/s */
#define RAMP_STEP           100
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */
#define ETH_CS_LOW()   HAL_GPIO_WritePin(GPIOA, GPIO_PIN_8, GPIO_PIN_RESET)
#define ETH_CS_HIGH()  HAL_GPIO_WritePin(GPIOA, GPIO_PIN_8, GPIO_PIN_SET)
/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
SPI_HandleTypeDef hspi1;

/* USER CODE BEGIN PV */
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_SPI1_Init(void);

/* USER CODE BEGIN PFP */
static void Build_Frame(uint8_t *frame, uint32_t batch, uint8_t fi, int16_t ramp);
/* USER CODE END PFP */

/* USER CODE BEGIN 0 */
static void Build_Frame(uint8_t *frame, uint32_t batch, uint8_t fi, int16_t ramp)
{
    frame[0] = 0xDE; frame[1] = 0xAD; frame[2] = 0xBE; frame[3] = 0xEF;
    int16_t ch[16];
    ch[0]  =  ramp;  ch[1]  = -ramp;
    ch[2]  =  2500;  ch[3]  = -2500;
    ch[4] = ch[5] = ch[6] = ch[7]   = (int16_t)fi;
    ch[8] = ch[9] = ch[10] = ch[11] = (int16_t)(batch & 0x7FFF);
    ch[12] = 0x1234; ch[13] = 0x2345;
    ch[14] = 0x3456; ch[15] = 0x4567;
    for (int i = 0; i < 16; i++) {
        frame[4 + i*2]   = (uint8_t)((uint16_t)ch[i] >> 8);
        frame[4 + i*2+1] = (uint8_t)((uint16_t)ch[i] & 0xFF);
    }
}
/* USER CODE END 0 */

int main(void)
{
  /* USER CODE BEGIN 1 */
  /* USER CODE END 1 */

  HAL_Init();
  SystemClock_Config();
  MX_GPIO_Init();
  MX_SPI1_Init();

  /* USER CODE BEGIN 2 */

  /* Init W5500 */
  WIZ5500_Config eth_cfg = {
      .mac       = { 0x00, 0x08, 0xDC, 0x11, 0x22, 0x33 },
      .ip        = { 192, 168,   1,  20 },
      .subnet    = { 255, 255, 255,   0 },
      .gateway   = { 192, 168,   1,   1 },
      .dest_ip   = { 192, 168,   1, 100 },
      .dest_port = 5002u,
      .src_port  = 5001u,
  };
  WIZ5500_Init(&eth_cfg);

  /* Verify W5500 version register — must return 0x04, else SPI wiring fault */
  {
      uint8_t hdr[3] = {
          (uint8_t)(W5500_VERSIONR >> 8),
          (uint8_t)(W5500_VERSIONR & 0xFF),
          W5500_CTRL_CMN_R
      };
      uint8_t ver = 0;
      ETH_CS_LOW();
      HAL_SPI_Transmit(&hspi1, hdr, 3, 10);
      HAL_SPI_Receive (&hspi1, &ver, 1, 10);
      ETH_CS_HIGH();
      if (ver != 0x04) Error_Handler();
  }

  /* Open UDP socket */
  if (WIZ5500_SetupSocket0() != WIZ5500_OK)
      Error_Handler();

  uint32_t batch   = 0;
  uint32_t last_ms = 0;
  uint32_t sent_ok = 0;   /* watch in debugger */
  uint32_t drops   = 0;   /* watch in debugger */
  static uint8_t tx_buf[BATCH_SIZE];

  /* USER CODE END 2 */

  /* USER CODE BEGIN WHILE */
  while (1)
  {
      uint32_t now = HAL_GetTick();
      if ((now - last_ms) >= SEND_INTERVAL_MS)
      {
          last_ms = now;

          int32_t raw  = (int32_t)(batch * (uint32_t)RAMP_STEP) & 0xFFFF;
          int16_t ramp = (int16_t)(raw > 32767 ? 65535 - raw : raw);

          for (uint8_t fi = 0; fi < BATCH_FRAMES; fi++)
              Build_Frame(tx_buf + fi * FRAME_SIZE, batch, fi, ramp);

          WIZ5500_Status result = WIZ5500_SendBatch(tx_buf, BATCH_SIZE);
          if (result == WIZ5500_OK)
              sent_ok++;
          else
              drops = result;

          batch++;
      }
      (void)sent_ok;
      (void)drops;
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * HSE=25MHz | PLLM=25 | PLLN=384 | PLLP=DIV6 | PLLQ=8
  * VCO input=1MHz, VCO output=384MHz, SYSCLK=64MHz
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE2);

  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState       = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState   = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource  = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM       = 25;               /* VCO in  = 25/25 = 1 MHz   */
  RCC_OscInitStruct.PLL.PLLN       = 384;              /* VCO out = 384 MHz         */
  RCC_OscInitStruct.PLL.PLLP       = RCC_PLLP_DIV6;   /* SYSCLK  = 384/6 = 64 MHz  */
  RCC_OscInitStruct.PLL.PLLQ       = 8;                /* USB     = 384/8 = 48 MHz  */
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  RCC_ClkInitStruct.ClockType      = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                                   |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource   = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider  = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;   /* APB1 = 32 MHz */
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;   /* APB2 = 64 MHz */

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief SPI1 Initialization — 32 MHz, Mode 0, MSB first
  */
static void MX_SPI1_Init(void)
{
  /* USER CODE BEGIN SPI1_Init 0 */
  /* USER CODE END SPI1_Init 0 */
  /* USER CODE BEGIN SPI1_Init 1 */
  /* USER CODE END SPI1_Init 1 */

  hspi1.Instance               = SPI1;
  hspi1.Init.Mode              = SPI_MODE_MASTER;
  hspi1.Init.Direction         = SPI_DIRECTION_2LINES;
  hspi1.Init.DataSize          = SPI_DATASIZE_8BIT;
  hspi1.Init.CLKPolarity       = SPI_POLARITY_LOW;
  hspi1.Init.CLKPhase          = SPI_PHASE_1EDGE;
  hspi1.Init.NSS               = SPI_NSS_SOFT;
  hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_2;  /* 64/2 = 32 MHz */
  hspi1.Init.FirstBit          = SPI_FIRSTBIT_MSB;
  hspi1.Init.TIMode            = SPI_TIMODE_DISABLE;
  hspi1.Init.CRCCalculation    = SPI_CRCCALCULATION_DISABLE;
  hspi1.Init.CRCPolynomial     = 10;
  if (HAL_SPI_Init(&hspi1) != HAL_OK)
  {
    Error_Handler();
  }

  /* USER CODE BEGIN SPI1_Init 2 */
  /* USER CODE END SPI1_Init 2 */
}

/**
  * @brief GPIO Initialization
  * PA8 = ETH_CS  (starts HIGH — deasserted)
  * PB5 = ETH_RST (starts HIGH — not in reset)
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */
  /* USER CODE END MX_GPIO_Init_1 */

  __HAL_RCC_GPIOH_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /* PA8 ETH_CS — HIGH before configuring as output so it never glitches low */
  HAL_GPIO_WritePin(GPIOA, GPIO_PIN_8, GPIO_PIN_SET);
  GPIO_InitStruct.Pin   = GPIO_PIN_8;
  GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull  = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /* PB5 ETH_RST — HIGH before configuring as output */
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_5, GPIO_PIN_SET);
  GPIO_InitStruct.Pin   = GPIO_PIN_5;
  GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull  = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */
  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */
/* USER CODE END 4 */

void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  __disable_irq();
  while (1) { }
  /* USER CODE END Error_Handler_Debug */
}

#ifdef USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* USER CODE END 6 */
}
#endif
