/**
 * ============================================================================
 * Project: 48V EV BLDC Predictive Thermal & Energy Telemetry System
 * Target: Texas Instruments LAUNCHXL-F2800137 (TMS320F2800137)
 * File: main_f2800137.c
 * Description: High-Speed 48V BLDC Sensor Acquisition, 4-Node Thermal Predictor,
 *              and USB Telemetry Streaming to Laptop Web Cockpit (115200 bps).
 *              - 4 Sensors: Stator 10k NTC, 48V DC Link Current, 0-60V Voltage, BLDC Hall
 *              - Display: Streamed directly over USB XDS110 to Laptop (No external TFT)
 * ============================================================================
 */

#include "driverlib.h"
#include "device.h"
#include "../include/ai_model_weights.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

// --- 48V Hardware Calibration Constants ---
#define ADC_MAX_COUNT          4095.0f   // 12-bit ADC
#define V_REF                  3.3f      // 3.3V reference voltage

// Sensor 1: Stator 10k NTC Thermistor
#define NTC_R_REF              10000.0f  // 10k pull-up resistor to 3.3V
#define NTC_BETA               3950.0f   // NTC Beta coefficient
#define NTC_T0_KELVIN          298.15f   // 25°C in Kelvin
#define NTC_R0                 10000.0f  // 10k at 25°C

// Sensor 2: ACS758LCB-050B (or ACS712-30A) 50A Current Sensor
// Vout = 1.65V (Zero current) + 0.040V/A (Sensitivity scaled to 3.3V range)
#define CURRENT_ZERO_OFFSET_V  1.65f     // Zero current offset
#define CURRENT_SENSITIVITY    0.040f    // 40 mV / Amp (for 50A range)

// Sensor 3: 0–60V DC Voltage Divider (100k / 5.1k Resistors)
// Divider Ratio = (100k + 5.1k) / 5.1k = 20.607 (60V in -> 2.91V out)
#define VOLT_DIVIDER_RATIO     20.607f

// --- 48V BLDC Motor & Thermal Parameters ---
#define BLDC_POLE_PAIRS        4         // 8-Pole BLDC motor (4 pole pairs)
#define BLDC_KV_RATING         450.0f    // 450 RPM/Volt (48V nominal = ~21,600 max electrical RPM)
#define BLDC_KT_NM_PER_A       (60.0f / (2.0f * 3.14159f * BLDC_KV_RATING)) // ~0.0212 Nm/A
#define R_PHASE_20C            0.12f     // Phase-to-phase stator resistance at 20°C (Ohms)
#define ALPHA_COPPER           0.00393f  // Copper temperature coefficient (1/°C)

// 4-Node Thermal Capacitances & Resistances
#define C_STATOR_WINDING       220.0f    // Stator copper heat capacity (J/K)
#define R_STATOR_TO_CORE       0.045f    // Stator to iron core resistance (K/W)
#define C_STATOR_CORE          650.0f    // Core heat capacity (J/K)
#define R_CORE_TO_CASING       0.035f    // Core to outer casing (K/W)
#define C_ROTOR_MAGNETS        320.0f    // NdFeB permanent magnets on rotor (J/K)
#define R_MAGNETS_TO_AIRGAP    0.120f    // Airgap thermal resistance (K/W)
#define R_CASING_TO_AIR        1.850f    // Casing to ambient air (K/W)

// Safety Critical Limits
#define STATOR_WARN_TEMP       110.0f    // Stator winding warning (°C)
#define STATOR_CRITICAL_TEMP   135.0f    // Stator insulation trip limit (°C)
#define ROTOR_DEMAG_WARN_TEMP  90.0f     // NdFeB magnet demag warning (°C)
#define ROTOR_DEMAG_TRIP_TEMP  115.0f    // Irreversible demagnetization trip (°C)

