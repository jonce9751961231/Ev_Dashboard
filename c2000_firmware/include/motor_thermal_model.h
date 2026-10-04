/**
 * ============================================================================
 * Project: EV Dashboard & Motor Predictive Thermal Management System
 * Target: Texas Instruments C2000 Microcontrollers
 * File: motor_thermal_model.h
 * Description: 4-Node Lumped-Parameter Thermal Network (LPTN) & Embedded
 *              Predictive Horizon Estimator for PMSM Traction Motors.
 * ============================================================================
 */

#ifndef MOTOR_THERMAL_MODEL_H
#define MOTOR_THERMAL_MODEL_H

#include "c2000_telemetry.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Motor Physical & Material Parameters (e.g. 150 kW Automotive PMSM) */
typedef struct {
    /* Stator Electrical & Thermal Parameters */
    float R_stator_ref_ohm;     /* Stator resistance at 20°C [Ohms] (e.g. 0.015 Ohm) */
    float alpha_copper_coeff;   /* Temperature coefficient of Copper (0.00393 / °C) */
    float C_stator_windings_J_K;/* Heat capacity of copper windings [J/K] (~2500 J/K) */
    float R_stator_to_core_K_W; /* Thermal resistance: Windings -> Iron Core [K/W] (~0.04 K/W) */

    /* Stator Iron Core Parameters */
    float C_stator_core_J_K;    /* Heat capacity of laminated silicon steel core [J/K] (~7000 J/K) */
    float R_core_to_frame_K_W;  /* Thermal resistance: Core -> Housing Frame [K/W] (~0.025 K/W) */
    float k_iron_hysteresis;    /* Core hysteresis loss coefficient */
    float k_iron_eddy;          /* Core eddy current loss coefficient */

    /* Rotor & Permanent Magnet Parameters */
    float C_rotor_magnet_J_K;   /* Heat capacity of rotor + NdFeB magnets [J/K] (~3500 J/K) */
    float R_magnet_to_airgap_K_W;/* Thermal resistance: Magnets -> Airgap/Shaft [K/W] (~0.12 K/W) */
    float R_airgap_to_frame_K_W; /* Thermal resistance: Airgap -> Housing [K/W] (~0.08 K/W) */

    /* Housing & Liquid Cooling Jacket Parameters */
    float C_frame_housing_J_K;  /* Heat capacity of aluminum motor housing [J/K] (~5500 J/K) */
    float R_frame_to_coolant_K_W;/* Base thermal resistance to coolant jacket [K/W] (~0.015 K/W) */

    /* Critical Safety Thresholds */
    float stator_temp_warning_C; /* Warning temperature (e.g., 140.0 °C) */
    float stator_temp_trip_C;    /* Class H insulation hard limit (e.g., 165.0 °C) */
    float rotor_temp_warning_C;  /* NdFeB demagnetization warning (e.g., 115.0 °C) */
    float rotor_temp_trip_C;     /* Irreversible demagnetization risk (e.g., 135.0 °C) */
} Motor_Thermal_Parameters_t;

/* Motor Thermal State Variables */
typedef struct {
    float T_stator_winding_C;   /* Stator Winding Temperature [°C] */
    float T_stator_core_C;      /* Stator Laminated Core Temperature [°C] */
    float T_rotor_magnet_C;     /* Permanent Magnet Temperature [°C] */
    float T_housing_frame_C;    /* Motor Housing / Frame Temperature [°C] */

    /* Derivative states for prediction */
    float dT_stator_dt;         /* Rate of temp change [°C/s] */
    float dT_rotor_dt;          /* Rate of temp change [°C/s] */
} Motor_Thermal_State_t;

/**
 * @brief Initialize the thermal observer parameters with motor specifications
 */
void Motor_Thermal_Init(Motor_Thermal_Parameters_t *params, Motor_Thermal_State_t *state, float ambient_temp_C);

/**
 * @brief Execute one step of the physical LPTN observer (called periodically, e.g. at 10 Hz)
 * @param params Motor physical parameters
 * @param state Current thermal state vector (updated in place)
 * @param telemetry Instantaneous electrical telemetry
 * @param dt_seconds Time delta since last update (e.g. 0.1s for 10 Hz)
 */
void Motor_Thermal_Update_Step(const Motor_Thermal_Parameters_t *params,
                               Motor_Thermal_State_t *state,
                               const C2000_Motor_Raw_Telemetry_t *telemetry,
                               C2000_Motor_Thermal_Estimate_t *estimate,
                               float dt_seconds);

/**
 * @brief Calculate future temperatures over multiple time horizons (+1m, +5m, +15m)
 *        and calculate proactive torque derating.
 */
void Motor_Thermal_Predict_Horizon(const Motor_Thermal_Parameters_t *params,
                                   const Motor_Thermal_State_t *state,
                                   const C2000_Motor_Raw_Telemetry_t *telemetry,
                                   C2000_Motor_Thermal_Estimate_t *estimate);

#ifdef __cplusplus
}
#endif

#endif /* MOTOR_THERMAL_MODEL_H */
