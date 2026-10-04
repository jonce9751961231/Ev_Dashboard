/**
 * ============================================================================
 * 48V-96V BLDC Multi-Horizon Temperature AI Model Weights
 * Embedded C/C++ Header for ESP32 and TI C2000 Microcontrollers
 * Target: Multi-Horizon Stator & Rotor Magnet Temperature Forecasting
 * ============================================================================
 */

#ifndef BLDC_AI_WEIGHTS_H
#define BLDC_AI_WEIGHTS_H

#define AI_NUM_FEATURES 9
#define AI_NUM_HORIZONS 5

// Normalization Means for [V, I, RPM, P, T_stator, dT_dt, T_amb, P_cu, P_fe]
static const float AI_FEATURE_MEANS[9] = {
    72.0f, 18.5f, 3450.0f, 1332.0f, 52.0f, 0.12f, 30.0f, 115.0f, 45.0f
};

// Normalization Standard Deviations
static const float AI_FEATURE_STDS[9] = {
    17.5f, 14.2f, 1650.0f, 1120.0f, 24.0f, 0.28f, 5.0f, 145.0f, 38.0f
};

// Target Bias Vectors: [+1m, +5m, +15m, +30m, Rotor+5m]
static const float AI_BIAS[5] = {
    54.25f, 63.10f, 74.85f, 81.40f, 49.60f
};

// 9x5 Weight Matrix
static const float AI_WEIGHTS[9][5] = {
    {0.15f, 0.32f, 0.48f, 0.55f, 0.20f},
    {0.85f, 2.45f, 3.80f, 4.10f, 1.15f},
    {0.45f, 1.20f, 2.10f, 2.40f, 0.95f},
    {0.92f, 2.85f, 4.25f, 4.60f, 1.40f},
    {21.80f, 16.50f, 8.20f, 4.10f, 14.80f},
    {3.40f, 7.85f, 2.10f, 0.85f, 1.95f},
    {0.85f, 2.10f, 3.90f, 4.85f, 1.90f},
    {1.65f, 4.90f, 7.45f, 8.20f, 2.80f},
    {0.55f, 1.85f, 3.10f, 3.50f, 1.25f}
};

/**
 * @brief Evaluates the AI model on-chip on the ESP32
 * @param features Array of 9 input features
 * @param predictions_out Output array of 5 future temperature predictions
 */
inline void evaluate_bldc_ai_model(const float features[9], float predictions_out[5]) {
    float norm_features[9];
    for (int i = 0; i < 9; i++) {
        norm_features[i] = (features[i] - AI_FEATURE_MEANS[i]) / AI_FEATURE_STDS[i];
    }
    for (int j = 0; j < 5; j++) {
        float sum = AI_BIAS[j];
        for (int i = 0; i < 9; i++) {
            sum += norm_features[i] * AI_WEIGHTS[i][j];
        }
        predictions_out[j] = sum;
    }
}

#endif /* BLDC_AI_WEIGHTS_H */
