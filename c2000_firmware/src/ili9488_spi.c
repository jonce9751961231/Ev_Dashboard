/**
 * ============================================================================
 * Project: EV Dashboard & Predictive Thermal Telemetry System
 * Target: Texas Instruments TMS320F2800137
 * File: ili9488_spi.c
 * Description: Dedicated Dual-Panel EV Cockpit UI Renderer:
 *              [LEFT: Current Live Details] | [RIGHT: Future Temperature Forecast]
 * ============================================================================
 */

#include "../include/ili9488_spi.h"
#include <stdio.h>
#include <string.h>

/* Basic 5x7 ASCII Font Bitmap */
static const uint8_t font5x7[] = {
    0x00, 0x00, 0x00, 0x00, 0x00, // Space (32)
    0x00, 0x00, 0x5F, 0x00, 0x00, // !
    0x00, 0x07, 0x00, 0x07, 0x00, // "
    0x14, 0x7F, 0x14, 0x7F, 0x14, // #
    0x24, 0x2A, 0x7F, 0x2A, 0x12, // $
    0x23, 0x13, 0x08, 0x64, 0x62, // %
    0x36, 0x49, 0x55, 0x22, 0x50, // &
    0x00, 0x05, 0x03, 0x00, 0x00, // '
    0x00, 0x1C, 0x22, 0x41, 0x00, // (
    0x00, 0x41, 0x22, 0x1C, 0x00, // )
    0x08, 0x2A, 0x1C, 0x2A, 0x08, // *
    0x08, 0x08, 0x3E, 0x08, 0x08, // +
    0x00, 0x50, 0x30, 0x00, 0x00, // ,
    0x08, 0x08, 0x08, 0x08, 0x08, // -
    0x00, 0x60, 0x60, 0x00, 0x00, // .
    0x20, 0x10, 0x08, 0x04, 0x02, // /
    0x3E, 0x51, 0x49, 0x45, 0x3E, // 0 (48)
    0x00, 0x42, 0x7F, 0x40, 0x00, // 1
    0x42, 0x61, 0x51, 0x49, 0x46, // 2
    0x21, 0x41, 0x45, 0x4B, 0x31, // 3
    0x18, 0x14, 0x12, 0x7F, 0x10, // 4
    0x27, 0x45, 0x45, 0x45, 0x39, // 5
    0x3C, 0x4A, 0x49, 0x49, 0x30, // 6
    0x01, 0x71, 0x09, 0x05, 0x03, // 7
    0x36, 0x49, 0x49, 0x49, 0x36, // 8
    0x06, 0x49, 0x49, 0x29, 0x1E, // 9
    0x00, 0x36, 0x36, 0x00, 0x00, // : (58)
    0x00, 0x56, 0x36, 0x00, 0x00, // ;
    0x08, 0x14, 0x22, 0x41, 0x00, // <
    0x14, 0x14, 0x14, 0x14, 0x14, // =
    0x00, 0x41, 0x22, 0x14, 0x08, // >
    0x02, 0x01, 0x51, 0x09, 0x06, // ?
    0x32, 0x49, 0x79, 0x41, 0x3E, // @
    0x7E, 0x11, 0x11, 0x11, 0x7E, // A (65)
    0x7F, 0x49, 0x49, 0x49, 0x36, // B
    0x3E, 0x41, 0x41, 0x41, 0x22, // C
    0x7F, 0x41, 0x41, 0x22, 0x1C, // D
    0x7F, 0x49, 0x49, 0x49, 0x41, // E
    0x7F, 0x09, 0x09, 0x09, 0x01, // F
    0x3E, 0x41, 0x49, 0x49, 0x7A, // G
    0x7F, 0x08, 0x08, 0x08, 0x7F, // H
    0x00, 0x41, 0x7F, 0x41, 0x00, // I
    0x20, 0x40, 0x41, 0x3F, 0x01, // J
    0x7F, 0x08, 0x14, 0x22, 0x41, // K
    0x7F, 0x40, 0x40, 0x40, 0x40, // L
    0x7F, 0x02, 0x0C, 0x02, 0x7F, // M
    0x7F, 0x04, 0x08, 0x10, 0x7F, // N
    0x3E, 0x41, 0x41, 0x41, 0x3E, // O
    0x7F, 0x09, 0x09, 0x09, 0x06, // P
    0x3E, 0x41, 0x51, 0x21, 0x5E, // Q
    0x7F, 0x09, 0x19, 0x29, 0x46, // R
    0x46, 0x49, 0x49, 0x49, 0x31, // S
    0x01, 0x01, 0x7F, 0x01, 0x01, // T
    0x3F, 0x40, 0x40, 0x40, 0x3F, // U
    0x1F, 0x20, 0x40, 0x20, 0x1F, // V
    0x7F, 0x20, 0x18, 0x20, 0x7F, // W
    0x63, 0x14, 0x08, 0x14, 0x63, // X
    0x03, 0x04, 0x78, 0x04, 0x03, // Y
    0x61, 0x51, 0x49, 0x45, 0x43, // Z (90)
    0x00, 0x7F, 0x41, 0x41, 0x00, // [
    0x02, 0x04, 0x08, 0x10, 0x20, // \
    0x00, 0x41, 0x41, 0x7F, 0x00, // ]
    0x04, 0x02, 0x01, 0x02, 0x04, // ^
    0x40, 0x40, 0x40, 0x40, 0x40, // _
    0x00, 0x01, 0x02, 0x04, 0x00, // `
    0x20, 0x54, 0x54, 0x54, 0x78, // a (97)
    0x7F, 0x48, 0x44, 0x44, 0x38, // b
    0x38, 0x44, 0x44, 0x44, 0x20, // c
    0x38, 0x44, 0x44, 0x48, 0x7F, // d
    0x38, 0x54, 0x54, 0x54, 0x18, // e
    0x08, 0x7E, 0x09, 0x01, 0x02, // f
    0x0C, 0x52, 0x52, 0x52, 0x3E, // g
    0x7F, 0x08, 0x04, 0x04, 0x78, // h
    0x00, 0x44, 0x7D, 0x40, 0x00, // i
    0x20, 0x40, 0x44, 0x3D, 0x00, // j
    0x7F, 0x10, 0x28, 0x44, 0x00, // k
    0x00, 0x41, 0x7F, 0x40, 0x00, // l
    0x7C, 0x04, 0x18, 0x04, 0x78, // m
    0x7C, 0x08, 0x04, 0x04, 0x78, // n
    0x38, 0x44, 0x44, 0x44, 0x38, // o
    0x7C, 0x14, 0x14, 0x14, 0x08, // p
    0x08, 0x14, 0x14, 0x18, 0x7C, // q
    0x7C, 0x08, 0x04, 0x04, 0x08, // r
    0x48, 0x54, 0x54, 0x54, 0x20, // s
    0x04, 0x3F, 0x44, 0x40, 0x20, // t
    0x3C, 0x40, 0x40, 0x20, 0x7C, // u
    0x1C, 0x20, 0x40, 0x20, 0x1C, // v
    0x3C, 0x40, 0x30, 0x40, 0x3C, // w
    0x44, 0x28, 0x10, 0x28, 0x44, // x
    0x0C, 0x50, 0x50, 0x50, 0x3C, // y
    0x44, 0x64, 0x54, 0x4C, 0x44, // z (122)
    0x00, 0x08, 0x36, 0x41, 0x00, // {
    0x00, 0x00, 0x7F, 0x00, 0x00, // |
    0x00, 0x41, 0x36, 0x08, 0x00, // }
    0x08, 0x08, 0x2A, 0x1C, 0x08  // ~
};

