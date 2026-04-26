# Firmware Context — STM32 Microcontroller

## Purpose
This folder contains all STM32 firmware for the microphone array board.
Responsibilities:
- Initialize and configure ADC with DMA for multi-channel simultaneous sampling
- Buffer audio samples and packetize them
- Stream packets to PC over USB CDC (appears as virtual COM port)

## Hardware Details
- **MCU**: STM32 (HAL-based project, CubeMX generated)
- **Microphones**: Analog MEMS or electret mics on ADC pins
- **Channels**: 8 microphone channels
- **Sampling**: ADC in scan mode + DMA circular buffer
- **Communication**: USB CDC (usbd_cdc_if.c / CDC_Transmit_FS)

## Packet Protocol
```c
// Packet structure sent over USB CDC
uint8_t packet[5] = {
    0xAA,                    // start byte
    channel_id,              // 0–7
    (uint8_t)(value >> 8),   // high byte
    (uint8_t)(value & 0xFF), // low byte
    0xFF                     // end byte
};
CDC_Transmit_FS(packet, 5);
```

## Key Files / Conventions
- `Core/Src/main.c` — main loop, HAL init
- `Core/Src/usbd_cdc_if.c` — USB TX/RX callbacks
- `Core/Inc/` — header files
- Use **HAL_ prefix** for all peripheral calls (HAL_ADC_Start_DMA, etc.)
- Use **LL_ prefix** only if explicitly switching to Low Layer for performance
- Do NOT use blocking HAL_Delay() inside DMA callbacks

## Coding Rules for This Folder
- Language: **C (C11)**
- Style: STM32CubeIDE default (2-space or 4-space indent is fine, be consistent)
- All ISR handlers: keep minimal, set flags, do work in main loop
- DMA complete callback: `HAL_ADC_ConvCpltCallback` — copy buffer, set ready flag
- Never call `CDC_Transmit_FS` from inside an ISR directly — buffer and transmit from main loop

## Common Tasks Gemini Should Help With
- Writing DMA circular buffer handling for multi-channel ADC
- Implementing the packetization loop
- USB CDC transmit with flow control (check CDC_Transmit_FS return value)
- Configuring TIM-triggered ADC for precise sample rate
- Debugging: adding UART printf for debug without breaking USB CDC