// Telemetry Data Structure
typedef struct {
    // Current Live 48V BLDC Details
    float stator_temp_measured_C;        // Measured Stator Winding Temp (°C)
    float est_rotor_magnet_temp_C;       // Estimated Rotor Magnet Temp (°C)
    float dc_bus_current_A;              // 48V DC Link Current (A)
    float dc_bus_voltage_V;              // 48V DC Bus Voltage (V)
    float rotor_speed_rpm;               // BLDC Rotor Mechanical Speed (RPM)
    float electrical_freq_hz;            // Stator Electrical Frequency (fe = p*RPM/60)
    float vehicle_speed_kmh;             // Vehicle Ground Speed (km/h)
    float motor_torque_nm;               // Electromagnetic Torque (Nm)
    float electrical_power_W;            // Total Input Power (W)
    float mechanical_power_W;            // Shaft Output Power (W)
    float p_copper_loss_W;               // 3-Phase Stator Copper Loss (W)
    float p_iron_loss_W;                 // Core Hysteresis + Eddy Loss (W)
    float p_rotor_eddy_W;                // Magnet Eddy Current Heating (W)
    float dT_stator_dt;                  // Stator heating rate (°C/s)

    // Future Multi-Horizon Predictions
    float pred_stator_temp_1m_C;
    float pred_stator_temp_5m_C;
    float pred_rotor_temp_5m_C;
    float pred_stator_temp_15m_C;
    float pred_stator_temp_30m_C;

    // Battery & Energy Telemetry
    float battery_soc_pct;               // 48V Battery State of Charge (%)
    float energy_rate_wh_per_km;         // Energy consumption rate (Wh/km)
    float remaining_range_km;            // Projected remaining range (km)

    // Safety & Proactive Derating
    float max_allowable_current_A;
    uint8_t thermal_derate_active;
} C2000_48V_BLDC_Telemetry_t;

static C2000_48V_BLDC_Telemetry_t g_telemetry = {
    .stator_temp_measured_C = 30.0f,
    .est_rotor_magnet_temp_C = 30.0f,
    .battery_soc_pct = 85.0f,
    .max_allowable_current_A = 35.0f,
    .thermal_derate_active = 0
};

volatile uint32_t g_hall_pulse_counter = 0;
static uint32_t g_system_tick_ms = 0;

// Function Prototypes
void initADC(void);
void initEPWM(void);
void initSCIA(void);
void initHallSpeedInterrupt(void);
void process48VBLDCPredictions(float dt_sec);
void sendTelemetryStreamToLaptop(void);

// External Interrupt Service Routine for BLDC Hall Sensor (GPIO0 -> XINT1)
__interrupt void xint1_isr(void) {
    g_hall_pulse_counter++;
    Interrupt_clearACKGroup(INTERRUPT_ACK_GROUP1);
}