/* Helper Functions for GPIO & SPI */
static inline void CS_LOW(void)  { GPIO_writePin(TFT_CS_PIN, 0); }
static inline void CS_HIGH(void) { GPIO_writePin(TFT_CS_PIN, 1); }
static inline void DC_CMD(void)  { GPIO_writePin(TFT_DC_PIN, 0); }
static inline void DC_DATA(void) { GPIO_writePin(TFT_DC_PIN, 1); }

static void SPI_WriteByte(uint8_t data) {
    SPI_writeDataBlockingNonFIFO(SPIA_BASE, ((uint16_t)data << 8));
}

void ILI9488_SendCommand(uint8_t cmd) {
    DC_CMD();
    CS_LOW();
    SPI_WriteByte(cmd);
    CS_HIGH();
}

void ILI9488_SendData(uint8_t data) {
    DC_DATA();
    CS_LOW();
    SPI_WriteByte(data);
    CS_HIGH();
}

void ILI9488_SetAddressWindow(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1) {
    ILI9488_SendCommand(0x2A); // Column Addr Set
    ILI9488_SendData(x0 >> 8);
    ILI9488_SendData(x0 & 0xFF);
    ILI9488_SendData(x1 >> 8);
    ILI9488_SendData(x1 & 0xFF);

    ILI9488_SendCommand(0x2B); // Row Addr Set
    ILI9488_SendData(y0 >> 8);
    ILI9488_SendData(y0 & 0xFF);
    ILI9488_SendData(y1 >> 8);
    ILI9488_SendData(y1 & 0xFF);

    ILI9488_SendCommand(0x2C); // Memory Write
}

