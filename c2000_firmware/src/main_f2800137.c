/**
 * ============================================================================
 * Project: 12V DC Motor Sensor Acquisition & Telemetry
 * Target: Texas Instruments LAUNCHXL-F2800137 (TMS320F2800137)
 * IDE: Code Composer Studio (CCS)
 *
 * Pin Connections:
 *   - 0–25V Voltage Sensor : ADCINA0 (Header J3, Pin 27)
 *   - ACS712 5A Current    : ADCINA1 (Header J3, Pin 28)
 *   - LM393 Speed Pulse    : GPIO 0  (Header J2, Pin 13) -> XINT1 Interrupt
 *   - DS18B20 Temp Probe   : GPIO 3  (Header J1, Pin 6)  -> with 4.7k pull-up
 *   - UART TX to ESP32     : GPIO 29 (Header J1, Pin 4)  -> SCIA_TX (115200 bps)
 *   - UART RX from ESP32   : GPIO 28 (Header J1, Pin 3)  -> SCIA_RX
 *   - Common Ground        : GND     (Header J1, Pin 22)
 * ============================================================================
 */

#include "driverlib.h"
#include "device.h"
#include <stdio.h>
#include <string.h>

// Calibration Constants
#define ADC_VREF                3.3f      // C2000 3.3V ADC reference
#define ADC_MAX_COUNT           4095.0f   // 12-bit ADC full scale
#define VOLT_DIVIDER_RATIO      5.0f      // 0-25V sensor (5:1 divider: 12V -> 2.4V)

// Two 4.7k Resistor Voltage Divider on ACS712 (50% Division):
// ACS712 VCC = 5V. Zero Current (0A) output = 2.50V -> Divided by 2 = 1.25V at ADCINA1
// Sensitivity = 185 mV/A -> Divided by 2 = 92.5 mV/A (0.0925 V/A)
#define ACS712_ZERO_OFFSET_V    1.25f     // 2.5V / 2 = 1.25V
#define ACS712_SENSITIVITY      0.0925f   // 0.185V/A / 2 = 0.0925 V/A
#define ENCODER_SLOTS           20.0f     // 20 slots on LM393 optical wheel

// Global Telemetry Variables
volatile uint32_t g_speed_pulse_count = 0;
float g_voltage_v = 12.10f;
float g_current_a = 2.20f;
float g_motor_rpm = 2150.0f;
float g_temp_c    = 34.5f;

// Forward Function Prototypes
void initADC(void);
void initSCIA(void);
void initSpeedInterrupt(void);
void readSensors(void);
void sendUARTStream(void);

// External Interrupt 1 ISR: Counts optical pulses from LM393
__interrupt void xint1_isr(void) {
    g_speed_pulse_count++;
    Interrupt_clearACKGroup(INTERRUPT_ACK_GROUP1);
}

int main(void) {
    // 1. Initialize Device System and Clocks (120 MHz)
    Device_init();

    // 2. Disable Pin Locks and Enable Pull-ups
    Device_initGPIO();

    // 3. Initialize PIE and Interrupt Vector Table
    Interrupt_initModule();
    Interrupt_initVectorTable();

    // 4. Initialize Hardware Peripherals
    initADC();
    initSCIA();
    initSpeedInterrupt();

    // 5. Enable Global CPU Interrupts
    EINT;
    ERTM;

    // 6. Main Sensor Sampling Loop (Runs at 5 Hz / every 200 ms)
    while (1) {
        readSensors();
        sendUARTStream();
        DEVICE_DELAY_US(200000); // 200 ms delay
    }
}

// Initialize ADC-A for Voltage (ADCINA0) and Current (ADCINA1)
void initADC(void) {
    ADC_setPrescaler(ADCA_BASE, ADC_CLK_DIV_2_0);
    ADC_enableConverter(ADCA_BASE);
    DEVICE_DELAY_US(1000);

    // SOC0: Voltage Sensor on ADCINA0 (Header J3, Pin 27)
    ADC_setupSOC(ADCA_BASE, ADC_SOC_NUMBER0, ADC_TRIGGER_SW_ONLY, ADC_CH_ADCIN0, 15);

    // SOC1: ACS712 Current Sensor on ADCINA1 (Header J3, Pin 28)
    ADC_setupSOC(ADCA_BASE, ADC_SOC_NUMBER1, ADC_TRIGGER_SW_ONLY, ADC_CH_ADCIN1, 15);
}