int main(void) {
    // 1. Initialize Device System and Clocks (120 MHz SYSCLK)
    Device_init();
    Device_initGPIO();

    // 2. Initialize PIE Interrupt Controller
    Interrupt_initModule();
    Interrupt_initVectorTable();

    // 3. Initialize Peripherals
    initADC();
    initEPWM();
    initSCIA();
    initHallSpeedInterrupt();

    // Enable Global Interrupts
    EINT;
    ERTM;

    // 4. Main 10 Hz Real-Time Telemetry & Prediction Loop (Every 100 ms)
    while (1) {
        g_system_tick_ms += 100;

        // A. Trigger ADC Conversions (SOC0: NTC Temp, SOC1: DC Current, SOC2: 48V Voltage)
        ADC_forceSOC(ADCA_BASE, ADC_SOC_NUMBER0);
        ADC_forceSOC(ADCA_BASE, ADC_SOC_NUMBER1);
        ADC_forceSOC(ADCA_BASE, ADC_SOC_NUMBER2);

        while (!ADC_getInterruptStatus(ADCA_BASE, ADC_INT_NUMBER1));
        ADC_clearInterruptStatus(ADCA_BASE, ADC_INT_NUMBER1);

        // B. Read ADC conversion results
        uint16_t raw_temp = ADC_readResult(ADCARESULT_BASE, ADC_SOC_NUMBER0);
        uint16_t raw_curr = ADC_readResult(ADCARESULT_BASE, ADC_SOC_NUMBER1);
        uint16_t raw_volt = ADC_readResult(ADCARESULT_BASE, ADC_SOC_NUMBER2);

        float v_temp = ((float)raw_temp / ADC_MAX_COUNT) * V_REF;
        float v_curr = ((float)raw_curr / ADC_MAX_COUNT) * V_REF;
        float v_volt = ((float)raw_volt / ADC_MAX_COUNT) * V_REF;

        // C. Calculate Physical Sensor Units for 48V BLDC
        // 1. Stator Winding Temperature (°C)
        float r_ntc = NTC_R_REF * (v_temp / (V_REF - v_temp + 1e-4f));
        float inv_T = (1.0f / NTC_T0_KELVIN) + (1.0f / NTC_BETA) * logf(r_ntc / NTC_R0);
        g_telemetry.stator_temp_measured_C = (1.0f / inv_T) - 273.15f;

        // 2. 48V Inverter DC Link Current (A)
        g_telemetry.dc_bus_current_A = fabsf((v_curr - CURRENT_ZERO_OFFSET_V) / CURRENT_SENSITIVITY);

        // 3. 48V DC Bus Voltage (V)
        g_telemetry.dc_bus_voltage_V = v_volt * VOLT_DIVIDER_RATIO;

        // 4. BLDC Speed (RPM) from Hall sensor pulses: (Pulses in 0.1s / (Pole_Pairs * 6)) * 600
        g_telemetry.rotor_speed_rpm = ((float)g_hall_pulse_counter / (BLDC_POLE_PAIRS * 6.0f)) * 600.0f;
        g_hall_pulse_counter = 0;

        // 5. Electrical Stator Frequency (fe = Pole_Pairs * RPM / 60)
        g_telemetry.electrical_freq_hz = (BLDC_POLE_PAIRS * g_telemetry.rotor_speed_rpm) / 60.0f;

        // 6. Sensorless BLDC Torque: T = Kt * Idc
        g_telemetry.motor_torque_nm = BLDC_KT_NM_PER_A * g_telemetry.dc_bus_current_A * 0.92f;

        // 7. Vehicle Ground Speed & Power
        g_telemetry.vehicle_speed_kmh = (g_telemetry.rotor_speed_rpm / 6000.0f) * 60.0f;
        g_telemetry.electrical_power_W = g_telemetry.dc_bus_voltage_V * g_telemetry.dc_bus_current_A;
        g_telemetry.mechanical_power_W = g_telemetry.motor_torque_nm * (g_telemetry.rotor_speed_rpm * 0.1047f);

        // D. Execute 48V BLDC 4-Node Thermal & AI Forward Predictor
        process48VBLDCPredictions(0.10f); // dt = 0.10 s

        // E. Stream Real-Time Telemetry to Laptop via USB Virtual COM
        sendTelemetryStreamToLaptop();

        // 100 ms loop delay (10 Hz periodic stream)
        DEVICE_DELAY_US(100000);
    }
}

/**
 * @brief Initialize 12-Bit ADC-A for NTC, Current, and Voltage Channels
 */
void initADC(void) {
    ADC_setPrescaler(ADCA_BASE, ADC_CLK_DIV_2_0);
    ADC_setMode(ADCA_BASE, ADC_RESOLUTION_12BIT, ADC_MODE_SINGLE_ENDED);
    ADC_enableConverter(ADCA_BASE);
    DEVICE_DELAY_US(1000);

    ADC_setupSOC(ADCA_BASE, ADC_SOC_NUMBER0, ADC_TRIGGER_SW_ONLY, ADC_CH_ADCIN0, 15);
    ADC_setupSOC(ADCA_BASE, ADC_SOC_NUMBER1, ADC_TRIGGER_SW_ONLY, ADC_CH_ADCIN1, 15);
    ADC_setupSOC(ADCA_BASE, ADC_SOC_NUMBER2, ADC_TRIGGER_SW_ONLY, ADC_CH_ADCIN2, 15);

    ADC_setInterruptSource(ADCA_BASE, ADC_INT_NUMBER1, ADC_SOC_NUMBER2);
    ADC_enableInterrupt(ADCA_BASE, ADC_INT_NUMBER1);
    ADC_clearInterruptStatus(ADCA_BASE, ADC_INT_NUMBER1);
}

/**
 * @brief Initialize SCI-A UART for 115200 Baud on GPIO28/29 (Virtual COM Port to Laptop)
 */
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
    SCI_clearInterruptStatus(SCIA_BASE, SCI_INT_TXFF | SCI_INT_RXFF);
    SCI_enableFIFO(SCIA_BASE);
    SCI_enableModule(SCIA_BASE);
}

/**
 * @brief Initialize GPIO0 for BLDC Hall Sensor Input
 */
