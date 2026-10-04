/**
 * ============================================================================
 * Project: EV Dashboard & Predictive Thermal Telemetry System
 * Target: Texas Instruments TMS320F2800137 (LAUNCHXL-F2800137)
 * File: ili9488_spi.h
 * Description: Dedicated Dual-Panel EV Cockpit UI Engine:
 *              [LEFT: Current Live Details] | [RIGHT: Future Temperature Forecast]
 * ============================================================================
 */

#ifndef ILI9488_SPI_H
#define ILI9488_SPI_H

#include "driverlib.h"
#include "device.h"
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Display Dimensions (Landscape Mode) */
#define ILI9488_TFTWIDTH   480
#define ILI9488_TFTHEIGHT  320

/* 16-bit RGB565 Colors */
#define COLOR_BLACK        0x0000
#define COLOR_NAVY         0x000F
#define COLOR_DARKGREEN    0x03E0
#define COLOR_DARKCYAN     0x03EF
#define COLOR_MAROON       0x7800
#define COLOR_PURPLE       0x780F
#define COLOR_OLIVE        0x7BE0
#define COLOR_LIGHTGREY    0xC618
#define COLOR_DARKGREY     0x7BEF
#define COLOR_BLUE         0x001F
#define COLOR_GREEN        0x07E0
#define COLOR_CYAN         0x07FF
#define COLOR_RED          0xF800
#define COLOR_MAGENTA      0xF81F
#define COLOR_YELLOW       0xFFE0
#define COLOR_WHITE        0xFFFF
#define COLOR_ORANGE       0xFD20
#define COLOR_CARD_BG      0x10A2  /* Dark slate blue #0f172a */
#define COLOR_PANEL_BG     0x0841  /* Deep background */

/* Hardware Pin Mappings on LAUNCHXL-F2800137 */
#define TFT_CS_PIN         19      /* GPIO19 - Chip Select */
#define TFT_DC_PIN         4       /* GPIO4  - Data / Command */
#define TFT_RST_PIN        5       /* GPIO5  - Reset */
#define TFT_LED_PIN        6       /* GPIO6  - Backlight */

/* Driver Prototypes */
void ILI9488_Init(void);
void ILI9488_SendCommand(uint8_t cmd);
void ILI9488_SendData(uint8_t data);
void ILI9488_SendData16(uint16_t data);
void ILI9488_SetAddressWindow(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1);
void ILI9488_FillScreen(uint16_t color);
void ILI9488_FillRect(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t color);
void ILI9488_DrawRect(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t color);
void ILI9488_DrawChar(uint16_t x, uint16_t y, char c, uint16_t color, uint16_t bg, uint8_t size);
void ILI9488_DrawString(uint16_t x, uint16_t y, const char *str, uint16_t color, uint16_t bg, uint8_t size);

/* Dual-Panel Cockpit Drawing Functions */
void ILI9488_DrawDashboardLayout(void);
void ILI9488_UpdateLiveAndPredictionUI(
    float speed_kmh, float rpm, float current_a, float volt_v, float torque_nm, float power_w,
    float temp_current, float pred_1m, float pred_5m, float pred_15m, float pred_30m,
    float dT_dt, uint8_t derate_active, float max_allowable_current_a
);

#ifdef __cplusplus
}
#endif

#endif /* ILI9488_SPI_H */
