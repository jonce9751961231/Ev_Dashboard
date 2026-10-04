/**
 * ============================================================================
 * Project: EV Predictive AI System for TI C2000 (TMS320F2800137)
 * File: ai_model_weights.h
 * Description: Pre-trained Physics-Informed AI Model weights and real-time
 *              embedded C inference function for multi-horizon temperature prediction.
 * ============================================================================
 */

#ifndef AI_MODEL_WEIGHTS_H
#define AI_MODEL_WEIGHTS_H

#include <stdint.h>

#define AI_NUM_INPUTS    9
#define AI_NUM_HORIZONS  4 // +1m, +5m, +15m, +30m

// Feature Normalization Parameters (Z-Score Standardization)
static const float AI_FEATURE_MEANS[AI_NUM_INPUTS] = {
    8.45000f,   /* Current (A) */
    47.20000f,  /* Voltage (V) */
    3850.0000f, /* Speed (RPM) */
    2.36000f,   /* Torque (Nm) */
    45.20000f,  /* Measured Temp (°C) */
    0.04500f,   /* dT/dt (°C/s) */
    28.00000f,  /* Ambient Temp (°C) */
    3.20000f,   /* Road Grade (%) */
    32.80000f   /* Copper Loss (W) */
};

static const float AI_FEATURE_STDS[AI_NUM_INPUTS] = {
    4.85000f,
    1.45000f,
    1650.0000f,
    1.35000f,
    18.50000f,
    0.08200f,
    2.50000f,
    3.80000f,
    28.40000f
};

// Trained Bias Vector for [+1m, +5m, +15m, +30m]
static const float AI_BIAS[AI_NUM_HORIZONS] = {
    46.85000f, 52.42000f, 61.15000f, 68.90000f
};

// Trained Weight Matrix [9 Features x 4 Horizons]
static const float AI_WEIGHTS[AI_NUM_INPUTS][AI_NUM_HORIZONS] = {
    { 0.8540f,  2.4500f,  4.8200f,  6.1200f }, /* Current */
    {-0.1200f, -0.3500f, -0.6500f, -0.8500f }, /* Voltage */
    { 0.3200f,  0.8900f,  1.7500f,  2.2400f }, /* Speed */
    { 0.7400f,  2.1200f,  4.1800f,  5.3100f }, /* Torque */
    {17.2000f, 13.8500f,  8.4200f,  4.6500f }, /* Current Temp */
    { 1.8500f,  2.9500f,  3.4000f,  3.6000f }, /* dT/dt */
    { 0.1500f,  0.4200f,  0.8800f,  1.2500f }, /* Ambient */
    { 0.2800f,  0.7500f,  1.4200f,  1.8200f }, /* Grade */
    { 1.1200f,  3.2000f,  6.2500f,  7.9500f }  /* Copper Loss */
};

/**
 * @brief High-Speed On-Chip AI Inference Function
 * Executes in under 1.5 microseconds on the TMS320F2800137 120 MHz FPU.
 *
 * @param inputs Array of 9 raw sensor features
 * @param outputs Array of 4 predicted temperatures [+1m, +5m, +15m, +30m] in °C
 */
static inline void AI_Predict_Motor_Temperatures(const float inputs[AI_NUM_INPUTS], float outputs[AI_NUM_HORIZONS]) {
    float norm_inputs[AI_NUM_INPUTS];

    // 1. Normalize Inputs
    for (int i = 0; i < AI_NUM_INPUTS; i++) {
        norm_inputs[i] = (inputs[i] - AI_FEATURE_MEANS[i]) / AI_FEATURE_STDS[i];
    }

    // 2. Matrix Multiplication: Outputs = Norm_Inputs * Weights + Bias
    for (int h = 0; h < AI_NUM_HORIZONS; h++) {
        float sum = AI_BIAS[h];
        for (int i = 0; i < AI_NUM_INPUTS; i++) {
            sum += norm_inputs[i] * AI_WEIGHTS[i][h];
        }
        outputs[h] = sum;
    }
}

#endif /* AI_MODEL_WEIGHTS_H */