void ILI9488_Init(void) {
    // 1. Setup Control GPIOs
    GPIO_setPinConfig(GPIO_19_GPIO19); // CS
    GPIO_setDirectionMode(TFT_CS_PIN, GPIO_DIR_MODE_OUT);
    CS_HIGH();

    GPIO_setPinConfig(GPIO_4_GPIO4);   // DC
    GPIO_setDirectionMode(TFT_DC_PIN, GPIO_DIR_MODE_OUT);
    DC_DATA();

    GPIO_setPinConfig(GPIO_5_GPIO5);   // RST
    GPIO_setDirectionMode(TFT_RST_PIN, GPIO_DIR_MODE_OUT);

    GPIO_setPinConfig(GPIO_6_GPIO6);   // LED Backlight
    GPIO_setDirectionMode(TFT_LED_PIN, GPIO_DIR_MODE_OUT);
    GPIO_writePin(TFT_LED_PIN, 1);     // Backlight ON

    // 2. Hardware SPI-A Initialization (20 MHz)
    GPIO_setPinConfig(GPIO_16_SPISIMO_A);
    GPIO_setPinConfig(GPIO_18_SPICLK_A);

    SPI_disableModule(SPIA_BASE);
    SPI_setConfig(SPIA_BASE, DEVICE_LSPCLK_FREQ, SPI_PROT_POL0PHA0,
                  SPI_MODE_MASTER, 20000000, 8);
    SPI_enableModule(SPIA_BASE);

    // 3. Hardware Reset Pulse
    GPIO_writePin(TFT_RST_PIN, 1);
    DEVICE_DELAY_US(10000);
    GPIO_writePin(TFT_RST_PIN, 0);
    DEVICE_DELAY_US(20000);
    GPIO_writePin(TFT_RST_PIN, 1);
    DEVICE_DELAY_US(120000);

    // 4. Initialization Sequence for ILI9488
    ILI9488_SendCommand(0xE0); // Positive Gamma Control
    ILI9488_SendData(0x00); ILI9488_SendData(0x03); ILI9488_SendData(0x09);
    ILI9488_SendData(0x08); ILI9488_SendData(0x16); ILI9488_SendData(0x0A);
    ILI9488_SendData(0x3F); ILI9488_SendData(0x78); ILI9488_SendData(0x4C);
    ILI9488_SendData(0x09); ILI9488_SendData(0x0A); ILI9488_SendData(0x08);
    ILI9488_SendData(0x16); ILI9488_SendData(0x1A); ILI9488_SendData(0x0F);

    ILI9488_SendCommand(0xE1); // Negative Gamma Control
    ILI9488_SendData(0x00); ILI9488_SendData(0x16); ILI9488_SendData(0x19);
    ILI9488_SendData(0x03); ILI9488_SendData(0x0F); ILI9488_SendData(0x05);
    ILI9488_SendData(0x32); ILI9488_SendData(0x45); ILI9488_SendData(0x46);
    ILI9488_SendData(0x04); ILI9488_SendData(0x0E); ILI9488_SendData(0x0D);
    ILI9488_SendData(0x35); ILI9488_SendData(0x37); ILI9488_SendData(0x0F);

    ILI9488_SendCommand(0xC0); // Power Control 1
    ILI9488_SendData(0x17); ILI9488_SendData(0x15);

    ILI9488_SendCommand(0xC1); // Power Control 2
    ILI9488_SendData(0x41);

    ILI9488_SendCommand(0xC5); // VCOM Control
    ILI9488_SendData(0x00); ILI9488_SendData(0x12); ILI9488_SendData(0x80);

    ILI9488_SendCommand(0x36); // Memory Access Control (Landscape Mode)
    ILI9488_SendData(0xE8);

    ILI9488_SendCommand(0x3A); // Pixel Format 16-bit RGB565
    ILI9488_SendData(0x55);

    ILI9488_SendCommand(0xB0); // Interface Mode Control
    ILI9488_SendData(0x00);

    ILI9488_SendCommand(0xB1); // Frame Rate 60Hz
    ILI9488_SendData(0xA0);

    ILI9488_SendCommand(0xB6); // Display Function Control
    ILI9488_SendData(0x02); ILI9488_SendData(0x02);

    ILI9488_SendCommand(0x11); // Sleep OUT
    DEVICE_DELAY_US(120000);

    ILI9488_SendCommand(0x29); // Display ON
    DEVICE_DELAY_US(20000);

    ILI9488_FillScreen(COLOR_BLACK);
}

