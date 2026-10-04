/**
 * ============================================================================
 * Project: EV Dashboard & Motor Predictive Thermal Management System
 * Target: Texas Instruments C2000 Microcontrollers (TMS320F280049C / TMS320F28379D)
 * File: motor_thermal_estimator.c
 * Description: High-speed, numerical implementation of 4-Node PMSM Thermal Model
 *              and analytical state-space forward predictor.
 * ============================================================================
 */

#include "../include/motor_thermal_model.h"
#include <math.h>

void Motor_Thermal_Init(Motor_Thermal_Parameters_t *params, Motor_Thermal_State_t *state, float ambient_temp_C) {
    if (!params || !state) return;

    /* Standard automotive traction PMSM defaults (150 kW, 350 Nm peak) */
    params->R_stator_ref_ohm      = 0.018f;   /* 18 mOhm per phase at 20°C */
    params->alpha_copper_coeff    = 0.00393f; /* Copper temp coefficient */
    params->C_stator_windings_J_K = 2800.0f;  /* Thermal capacitance of windings */
    params->R_stator_to_core_K_W  = 0.038f;   /* Windings to Core resistance */

    params->C_stator_core_J_K     = 7200.0f;  /* Thermal capacitance of stator steel */
    params->R_core_to_frame_K_W   = 0.024f;   /* Core to Housing resistance */
    params->k_iron_hysteresis     = 0.0022f;  /* Hysteresis loss constant */
    params->k_iron_eddy           = 0.000045f;/* Eddy current loss constant */

    params->C_rotor_magnet_J_K    = 3400.0f;  /* Rotor + Magnet thermal capacitance */
    params->R_magnet_to_airgap_K_W= 0.110f;   /* Magnet to Airgap resistance */
    params->R_airgap_to_frame_K_W = 0.075f;   /* Airgap to Housing resistance */

    params->C_frame_housing_J_K   = 5600.0f;  /* Aluminum housing thermal capacitance */
    params->R_frame_to_coolant_K_W= 0.016f;   /* Housing to Coolant Jacket resistance */

    params->stator_temp_warning_C = 135.0f;
    params->stator_temp_trip_C    = 160.0f;
    params->rotor_temp_warning_C  = 110.0f;
    params->rotor_temp_trip_C     = 130.0f;

    /* Initialize initial state temperatures to ambient */
    state->T_stator_winding_C = ambient_temp_C;
    state->T_stator_core_C    = ambient_temp_C;
    state->T_rotor_magnet_C   = ambient_temp_C;
    state->T_housing_frame_C  = ambient_temp_C;
    state->dT_stator_dt       = 0.0f;
    state->dT_rotor_dt        = 0.0f;
}

