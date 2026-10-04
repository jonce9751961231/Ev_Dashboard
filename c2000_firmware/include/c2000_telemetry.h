/**
 * ============================================================================
 * Project: EV Dashboard & Motor Predictive Thermal Management System
 * Target: Texas Instruments C2000 Microcontrollers (TMS320F280049C / TMS320F28379D)
 * File: c2000_telemetry.h
 * Description: Telemetry frame definitions, ADC mappings, and serial protocol
 *              for high-speed motor and battery sensor streaming.
 * ============================================================================
 */

#ifndef C2000_TELEMETRY_H
#define C2000_TELEMETRY_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Packet Header & Protocol Identifiers */
#define TELEMETRY_START_BYTE_1    0xAA
#define TELEMETRY_START_BYTE_2    0x55
#define TELEMETRY_PROTOCOL_VER    0x01

/* CAN Message IDs (Standard 11-bit / Extended 29-bit CAN 2.0B / CAN-FD) */
#define CAN_ID_MOTOR_DYNAMICS     0x18F00101
#define CAN_ID_MOTOR_THERMAL      0x18F00102
#define CAN_ID_PREDICTIVE_DERATE  0x18F00103
#define CAN_ID_BATTERY_STATUS     0x18F00201

#pragma pack(push, 1)

/**
 * @brief Raw ADC and Filtered Sensor Readings from TI C2000 ADC Modules
 */
typedef struct {
    /* Motor Phase Currents (Measured via Shunts or Hall Sensors / ADC-A, ADC-B) */
    float phase_u_current_A;      /* Phase U RMS Current [Amperes] */
    float phase_v_current_A;      /* Phase V RMS Current [Amperes] */
    float phase_w_current_A;      /* Phase W RMS Current [Amperes] */
    
    /* FOC Transformed Coordinates */
    float i_d_current_A;          /* Direct-axis current (Flux weakening) [A] */
    float i_q_current_A;          /* Quadrature-axis current (Torque producing) [A] */
    
    /* Motor Kinematics & Electrical Dynamics */
    float motor_speed_rpm;        /* Rotor Mechanical Speed [RPM] */
    float motor_torque_nm;        /* Electrical Torque [Nm] */
    float dc_bus_voltage_V;       /* Inverter DC Link Voltage [Volts] */
    float inverter_current_A;     /* DC Link Current [Amperes] */
    
    /* Measured Temperatures (NTC Thermistors / PT1000 RTD via ADC-C) */
    float stator_winding_temp_C;  /* Measured Stator Winding Temp [°C] */
    float motor_casing_temp_C;    /* Measured Motor Frame / Housing Temp [°C] */
    float coolant_inlet_temp_C;   /* Liquid Coolant Inlet Temp [°C] */
    float ambient_temp_C;         /* Ambient Under-hood Temp [°C] */
    
    /* Inverter & Gate Driver Status */
    float inverter_igbt_temp_C;   /* Power Stage / MOSFET/IGBT Temp [°C] */
    float coolant_flow_rate_lpm;  /* Coolant Flow Rate [Liters/min] */
} C2000_Motor_Raw_Telemetry_t;

/**
 * @brief Real-Time On-Chip Thermal Observer & Future Predictions computed on C2000
 */
typedef struct {
    /* Instantaneous Estimated Unmeasured Hotspots */
    float est_rotor_magnet_temp_C;  /* Estimated NdFeB Magnet Temp [°C] */
    float est_stator_core_temp_C;    /* Stator Iron Core Teeth Temp [°C] */
    
    /* Power Loss Calculations */
    float copper_loss_watts;        /* I^2 * R Stator Joule Loss [W] */
    float iron_loss_watts;          /* Hysteresis + Eddy Current Core Loss [W] */
    float mechanical_loss_watts;    /* Friction + Windage Loss [W] */
    float total_loss_watts;         /* Total Motor Heat Dissipation [W] */
    
    /* Embedded Short-Horizon Predictions (+1 min, +5 min) */
    float predicted_stator_temp_1m; /* Predicted Stator Temp in 1 min [°C] */
    float predicted_stator_temp_5m; /* Predicted Stator Temp in 5 min [°C] */
    float predicted_rotor_temp_5m;  /* Predicted Magnet Temp in 5 min [°C] */
    
    /* Proactive Derating & Thermal Safety Flags */
    float max_allowable_torque_nm;  /* Derated Max Torque Limit [Nm] */
    uint8_t thermal_warning_flags;  /* Bit 0: Stator Warning, Bit 1: Rotor Warning, Bit 2: Inverter Overheat */
    uint8_t cooling_pump_command;   /* Recommended Pump PWM [0-100%] */
} C2000_Motor_Thermal_Estimate_t;

/**
 * @brief Complete Telemetry Packet Streamed over SCI / UART to Dashboard
 */
typedef struct {
    uint8_t sync_byte_1;            /* 0xAA */
    uint8_t sync_byte_2;            /* 0x55 */
    uint8_t version;                /* Protocol Version (1) */
    uint8_t packet_type;            /* 0x01 = Motor Telemetry, 0x02 = Prediction Horizon */
    uint32_t timestamp_ms;          /* MCU Timer tick in milliseconds */
    
    C2000_Motor_Raw_Telemetry_t sensor_data;
    C2000_Motor_Thermal_Estimate_t thermal_data;
    
    uint16_t checksum_crc16;        /* CRC-16-CCITT for packet integrity */
} C2000_Serial_Telemetry_Packet_t;

#pragma pack(pop)

/* Helper: Calculate CRC16 CCITT */
static inline uint16_t C2000_Calculate_CRC16(const uint8_t *data, uint32_t length) {
    uint16_t crc = 0xFFFF;
    for (uint32_t i = 0; i < length; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (uint8_t j = 0; j < 8; j++) {
            if (crc & 0x8000) {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc <<= 1;
            }
        }
    }
    return crc;
}

#ifdef __cplusplus
}
#endif

#endif /* C2000_TELEMETRY_H */