void ILI9488_FillRect(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t color) {
    if ((x >= ILI9488_TFTWIDTH) || (y >= ILI9488_TFTHEIGHT)) return;
    if ((x + w - 1) >= ILI9488_TFTWIDTH)  w = ILI9488_TFTWIDTH - x;
    if ((y + h - 1) >= ILI9488_TFTHEIGHT) h = ILI9488_TFTHEIGHT - y;

    ILI9488_SetAddressWindow(x, y, x + w - 1, y + h - 1);
    DC_DATA();
    CS_LOW();

    uint8_t hi = color >> 8;
    uint8_t lo = color & 0xFF;
    uint32_t total_pixels = (uint32_t)w * h;

    for (uint32_t i = 0; i < total_pixels; i++) {
        SPI_WriteByte(hi);
        SPI_WriteByte(lo);
    }
    CS_HIGH();
}

void ILI9488_FillScreen(uint16_t color) {
    ILI9488_FillRect(0, 0, ILI9488_TFTWIDTH, ILI9488_TFTHEIGHT, color);
}

void ILI9488_DrawRect(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t color) {
    ILI9488_FillRect(x, y, w, 1, color);
    ILI9488_FillRect(x, y + h - 1, w, 1, color);
    ILI9488_FillRect(x, y, 1, h, color);
    ILI9488_FillRect(x + w - 1, y, 1, h, color);
}

void ILI9488_DrawChar(uint16_t x, uint16_t y, char c, uint16_t color, uint16_t bg, uint8_t size) {
    if (c < 32 || c > 126) c = ' ';
    uint16_t font_idx = (c - 32) * 5;

    for (int8_t i = 0; i < 5; i++) {
        uint8_t line = font5x7[font_idx + i];
        for (int8_t j = 0; j < 8; j++) {
            if (line & 0x1) {
                if (size == 1) {
                    ILI9488_FillRect(x + i, y + j, 1, 1, color);
                } else {
                    ILI9488_FillRect(x + (i * size), y + (j * size), size, size, color);
                }
            } else if (bg != color) {
                if (size == 1) {
                    ILI9488_FillRect(x + i, y + j, 1, 1, bg);
                } else {
                    ILI9488_FillRect(x + (i * size), y + (j * size), size, size, bg);
                }
            }
            line >>= 1;
        }
    }
}