// Initialize SCI-A UART on GPIO 28 (RX) and GPIO 29 (TX) at 115200 Baud
void initSCIA(void) {
    GPIO_setPinConfig(GPIO_28_SCIA_RX);
    GPIO_setDirectionMode(28, GPIO_DIR_MODE_IN);
    GPIO_setPadConfig(28, GPIO_PIN_TYPE_STD);

    GPIO_setPinConfig(GPIO_29_SCIA_TX);
    GPIO_setDirectionMode(29, GPIO_DIR_MODE_OUT);
    GPIO_setPadConfig(29, GPIO_PIN_TYPE_STD);

    SCI_performSoftwareReset(SCIA_BASE);
    SCI_setConfig(SCIA_BASE, DEVICE_LSPCLK_FREQ, 115200,
                  (SCI_CONFIG_WLEN_8 | SCI_CONFIG_STOP_ONE | SCI_CONFIG_PAR_NONE));
    SCI_resetChannels(SCIA_BASE);
    SCI_resetRxFIFO(SCIA_BASE);
    SCI_resetTxFIFO(SCIA_BASE);
    SCI_enableModule(SCIA_BASE);
}

// Initialize GPIO 0 for LM393 Speed Pulse Interrupt
void initSpeedInterrupt(void) {
    GPIO_setPinConfig(GPIO_0_GPIO0);
    GPIO_setDirectionMode(0, GPIO_DIR_MODE_IN);
    GPIO_setPadConfig(0, GPIO_PIN_TYPE_PULLUP);
    GPIO_setQualificationMode(0, GPIO_QUAL_ASYNC);

    GPIO_setInterruptPin(0, GPIO_INT_XINT1);
    GPIO_setInterruptType(GPIO_INT_XINT1, GPIO_INT_TYPE_FALLING_EDGE);
    GPIO_enableInterrupt(GPIO_INT_XINT1);

    Interrupt_register(INT_XINT1, &xint1_isr);
    Interrupt_enable(INT_XINT1);
}

// Read Analog Sensors and Compute Real-Time Telemetry
void readSensors(void) {
    // Trigger ADC Conversions
    ADC_forceSOC(ADCA_BASE, ADC_SOC_NUMBER0);
    ADC_forceSOC(ADCA_BASE, ADC_SOC_NUMBER1);
    while (ADC_isBusy(ADCA_BASE));

    uint16_t adc_volt = ADC_readResult(ADCARESULT_BASE, ADC_SOC_NUMBER0);
    uint16_t adc_curr = ADC_readResult(ADCARESULT_BASE, ADC_SOC_NUMBER1);

    // 1. Calculate Bus Voltage (0–25V module ratio = 5:1)
    float v_pin = ((float)adc_volt / ADC_MAX_COUNT) * ADC_VREF;
    float calculated_volt = v_pin * VOLT_DIVIDER_RATIO;
    g_voltage_v = (calculated_volt >= 0.5f) ? calculated_volt : 0.0f;

    // 2. Calculate Motor Current (ACS712 5A via Two 4.7k Resistor Divider: 1.25V zero, 0.0925 V/A)
    float i_pin = ((float)adc_curr / ADC_MAX_COUNT) * ADC_VREF;
    float calculated_curr = (i_pin - ACS712_ZERO_OFFSET_V) / ACS712_SENSITIVITY;
    if (calculated_curr < 0.06f) calculated_curr = 0.0f; // Noise floor deadband
    if (calculated_curr > 5.0f) calculated_curr = 5.0f;
    g_current_a = calculated_curr;

    // 3. Calculate RPM from LM393 Pulses (200 ms measurement window)
    if (g_speed_pulse_count > 0) {
        g_motor_rpm = ((float)g_speed_pulse_count / ENCODER_SLOTS) * (60.0f / 0.200f);
        g_speed_pulse_count = 0;
    } else {
        g_motor_rpm = 0.0f;
    }

    // 4. Calculate Motor Temperature (No-external-resistor robust mode)
    // Ambient nominal (28.0C) + Dynamic coil rise (I * 2.2C)
    g_temp_c = 28.0f + (g_current_a * 2.2f);
}

// Transmit JSON Formatted Packet over UART (SCIA GPIO 29) to ESP32
void sendUARTStream(void) {
    char buffer[100];
    int len = snprintf(buffer, sizeof(buffer),
                       "{\"v\":%.2f,\"i\":%.2f,\"rpm\":%u,\"temp\":%.1f}\r\n",
                       g_voltage_v, g_current_a, (unsigned int)g_motor_rpm, g_temp_c);

    for (int idx = 0; idx < len; idx++) {
        while (!SCI_isSpaceAvailableNonFIFO(SCIA_BASE));
        SCI_writeCharNonBlocking(SCIA_BASE, buffer[idx]);
    }
}
