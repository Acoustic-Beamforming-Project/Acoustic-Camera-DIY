/**
 * @file wizchip_conf.h
 * @brief WIZnet ioLibrary configuration for STM32F401 + SPI1 (polling mode).
 *
 * This file configures the ioLibrary HAL (w5500.c / w5500.h) for use with the
 * STM32F4 HAL in byte-by-byte SPI mode.  The higher-level driver (wiz5500.c)
 * registers its SPI callbacks here via wizchip_conf_init().
 *
 * _WIZCHIP_ must be defined before including w5500.h.
 */

#ifndef _WIZCHIP_CONF_H_
#define _WIZCHIP_CONF_H_

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* ── Chip selection ─────────────────────────────────────────────────────── */
#ifndef _WIZCHIP_
#define _WIZCHIP_   5500
#endif

/* ── SPI I/O mode ── byte (non-burst) only for this project ─────────────── */
#define _WIZCHIP_IO_MODE_SPI_VDM_   /**< Variable Data Mode — VDM */

/* ── Critical section: bare-metal, no RTOS → disable interrupts ────────── */
#define _WIZCHIP_CRITICAL_SECTION_   1

/* ═══════════════════════════════════════════════════════════════════════════
 * WIZCHIP handle structure
 *
 * The ioLibrary w5500.c references the global `WIZCHIP` struct for:
 *   - WIZCHIP.CS._select() / _deselect()     — chip-select
 *   - WIZCHIP.IF.SPI._write_byte()            — single-byte SPI write
 *   - WIZCHIP.IF.SPI._read_byte()             — single-byte SPI read
 *   - WIZCHIP.IF.SPI._write_burst()           — burst write (optional, NULL = byte mode)
 *   - WIZCHIP.IF.SPI._read_burst()            — burst read  (optional, NULL = byte mode)
 *   - WIZCHIP.CRIS._enter() / _exit()         — critical section
 * ═══════════════════════════════════════════════════════════════════════════ */

typedef struct __WIZCHIPHandle {
    struct {
        void (*_enter)(void);   /**< Enter critical section  */
        void (*_exit)(void);    /**< Exit  critical section  */
    } CRIS;

    struct {
        void (*_select)(void);   /**< Assert   CS (active LOW) */
        void (*_deselect)(void); /**< Deassert CS              */
    } CS;

    union {
        struct {
            void    (*_write_byte)(uint8_t wb);
            uint8_t (*_read_byte)(void);
            void    (*_write_burst)(uint8_t *pBuf, uint16_t len);
            void    (*_read_burst)(uint8_t *pBuf, uint16_t len);
        } SPI;
    } IF;
} WIZCHIPHandle_t;

extern WIZCHIPHandle_t WIZCHIP;   /**< Defined in wiz5500.c */

/* ── Convenience macros used by w5500.c ────────────────────────────────── */
#define WIZCHIP_CRITICAL_ENTER()    WIZCHIP.CRIS._enter()
#define WIZCHIP_CRITICAL_EXIT()     WIZCHIP.CRIS._exit()

#ifdef __cplusplus
}
#endif

#endif /* _WIZCHIP_CONF_H_ */