void ILI9488_DrawString(uint16_t x, uint16_t y, const char *str, uint16_t color, uint16_t bg, uint8_t size) {
    while (*str) {
        ILI9488_DrawChar(x, y, *str, color, bg, size);
        x += (6 * size);
        str++;
    }
}

/**
 * @brief Draws Dedicated Static Layout: [LEFT: Current Details] | [RIGHT: Future Predictions]
 */
void ILI9488_DrawDashboardLayout(void) {
    ILI9488_FillScreen(COLOR_BLACK);

    // 1. Top Header
    ILI9488_FillRect(0, 0, 480, 34, COLOR_CARD_BG);
    ILI9488_DrawString(12, 9, "AURA EV COCKPIT", COLOR_CYAN, COLOR_CARD_BG, 2);
    ILI9488_DrawString(260, 9, "TI TMS320F2800137", COLOR_WHITE, COLOR_CARD_BG, 2);

    // 2. Left Panel: CURRENT LIVE DETAILS
    ILI9488_DrawRect(6, 40, 230, 226, COLOR_DARKCYAN);
    ILI9488_FillRect(7, 41, 228, 20, COLOR_NAVY);
    ILI9488_DrawString(14, 46, "CURRENT DETAILS [LIVE]", COLOR_CYAN, COLOR_NAVY, 1);

    ILI9488_DrawString(14, 68, "SPEED & RPM:", COLOR_LIGHTGREY, COLOR_BLACK, 1);
    ILI9488_DrawString(14, 134, "MEASURED MOTOR TEMP:", COLOR_LIGHTGREY, COLOR_BLACK, 1);
    ILI9488_DrawString(14, 190, "ELECTRICAL & TORQUE:", COLOR_LIGHTGREY, COLOR_BLACK, 1);

    // 3. Right Panel: FUTURE TEMPERATURE PREDICTIONS
    ILI9488_DrawRect(244, 40, 230, 226, COLOR_PURPLE);
    ILI9488_FillRect(245, 41, 228, 20, COLOR_MAROON);
    ILI9488_DrawString(252, 46, "FUTURE TEMP FORECAST [AI]", COLOR_MAGENTA, COLOR_MAROON, 1);

    ILI9488_DrawString(252, 68, "+1 min Forecast:", COLOR_LIGHTGREY, COLOR_BLACK, 1);
    ILI9488_DrawString(252, 108, "+5 min Forecast (Warn):", COLOR_LIGHTGREY, COLOR_BLACK, 1);
    ILI9488_DrawString(252, 148, "+15 min Forecast:", COLOR_LIGHTGREY, COLOR_BLACK, 1);
    ILI9488_DrawString(252, 188, "+30 min Equilibrium:", COLOR_LIGHTGREY, COLOR_BLACK, 1);
    ILI9488_DrawString(252, 228, "Thermal Rate (dT/dt):", COLOR_LIGHTGREY, COLOR_BLACK, 1);

    // 4. Bottom Alert Banner
    ILI9488_FillRect(0, 272, 480, 48, COLOR_CARD_BG);
    ILI9488_DrawString(14, 288, "SAFETY STATUS: OPTIMAL (FULL POWER ALLOWED)", COLOR_GREEN, COLOR_CARD_BG, 1);
}

/**
 * @brief High-Speed 10 Hz Live Dashboard Value Updater
 */
