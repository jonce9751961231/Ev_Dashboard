/**
 * ============================================================================
 * Project: EV Dashboard & Motor Predictive Thermal Management System
 * Target: Texas Instruments C2000 (TMS320F280049C / TMS320F28379D)
 * File: main_f280049c.c
 * Description: TI C2000 Main Control Loop with ADC Sampling, FOC Telemetry,
 *              On-Chip Thermal Observer, and SCI UART / CAN Streaming.
 * ============================================================================
 */

#include <stdio.h>
#include <string.h>
#include "../include/c2000_telemetry.h"
#include "../include/motor_thermal_model.h"

/* Global Instance Variables */
static Motor_Thermal_Parameters_t g_motor_params;
static Motor_Thermal_State_t      g_motor_thermal_state;
static C2000_Serial_Telemetry_Packet_t g_telemetry_packet;

/**
 * @brief Mock / Hardware ADC Sampling Routine for TI C2000
 * In real hardware, this reads ADCResultRegs.ADCRESULT0..N and converts to physical units.
 */
void C2000_Sample_Sensors(C2000_Motor_Raw_Telemetry_t *raw, float sim_load_level) {
    if (!raw) return;

    /* Base operating speed and voltage */
    raw->dc_bus_voltage_V = 398.5f; /* 400V nominal EV battery pack */
    
    /* Simulate dynamic drive behavior based on load level (0.0 to 1.0) */
    raw->motor_torque_nm     = sim_load_level * 320.0f;
    raw->motor_speed_rpm     = 1200.0f + sim_load_level * 6800.0f;
    
    /* Iq current drives torque, Id current used for field weakening at high RPM */
    raw->i_q_current_A       = raw->motor_torque_nm * 0.85f;
    raw->i_d_current_A       = (raw->motor_speed_rpm > 5000.0f) ? -35.0f : -5.0f;
    
    /* Phase currents (approximate 3-phase RMS) */
    float i_mag = sqrtf(raw->i_d_current_A * raw->i_d_current_A + raw->i_q_current_A * raw->i_q_current_A);
    raw->phase_u_current_A   = i_mag * 0.707f;
    raw->phase_v_current_A   = i_mag * 0.707f;
    raw->phase_w_current_A   = i_mag * 0.707f;
    raw->inverter_current_A  = (raw->motor_torque_nm * (raw->motor_speed_rpm * 0.1047f)) / (raw->dc_bus_voltage_V * 0.92f);
    
    /* Environment & Coolant Conditions */
    raw->ambient_temp_C        = 32.0f;
    raw->coolant_inlet_temp_C  = 38.0f + sim_load_level * 12.0f;
    raw->coolant_flow_rate_lpm = 6.5f;
    raw->inverter_igbt_temp_C  = raw->coolant_inlet_temp_C + (raw->inverter_current_A * 0.18f);
    
    /* Stator NTC reading (with slight thermal lag/measurement noise) */
    raw->stator_winding_temp_C = g_motor_thermal_state.T_stator_winding_C;
    raw->motor_casing_temp_C   = g_motor_thermal_state.T_housing_frame_C;
}

/**
 * @brief Initialize C2000 System Peripherals (SCI, ADC, ePWM, CAN)
 */
void C2000_System_Init(void) {
    /* Initialize thermal observer with 30°C starting ambient */
    Motor_Thermal_Init(&g_motor_params, &g_motor_thermal_state, 30.0f);

    /* Initialize packet header */
    memset(&g_telemetry_packet, 0, sizeof(g_telemetry_packet));
    g_telemetry_packet.sync_byte_1  = TELEMETRY_START_BYTE_1;
    g_telemetry_packet.sync_byte_2  = TELEMETRY_START_BYTE_2;
    g_telemetry_packet.version      = TELEMETRY_PROTOCOL_VER;
    g_telemetry_packet.packet_type  = 0x01;
}

/**
 * @brief Periodic 100ms Task (10 Hz) called by C2000 Timer Interrupt
 */
void C2000_Periodic_10Hz_Task(uint32_t tick_count_ms, float current_load) {
    g_telemetry_packet.timestamp_ms = tick_count_ms;

    /* 1. Acquire raw sensor readings */
    C2000_Sample_Sensors(&g_telemetry_packet.sensor_data, current_load);

    /* 2. Execute on-chip thermal predictive observer step */
    Motor_Thermal_Update_Step(&g_motor_params,
                              &g_motor_thermal_state,
                              &g_telemetry_packet.sensor_data,
                              &g_telemetry_packet.thermal_data,
                              0.10f); /* dt = 0.10 s */

    /* 3. Compute CRC-16 Checksum over the entire packet */
    uint32_t payload_len = sizeof(C2000_Serial_Telemetry_Packet_t) - sizeof(uint16_t);
    g_telemetry_packet.checksum_crc16 = C2000_Calculate_CRC16((const uint8_t *)&g_telemetry_packet, payload_len);

    /* 4. In Hardware, transmit via SCI_writeCharArray(SCIA_BASE, ...); */
}

int main(void) {
    C2000_System_Init();

    /* Demonstration: Run 50 ticks of simulated continuous heavy climb (load = 0.85) */
    printf("=== TI C2000 Motor Predictive Thermal Telemetry Stream ===\n");
    for (int tick = 0; tick < 50; tick++) {
        uint32_t time_ms = tick * 100;
        C2000_Periodic_10Hz_Task(time_ms, 0.85f);

        if (tick % 10 == 0) {
            printf("[Tick %4u ms] Stator: %5.1f°C | Rotor(Est): %5.1f°C | Pred(+5m): %5.1f°C | Derate Torque: %5.1f Nm\n",
                   time_ms,
                   g_telemetry_packet.sensor_data.stator_winding_temp_C,
                   g_telemetry_packet.thermal_data.est_rotor_magnet_temp_C,
                   g_telemetry_packet.thermal_data.predicted_stator_temp_5m,
                   g_telemetry_packet.thermal_data.max_allowable_torque_nm);
        }
    }
    return 0;
}