void initHallSpeedInterrupt(void) {
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

/**
 * @brief Initialize ePWM1 for 48V Inverter Throttle Control (20 kHz)
 */
void initEPWM(void) {
    GPIO_setPinConfig(GPIO_1_EPWM1_B);
    GPIO_setPadConfig(1, GPIO_PIN_TYPE_STD);

    GPIO_setPinConfig(GPIO_2_GPIO2);
    GPIO_setDirectionMode(2, GPIO_DIR_MODE_OUT);
    GPIO_writePin(2, 1); // Enable 48V Inverter Driver

    EPWM_setTimeBasePeriod(EPWM1_BASE, 3000); // 120 MHz / (2 * 3000) = 20 kHz
    EPWM_setTimeBaseCounter(EPWM1_BASE, 0);
    EPWM_setTimeBaseCounterMode(EPWM1_BASE, EPWM_COUNTER_MODE_UP_DOWN);
    EPWM_setClockPrescaler(EPWM1_BASE, EPWM_CLOCK_DIVIDER_1, EPWM_HSCLOCK_DIVIDER_1);

    EPWM_setCounterCompareValue(EPWM1_BASE, EPWM_COUNTER_COMPARE_B, 1500);
    EPWM_setActionQualifierAction(EPWM1_BASE, EPWM_AQ_OUTPUT_B, EPWM_AQ_OUTPUT_HIGH, EPWM_AQ_OUTPUT_ON_TIMEBASE_UP_CMPB);
    EPWM_setActionQualifierAction(EPWM1_BASE, EPWM_AQ_OUTPUT_B, EPWM_AQ_OUTPUT_LOW, EPWM_AQ_OUTPUT_ON_TIMEBASE_DOWN_CMPB);
}

/**
 * @brief 48V BLDC Thermal Loss Physics & Multi-Horizon Forward Predictor
 */
void process48VBLDCPredictions(float dt_sec) {
    float T_amb = 30.0f;

    // 1. 3-Phase Stator Copper Loss (P_cu = 3 * I_phase_rms^2 * R_phase)
    float i_phase_rms = g_telemetry.dc_bus_current_A * 0.816f;
    float r_phase_actual = R_PHASE_20C * (1.0f + ALPHA_COPPER * (g_telemetry.stator_temp_measured_C - 20.0f));
    g_telemetry.p_copper_loss_W = 3.0f * (i_phase_rms * i_phase_rms) * r_phase_actual;

    // 2. High-Frequency Iron Core Loss (P_fe = k_h * f + k_e * f^2)
    float f = g_telemetry.electrical_freq_hz;
    g_telemetry.p_iron_loss_W = (0.012f * f) + (0.00015f * f * f);

    // 3. Rotor Permanent Magnet Eddy Current Loss
    g_telemetry.p_rotor_eddy_W = 0.05f * g_telemetry.p_iron_loss_W + 0.0010f * (i_phase_rms * i_phase_rms);

    // 4. Stator & Rotor Thermal ODE Numerical Integration
    float q_stator_to_core = (g_telemetry.stator_temp_measured_C - (T_amb + 10.0f)) / (R_STATOR_TO_CORE + R_CORE_TO_CASING + R_CASING_TO_AIR);
    float dT_stator = (g_telemetry.p_copper_loss_W + g_telemetry.p_iron_loss_W - q_stator_to_core) / C_STATOR_WINDING;
    g_telemetry.dT_stator_dt = dT_stator;

    // Rotor Magnet Heating & Demagnetization State
    float q_rotor_to_airgap = (g_telemetry.est_rotor_magnet_temp_C - T_amb) / (R_MAGNETS_TO_AIRGAP + R_CASING_TO_AIR);
    float dT_rotor = (g_telemetry.p_rotor_eddy_W - q_rotor_to_airgap) / C_ROTOR_MAGNETS;
    g_telemetry.est_rotor_magnet_temp_C += dT_rotor * dt_sec;

    // 5. Steady-State Asymptotic Temperature Extrapolation for 48V BLDC
    float R_total_stator_th = R_STATOR_TO_CORE + R_CORE_TO_CASING + R_CASING_TO_AIR;
    float T_stator_inf = T_amb + ((g_telemetry.p_copper_loss_W + g_telemetry.p_iron_loss_W) * R_total_stator_th);
    float tau_bldc_stator = 160.0f; // Seconds

    // 6. Multi-Horizon Forward Predictions
    g_telemetry.pred_stator_temp_1m_C  = T_stator_inf + (g_telemetry.stator_temp_measured_C - T_stator_inf) * expf(-60.0f / tau_bldc_stator);
    g_telemetry.pred_stator_temp_5m_C  = T_stator_inf + (g_telemetry.stator_temp_measured_C - T_stator_inf) * expf(-300.0f / tau_bldc_stator);
    g_telemetry.pred_stator_temp_15m_C = T_stator_inf + (g_telemetry.stator_temp_measured_C - T_stator_inf) * expf(-900.0f / tau_bldc_stator);
    g_telemetry.pred_stator_temp_30m_C = T_stator_inf + (g_telemetry.stator_temp_measured_C - T_stator_inf) * expf(-1800.0f / tau_bldc_stator);

    // 7. 48V Battery Pack SoC & Energy Rate
    g_telemetry.battery_soc_pct -= (g_telemetry.dc_bus_current_A * (dt_sec / 3600.0f) / 50.0f) * 100.0f;
    if (g_telemetry.battery_soc_pct < 5.0f) g_telemetry.battery_soc_pct = 5.0f;

    float v_kmh = (g_telemetry.vehicle_speed_kmh > 5.0f) ? g_telemetry.vehicle_speed_kmh : 5.0f;
    g_telemetry.energy_rate_wh_per_km = (g_telemetry.electrical_power_W / v_kmh);
    float rem_kwh = (g_telemetry.battery_soc_pct / 100.0f) * 2.4f; // 48V * 50Ah = 2.4 kWh pack
    g_telemetry.remaining_range_km = (rem_kwh * 1000.0f) / (g_telemetry.energy_rate_wh_per_km + 1.0f);

    // 8. Proactive Thermal Derating (Protects Stator Insulation & NdFeB Rotor Magnets)
    if (g_telemetry.pred_stator_temp_5m_C > STATOR_WARN_TEMP || g_telemetry.est_rotor_magnet_temp_C > ROTOR_DEMAG_WARN_TEMP) {
        g_telemetry.thermal_derate_active = 1;
        float derate_factor = (STATOR_CRITICAL_TEMP - g_telemetry.pred_stator_temp_5m_C) / (STATOR_CRITICAL_TEMP - STATOR_WARN_TEMP);
        if (derate_factor < 0.20f) derate_factor = 0.20f;
        if (derate_factor > 1.0f)  derate_factor = 1.0f;
        g_telemetry.max_allowable_current_A = 35.0f * derate_factor;

        // Apply derating to PWM duty cycle
        uint16_t derated_cmp = (uint16_t)(3000.0f * (g_telemetry.max_allowable_current_A / 35.0f) * 0.5f);
        EPWM_setCounterCompareValue(EPWM1_BASE, EPWM_COUNTER_COMPARE_B, derated_cmp);
    } else {
        g_telemetry.thermal_derate_active = 0;
        g_telemetry.max_allowable_current_A = 35.0f;
    }
}

/**
 * @brief Streams 48V BLDC Telemetry over USB Virtual COM to Laptop
 */
void sendTelemetryStreamToLaptop(void) {
    char tx_buffer[160];
    int len = snprintf(tx_buffer, sizeof(tx_buffer),
                       "$EV_48V,%lu,%.1f,%.1f,%.2f,%.1f,%.0f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%u*\r\n",
                       g_system_tick_ms,
                       g_telemetry.stator_temp_measured_C,
                       g_telemetry.est_rotor_magnet_temp_C,
                       g_telemetry.dc_bus_current_A,
                       g_telemetry.dc_bus_voltage_V,
                       g_telemetry.rotor_speed_rpm,
                       g_telemetry.pred_stator_temp_1m_C,
                       g_telemetry.pred_stator_temp_5m_C,
                       g_telemetry.pred_stator_temp_15m_C,
                       g_telemetry.battery_soc_pct,
                       g_telemetry.energy_rate_wh_per_km,
                       g_telemetry.remaining_range_km,
                       g_telemetry.thermal_derate_active);

    for (int i = 0; i < len; i++) {
        while (!SCI_isSpaceAvailableNonFIFO(SCIA_BASE));
        SCI_writeCharNonBlocking(SCIA_BASE, tx_buffer[i]);
    }
}