void ILI9488_UpdateLiveAndPredictionUI(
    float speed_kmh, float rpm, float current_a, float volt_v, float torque_nm, float power_w,
    float temp_current, float pred_1m, float pred_5m, float pred_15m, float pred_30m,
    float dT_dt, uint8_t derate_active, float max_allowable_current_a
) {
    char buf[32];

    // ================= LEFT PANEL: CURRENT DETAILS =================
    // 1. Speed (Large 3x) & RPM
    snprintf(buf, sizeof(buf), "%5.1f", speed_kmh);
    ILI9488_DrawString(14, 82, buf, COLOR_CYAN, COLOR_BLACK, 3);
    ILI9488_DrawString(125, 84, "km/h", COLOR_WHITE, COLOR_BLACK, 1);
    snprintf(buf, sizeof(buf), "%4.0f RPM", rpm);
    ILI9488_DrawString(125, 98, buf, COLOR_YELLOW, COLOR_BLACK, 1);

    // 2. Measured Current Temperature (Large 3x)
    snprintf(buf, sizeof(buf), "%5.1f C", temp_current);
    uint16_t temp_col = (temp_current > 85.0f) ? COLOR_RED : (temp_current > 65.0f ? COLOR_ORANGE : COLOR_GREEN);
    ILI9488_DrawString(14, 148, buf, temp_col, COLOR_BLACK, 3);

    // 3. Current, Voltage, Torque, Power
    snprintf(buf, sizeof(buf), "I: %4.1f A | V: %4.1f V", current_a, volt_v);
    ILI9488_DrawString(14, 206, buf, COLOR_WHITE, COLOR_BLACK, 1);

    snprintf(buf, sizeof(buf), "T: %4.2f Nm | P: %4.0f W", torque_nm, power_w);
    ILI9488_DrawString(14, 224, buf, COLOR_GREENYELLOW, COLOR_BLACK, 1);

    // ================= RIGHT PANEL: FUTURE PREDICTIONS =================
    // 1. +1 min Pred
    snprintf(buf, sizeof(buf), "%5.1f C", pred_1m);
    ILI9488_DrawString(380, 68, buf, COLOR_CYAN, COLOR_BLACK, 1);

    // 2. +5 min Pred (Large 2x for prominent warning)
    snprintf(buf, sizeof(buf), "%5.1f C", pred_5m);
    uint16_t p5_col = (pred_5m > 85.0f) ? COLOR_RED : (pred_5m > 70.0f ? COLOR_ORANGE : COLOR_WHITE);
    ILI9488_DrawString(360, 104, buf, p5_col, COLOR_BLACK, 2);

    // 3. +15 min Pred
    snprintf(buf, sizeof(buf), "%5.1f C", pred_15m);
    uint16_t p15_col = (pred_15m > 85.0f) ? COLOR_RED : COLOR_WHITE;
    ILI9488_DrawString(380, 148, buf, p15_col, COLOR_BLACK, 1);

    // 4. +30 min Equilibrium
    snprintf(buf, sizeof(buf), "%5.1f C", pred_30m);
    ILI9488_DrawString(380, 188, buf, COLOR_WHITE, COLOR_BLACK, 1);

    // 5. Thermal Rate (dT/dt)
    snprintf(buf, sizeof(buf), "%+5.2f C/s", dT_dt);
    uint16_t rate_col = (dT_dt > 0.10f) ? COLOR_RED : COLOR_CYAN;
    ILI9488_DrawString(375, 228, buf, rate_col, COLOR_BLACK, 1);

    // ================= BOTTOM ALERT & DERATING BANNER =================
    if (derate_active) {
        snprintf(buf, sizeof(buf), "ALERT: THERMAL DERATING ACTIVE! CURRENT LIMITED TO %4.1f A", max_allowable_current_a);
        ILI9488_DrawString(14, 288, buf, COLOR_RED, COLOR_CARD_BG, 1);
    } else {
        snprintf(buf, sizeof(buf), "STATUS: OPTIMAL (FULL TORQUE ALLOWED | LIMIT: %4.1f A)     ", max_allowable_current_a);
        ILI9488_DrawString(14, 288, buf, COLOR_GREEN, COLOR_CARD_BG, 1);
    }
}