void Motor_Thermal_Update_Step(const Motor_Thermal_Parameters_t *params,
                               Motor_Thermal_State_t *state,
                               const C2000_Motor_Raw_Telemetry_t *telemetry,
                               C2000_Motor_Thermal_Estimate_t *estimate,
                               float dt_seconds) {
    if (!params || !state || !telemetry || !estimate) return;

    /* 1. Calculate Temperature-dependent Stator Phase Resistance */
    float R_stator_actual = params->R_stator_ref_ohm * 
        (1.0f + params->alpha_copper_coeff * (state->T_stator_winding_C - 20.0f));

    /* 2. Copper Losses: P_cu = 3 * I_rms^2 * R_stator (or 3/2 * (Id^2 + Iq^2) * R_s) */
    float i_mag_squared = (telemetry->i_d_current_A * telemetry->i_d_current_A) + 
                          (telemetry->i_q_current_A * telemetry->i_q_current_A);
    float P_copper = 1.5f * i_mag_squared * R_stator_actual;

    /* 3. Iron / Core Losses: function of electrical frequency (speed) and flux */
    float speed_rad_s = (telemetry->motor_speed_rpm * 3.14159265f) / 30.0f;
    float electrical_freq_hz = (telemetry->motor_speed_rpm * 4.0f) / 60.0f; /* 4 pole pairs */
    if (electrical_freq_hz < 0.0f) electrical_freq_hz = -electrical_freq_hz;

    float P_iron = (params->k_iron_hysteresis * electrical_freq_hz) + 
                   (params->k_iron_eddy * electrical_freq_hz * electrical_freq_hz);
    P_iron *= (telemetry->dc_bus_voltage_V > 50.0f ? 1.0f : 0.1f);

    /* 4. Mechanical & Windage Losses */
    float P_mech = 0.000008f * speed_rad_s * speed_rad_s * speed_rad_s;
    if (P_mech > 400.0f) P_mech = 400.0f;

    /* 5. Rotor Magnet Eddy Current Loss */
    float P_rotor_eddy = 0.06f * P_iron + 0.0005f * i_mag_squared;

    /* 6. Dynamic Cooling Adjustment based on Coolant Flow Rate */
    float flow_factor = (telemetry->coolant_flow_rate_lpm > 2.0f) ? 
                        (1.0f + 0.15f * (telemetry->coolant_flow_rate_lpm - 5.0f)) : 0.4f;
    if (flow_factor < 0.3f) flow_factor = 0.3f;
    if (flow_factor > 2.0f) flow_factor = 2.0f;

    float R_coolant_effective = params->R_frame_to_coolant_K_W / flow_factor;
    float T_coolant = (telemetry->coolant_inlet_temp_C > 0.0f) ? telemetry->coolant_inlet_temp_C : 35.0f;

    /* 7. Heat Flux Calculations between Nodes */
    float q_stator_to_core = (state->T_stator_winding_C - state->T_stator_core_C) / params->R_stator_to_core_K_W;
    float q_core_to_frame  = (state->T_stator_core_C - state->T_housing_frame_C) / params->R_core_to_frame_K_W;
    float q_magnet_to_gap  = (state->T_rotor_magnet_C - state->T_housing_frame_C) / 
                             (params->R_magnet_to_airgap_K_W + params->R_airgap_to_frame_K_W);
    float q_frame_to_cool  = (state->T_housing_frame_C - T_coolant) / R_coolant_effective;

    /* 8. Differential Equations (dT/dt = Net Heat / Heat Capacity) */
    float dT_stator = (P_copper - q_stator_to_core) / params->C_stator_windings_J_K;
    float dT_core   = (P_iron + q_stator_to_core - q_core_to_frame) / params->C_stator_core_J_K;
    float dT_rotor  = (P_rotor_eddy - q_magnet_to_gap) / params->C_rotor_magnet_J_K;
    float dT_frame  = (q_core_to_frame + q_magnet_to_gap - q_frame_to_cool) / params->C_frame_housing_J_K;

    /* Sensor Fusion / Kalman correction if measured stator sensor is reliable */
    if (telemetry->stator_winding_temp_C > 0.0f) {
        float meas_error = telemetry->stator_winding_temp_C - state->T_stator_winding_C;
        dT_stator += 0.05f * meas_error; /* Observer gain */
    }

    /* 9. Numerical Integration (Euler Update) */
    state->T_stator_winding_C += dT_stator * dt_seconds;
    state->T_stator_core_C    += dT_core * dt_seconds;
    state->T_rotor_magnet_C   += dT_rotor * dt_seconds;
    state->T_housing_frame_C  += dT_frame * dt_seconds;

    state->dT_stator_dt = dT_stator;
    state->dT_rotor_dt  = dT_rotor;

    /* 10. Update Estimates for Telemetry */
    estimate->est_stator_core_temp_C  = state->T_stator_core_C;
    estimate->est_rotor_magnet_temp_C = state->T_rotor_magnet_C;
    estimate->copper_loss_watts       = P_copper;
    estimate->iron_loss_watts         = P_iron;
    estimate->mechanical_loss_watts   = P_mech;
    estimate->total_loss_watts        = P_copper + P_iron + P_mech + P_rotor_eddy;

    /* 11. Run Multi-Horizon Predictions */
    Motor_Thermal_Predict_Horizon(params, state, telemetry, estimate);
}

void Motor_Thermal_Predict_Horizon(const Motor_Thermal_Parameters_t *params,
                                   const Motor_Thermal_State_t *state,
                                   const C2000_Motor_Raw_Telemetry_t *telemetry,
                                   C2000_Motor_Thermal_Estimate_t *estimate) {
    if (!params || !state || !estimate) return;

    /*
     * Analytical Thermal Equilibrium & Multi-Horizon Forward Extrapolation:
     * T(t + tau) = T_steady_state + (T_current - T_steady_state) * exp(-tau / tau_thermal)
     */
    float T_coolant = (telemetry->coolant_inlet_temp_C > 0.0f) ? telemetry->coolant_inlet_temp_C : 35.0f;
    float R_total_stator = params->R_stator_to_core_K_W + params->R_core_to_frame_K_W + params->R_frame_to_coolant_K_W;
    float R_total_rotor  = params->R_magnet_to_airgap_K_W + params->R_airgap_to_frame_K_W + params->R_frame_to_coolant_K_W;

    /* Estimated steady-state asymptotic temperature under current continuous load */
    float T_stator_asymptotic = T_coolant + (estimate->copper_loss_watts * 0.9f + estimate->iron_loss_watts) * R_total_stator;
    float T_rotor_asymptotic  = T_coolant + (estimate->copper_loss_watts * 0.2f + estimate->iron_loss_watts * 0.5f) * R_total_rotor;

    /* Thermal Time Constants: tau = R_th * C_th */
    float tau_stator = params->C_stator_windings_J_K * params->R_stator_to_core_K_W + 90.0f; /* ~190 seconds */
    float tau_rotor  = params->C_rotor_magnet_J_K * (params->R_magnet_to_airgap_K_W + params->R_airgap_to_frame_K_W) + 240.0f; /* ~600 seconds */

    /* Predict at tau = 60s (+1 min), 300s (+5 min) */
    float exp_1m_stator = expf(-60.0f / tau_stator);
    float exp_5m_stator = expf(-300.0f / tau_stator);
    float exp_5m_rotor  = expf(-300.0f / tau_rotor);

    estimate->predicted_stator_temp_1m = T_stator_asymptotic + (state->T_stator_winding_C - T_stator_asymptotic) * exp_1m_stator;
    estimate->predicted_stator_temp_5m = T_stator_asymptotic + (state->T_stator_winding_C - T_stator_asymptotic) * exp_5m_stator;
    estimate->predicted_rotor_temp_5m  = T_rotor_asymptotic + (state->T_rotor_magnet_C - T_rotor_asymptotic) * exp_5m_rotor;

    /* Thermal Protection & Proactive Derating Calculation */
    uint8_t flags = 0;
    float max_torque = 350.0f; /* Base rated peak torque in Nm */

    /* Check Stator Thresholds */
    if (state->T_stator_winding_C > params->stator_temp_warning_C || estimate->predicted_stator_temp_5m > params->stator_temp_trip_C) {
        flags |= 0x01; /* Stator Warning flag */
        float derate_stator = (params->stator_temp_trip_C - estimate->predicted_stator_temp_5m) / 
                              (params->stator_temp_trip_C - params->stator_temp_warning_C);
        if (derate_stator < 0.2f) derate_stator = 0.2f;
        if (derate_stator > 1.0f) derate_stator = 1.0f;
        max_torque *= derate_stator;
    }

    /* Check Rotor Magnet Demagnetization Risk */
    if (state->T_rotor_magnet_C > params->rotor_temp_warning_C || estimate->predicted_rotor_temp_5m > params->rotor_temp_trip_C) {
        flags |= 0x02; /* Rotor Magnet Risk flag */
        float derate_rotor = (params->rotor_temp_trip_C - estimate->predicted_rotor_temp_5m) / 
                             (params->rotor_temp_trip_C - params->rotor_temp_warning_C);
        if (derate_rotor < 0.15f) derate_rotor = 0.15f;
        if (derate_rotor > 1.0f) derate_rotor = 1.0f;
        if (350.0f * derate_rotor < max_torque) {
            max_torque = 350.0f * derate_rotor;
        }
    }

    estimate->thermal_warning_flags = flags;
    estimate->max_allowable_torque_nm = max_torque;

    /* Smart Cooling Pump Command: scale pump PWM proactively */
    float temp_max_pred = (estimate->predicted_stator_temp_5m > estimate->predicted_rotor_temp_5m) ? 
                           estimate->predicted_stator_temp_5m : estimate->predicted_rotor_temp_5m;
    if (temp_max_pred < 60.0f) {
        estimate->cooling_pump_command = 20; /* 20% minimum circulation */
    } else if (temp_max_pred < 100.0f) {
        estimate->cooling_pump_command = (uint8_t)(20 + (temp_max_pred - 60.0f) * 1.5f);
    } else {
        estimate->cooling_pump_command = 100; /* 100% full active cooling */
    }
}
