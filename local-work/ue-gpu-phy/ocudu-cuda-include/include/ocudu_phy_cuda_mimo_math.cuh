// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/*
 * OCUDU PHY CUDA - CUDA-accelerated 5G NR PHY processing
 *
 * MIMO Matrix Mathematics - Shared header for MIMO equalization
 *
 * This header provides device functions for MIMO matrix operations:
 * - 2x2 and 4x4 Hermitian matrix inversion
 * - Gram matrix computation
 * - MIMO equalization helpers
 *
 * Used by both equalization.cu (standalone) and pusch_e2e.cu (fused kernels).
 */

#pragma once

#include <cuda_runtime.h>
#include <cuComplex.h>

/* ============================================================================
 * 2x2 Hermitian Matrix Inversion
 * ============================================================================ */

/**
 * @brief Analytic 2x2 Hermitian matrix inversion
 *
 * Inverts G = [[g00, g01], [g10, g11]] using closed-form formula:
 *   det(G) = g00*g11 - g01*g10
 *   G^{-1} = adj(G) / det(G) = [[g11, -g01], [-g10, g00]] / det(G)
 *
 * Note: For Hermitian matrices, g10 = conj(g01), so we only need g00, g01, g11 as inputs.
 *
 * @param g00      Diagonal element (0,0) - must be real (imaginary part ignored)
 * @param g01      Off-diagonal element (0,1)
 * @param g11      Diagonal element (1,1) - must be real (imaginary part ignored)
 * @param inv_out  Output: [inv00, inv01, inv10, inv11] in row-major order
 * @param reg      Regularization factor to prevent division by zero
 */
__device__ __forceinline__ void mimo_invert_2x2_hermitian(
    cuFloatComplex g00,
    cuFloatComplex g01,
    cuFloatComplex g11,
    cuFloatComplex* inv_out,
    float reg = 1e-6f)
{
    // g10 = conj(g01) for Hermitian matrix
    cuFloatComplex g10 = cuConjf(g01);

    // det(G) = g00*g11 - |g01|² for Hermitian matrices.
    float det_real = g00.x * g11.x - (g01.x * g01.x + g01.y * g01.y);
    float det_mag_sq = det_real * det_real;

    // Regularized inverse: 1 / (det + reg)
    float inv_det = det_real / (det_mag_sq + reg);

    // adj(G) = [[g11, -g01], [-g10, g00]]
    // G^{-1} = adj(G) / det
    inv_out[0] = make_cuFloatComplex(g11.x * inv_det, 0.0f);  // inv00 is real
    inv_out[1] = make_cuFloatComplex(-g01.x * inv_det, -g01.y * inv_det);
    inv_out[2] = make_cuFloatComplex(-g10.x * inv_det, -g10.y * inv_det);
    inv_out[3] = make_cuFloatComplex(g00.x * inv_det, 0.0f);  // inv11 is real
}

/* ============================================================================
 * 4x4 Hermitian Matrix Inversion
 * ============================================================================ */

/**
 * @brief 4x4 Hermitian matrix inversion using block LU decomposition
 *
 * Partition G = [[A, B], [C, D]] where A, B, C, D are 2x2 blocks.
 * For Hermitian G: C = B^H, so only A, B, D need to be computed.
 *
 * Using Schur complement:
 *   S = D - C * A^{-1} * B = D - B^H * A^{-1} * B
 *   G^{-1} = [[A^{-1} + A^{-1}*B*S^{-1}*B^H*A^{-1}, -A^{-1}*B*S^{-1}],
 *            [-S^{-1}*B^H*A^{-1},                    S^{-1}]]
 *
 * This reduces to two 2x2 inversions (A and S) plus matrix multiplications.
 *
 * @param G      Input 16 elements [4x4] in row-major order
 * @param G_inv  Output 16 elements [4x4] in row-major order
 * @param reg    Regularization factor to prevent division by zero
 */
__device__ __forceinline__ void mimo_invert_4x4_hermitian_block_lu(
    const cuFloatComplex* G,
    cuFloatComplex* G_inv,
    float reg = 1e-6f)
{
    // Extract blocks: G = [[A, B], [C, D]]
    // A = G[0:2, 0:2], B = G[0:2, 2:4], C = G[2:4, 0:2], D = G[2:4, 2:4]
    // For Hermitian: C = B^H

    // A block (indices 0,1,4,5) - only upper triangle needed for Hermitian
    cuFloatComplex A00 = G[0], A01 = G[1];
    cuFloatComplex A11 = G[5];
    (void)G[4];  // A10 = conj(A01) for Hermitian

    // B block (indices 2,3,6,7)
    cuFloatComplex B00 = G[2], B01 = G[3];
    cuFloatComplex B10 = G[6], B11 = G[7];

    // D block (indices 10,11,14,15) - only upper triangle needed for Hermitian
    cuFloatComplex D00 = G[10], D01 = G[11];
    cuFloatComplex D11 = G[15];
    (void)G[14];  // D10 = conj(D01) for Hermitian

    // Step 1: Invert A (2x2 Hermitian)
    cuFloatComplex A_inv[4];
    mimo_invert_2x2_hermitian(A00, A01, A11, A_inv, reg);

    // Step 2: Compute A^{-1} * B (2x2 matrix multiplication)
    // AinvB[i,j] = sum_k A_inv[i,k] * B[k,j]
    cuFloatComplex AinvB[4];
    AinvB[0] = cuCaddf(cuCmulf(A_inv[0], B00), cuCmulf(A_inv[1], B10));  // [0,0]
    AinvB[1] = cuCaddf(cuCmulf(A_inv[0], B01), cuCmulf(A_inv[1], B11));  // [0,1]
    AinvB[2] = cuCaddf(cuCmulf(A_inv[2], B00), cuCmulf(A_inv[3], B10));  // [1,0]
    AinvB[3] = cuCaddf(cuCmulf(A_inv[2], B01), cuCmulf(A_inv[3], B11));  // [1,1]

    // Step 3: Compute Schur complement S = D - B^H * A^{-1} * B
    // B^H = [[conj(B00), conj(B10)], [conj(B01), conj(B11)]]
    // B^H * AinvB:
    cuFloatComplex BH_AinvB[4];
    BH_AinvB[0] = cuCaddf(cuCmulf(cuConjf(B00), AinvB[0]), cuCmulf(cuConjf(B10), AinvB[2]));
    BH_AinvB[1] = cuCaddf(cuCmulf(cuConjf(B00), AinvB[1]), cuCmulf(cuConjf(B10), AinvB[3]));
    BH_AinvB[2] = cuCaddf(cuCmulf(cuConjf(B01), AinvB[0]), cuCmulf(cuConjf(B11), AinvB[2]));
    BH_AinvB[3] = cuCaddf(cuCmulf(cuConjf(B01), AinvB[1]), cuCmulf(cuConjf(B11), AinvB[3]));

    // S = D - BH_AinvB
    cuFloatComplex S00 = cuCsubf(D00, BH_AinvB[0]);
    cuFloatComplex S01 = cuCsubf(D01, BH_AinvB[1]);
    cuFloatComplex S11 = cuCsubf(D11, BH_AinvB[3]);

    // Step 4: Invert S (2x2 Hermitian)
    cuFloatComplex S_inv[4];
    mimo_invert_2x2_hermitian(S00, S01, S11, S_inv, reg);

    // Step 5: Compute intermediate products for final result

    // -A^{-1}*B*S^{-1} = -AinvB * S_inv
    cuFloatComplex neg_AinvB_Sinv[4];
    neg_AinvB_Sinv[0] = make_cuFloatComplex(
        -(AinvB[0].x * S_inv[0].x - AinvB[0].y * S_inv[0].y + AinvB[1].x * S_inv[2].x - AinvB[1].y * S_inv[2].y),
        -(AinvB[0].x * S_inv[0].y + AinvB[0].y * S_inv[0].x + AinvB[1].x * S_inv[2].y + AinvB[1].y * S_inv[2].x));
    neg_AinvB_Sinv[1] = make_cuFloatComplex(
        -(AinvB[0].x * S_inv[1].x - AinvB[0].y * S_inv[1].y + AinvB[1].x * S_inv[3].x - AinvB[1].y * S_inv[3].y),
        -(AinvB[0].x * S_inv[1].y + AinvB[0].y * S_inv[1].x + AinvB[1].x * S_inv[3].y + AinvB[1].y * S_inv[3].x));
    neg_AinvB_Sinv[2] = make_cuFloatComplex(
        -(AinvB[2].x * S_inv[0].x - AinvB[2].y * S_inv[0].y + AinvB[3].x * S_inv[2].x - AinvB[3].y * S_inv[2].y),
        -(AinvB[2].x * S_inv[0].y + AinvB[2].y * S_inv[0].x + AinvB[3].x * S_inv[2].y + AinvB[3].y * S_inv[2].x));
    neg_AinvB_Sinv[3] = make_cuFloatComplex(
        -(AinvB[2].x * S_inv[1].x - AinvB[2].y * S_inv[1].y + AinvB[3].x * S_inv[3].x - AinvB[3].y * S_inv[3].y),
        -(AinvB[2].x * S_inv[1].y + AinvB[2].y * S_inv[1].x + AinvB[3].x * S_inv[3].y + AinvB[3].y * S_inv[3].x));

    // -S^{-1}*B^H*A^{-1} is the Hermitian transpose of -A^{-1}*B*S^{-1}
    // (since G^{-1} is also Hermitian)
    cuFloatComplex neg_Sinv_BH_Ainv[4];
    neg_Sinv_BH_Ainv[0] = cuConjf(neg_AinvB_Sinv[0]);
    neg_Sinv_BH_Ainv[1] = cuConjf(neg_AinvB_Sinv[2]);
    neg_Sinv_BH_Ainv[2] = cuConjf(neg_AinvB_Sinv[1]);
    neg_Sinv_BH_Ainv[3] = cuConjf(neg_AinvB_Sinv[3]);

    // A^{-1} + A^{-1}*B*S^{-1}*B^H*A^{-1}
    // = A^{-1} + (-AinvB_Sinv) * (-B^H*A^{-1})
    // = A^{-1} + AinvB_Sinv * B^H * A^{-1}
    // Compute (AinvB_Sinv) * (B^H * A^{-1})
    // First: B^H * A^{-1}
    cuFloatComplex BH_Ainv[4];
    BH_Ainv[0] = cuCaddf(cuCmulf(cuConjf(B00), A_inv[0]), cuCmulf(cuConjf(B10), A_inv[2]));
    BH_Ainv[1] = cuCaddf(cuCmulf(cuConjf(B00), A_inv[1]), cuCmulf(cuConjf(B10), A_inv[3]));
    BH_Ainv[2] = cuCaddf(cuCmulf(cuConjf(B01), A_inv[0]), cuCmulf(cuConjf(B11), A_inv[2]));
    BH_Ainv[3] = cuCaddf(cuCmulf(cuConjf(B01), A_inv[1]), cuCmulf(cuConjf(B11), A_inv[3]));

    // Then: (-neg_AinvB_Sinv) * BH_Ainv = AinvB_Sinv * BH_Ainv
    // But we have neg_AinvB_Sinv, so negate the result
    cuFloatComplex correction[4];
    correction[0] = cuCaddf(cuCmulf(neg_AinvB_Sinv[0], BH_Ainv[0]), cuCmulf(neg_AinvB_Sinv[1], BH_Ainv[2]));
    correction[1] = cuCaddf(cuCmulf(neg_AinvB_Sinv[0], BH_Ainv[1]), cuCmulf(neg_AinvB_Sinv[1], BH_Ainv[3]));
    correction[2] = cuCaddf(cuCmulf(neg_AinvB_Sinv[2], BH_Ainv[0]), cuCmulf(neg_AinvB_Sinv[3], BH_Ainv[2]));
    correction[3] = cuCaddf(cuCmulf(neg_AinvB_Sinv[2], BH_Ainv[1]), cuCmulf(neg_AinvB_Sinv[3], BH_Ainv[3]));

    // Top-left block: A^{-1} - correction (since correction used negated AinvB_Sinv)
    G_inv[0] = cuCsubf(A_inv[0], correction[0]);
    G_inv[1] = cuCsubf(A_inv[1], correction[1]);
    G_inv[4] = cuCsubf(A_inv[2], correction[2]);
    G_inv[5] = cuCsubf(A_inv[3], correction[3]);

    // Top-right block: -A^{-1}*B*S^{-1}
    G_inv[2] = neg_AinvB_Sinv[0];
    G_inv[3] = neg_AinvB_Sinv[1];
    G_inv[6] = neg_AinvB_Sinv[2];
    G_inv[7] = neg_AinvB_Sinv[3];

    // Bottom-left block: -S^{-1}*B^H*A^{-1}
    G_inv[8]  = neg_Sinv_BH_Ainv[0];
    G_inv[9]  = neg_Sinv_BH_Ainv[1];
    G_inv[12] = neg_Sinv_BH_Ainv[2];
    G_inv[13] = neg_Sinv_BH_Ainv[3];

    // Bottom-right block: S^{-1}
    G_inv[10] = S_inv[0];
    G_inv[11] = S_inv[1];
    G_inv[14] = S_inv[2];
    G_inv[15] = S_inv[3];
}

/* ============================================================================
 * Gram Matrix Computation
 * ============================================================================ */

/**
 * @brief Compute 2x2 Gram matrix G = H^H * H for MIMO equalization
 *
 * For 2-layer MIMO with N RX ports:
 *   H is [N x 2] channel matrix
 *   G = H^H * H is [2 x 2] Hermitian matrix
 *
 * @tparam NOF_PORTS  Number of RX ports (compile-time constant)
 * @param H           Channel matrix H[port][layer]
 * @param G           Output: [G00, G01, G10, G11] - only G00, G01, G11 needed (Hermitian)
 */
template <int NOF_PORTS>
__device__ __forceinline__ void mimo_compute_gram_2x2(
    const cuFloatComplex H[NOF_PORTS][2],
    cuFloatComplex* G)
{
    // G[i][j] = sum_p conj(H[p][i]) * H[p][j]
    cuFloatComplex G00 = make_cuFloatComplex(0.0f, 0.0f);
    cuFloatComplex G01 = make_cuFloatComplex(0.0f, 0.0f);
    cuFloatComplex G11 = make_cuFloatComplex(0.0f, 0.0f);

    #pragma unroll
    for (int p = 0; p < NOF_PORTS; p++) {
        cuFloatComplex h0 = H[p][0];
        cuFloatComplex h1 = H[p][1];

        // G00 = sum |h0|² (real)
        G00.x += h0.x * h0.x + h0.y * h0.y;

        // G01 = sum conj(h0) * h1
        G01 = cuCaddf(G01, cuCmulf(cuConjf(h0), h1));

        // G11 = sum |h1|² (real)
        G11.x += h1.x * h1.x + h1.y * h1.y;
    }

    // Store (G10 = conj(G01) computed implicitly by inversion)
    G[0] = G00;
    G[1] = G01;
    G[2] = cuConjf(G01);  // G10 = conj(G01)
    G[3] = G11;
}

/**
 * @brief Compute 4x4 Gram matrix G = H^H * H for MIMO equalization
 *
 * For 4-layer MIMO with N RX ports:
 *   H is [N x 4] channel matrix
 *   G = H^H * H is [4 x 4] Hermitian matrix
 *
 * @tparam NOF_PORTS  Number of RX ports (compile-time constant)
 * @param H           Channel matrix H[port][layer]
 * @param G           Output: 16 elements [4x4] in row-major order
 */
template <int NOF_PORTS>
__device__ __forceinline__ void mimo_compute_gram_4x4(
    const cuFloatComplex H[NOF_PORTS][4],
    cuFloatComplex* G)
{
    // G[i][j] = sum_p conj(H[p][i]) * H[p][j]
    #pragma unroll
    for (int i = 0; i < 4; i++) {
        #pragma unroll
        for (int j = i; j < 4; j++) {  // Only upper triangle (Hermitian)
            cuFloatComplex sum = make_cuFloatComplex(0.0f, 0.0f);
            #pragma unroll
            for (int p = 0; p < NOF_PORTS; p++) {
                sum = cuCaddf(sum, cuCmulf(cuConjf(H[p][i]), H[p][j]));
            }
            G[i * 4 + j] = sum;
            if (i != j) {
                G[j * 4 + i] = cuConjf(sum);  // Lower triangle
            }
        }
    }
}

/* ============================================================================
 * MIMO Equalization Helpers
 * ============================================================================ */

/**
 * @brief 2-layer MIMO ZF equalization
 *
 * Computes equalized symbols for both layers:
 *   eq = G^{-1} * H^H * y
 *
 * @tparam NOF_PORTS  Number of RX ports
 * @param y           Received symbols [NOF_PORTS]
 * @param H           Channel matrix H[port][layer]
 * @param G_inv       Inverse Gram matrix [4] (2x2 row-major)
 * @param noise_vars  Per-port noise variances [NOF_PORTS]
 * @param tx_scaling  Transmit scaling factor
 * @param eq_out      Output: Equalized symbols [2]
 * @param eq_noise_out Output: Per-layer noise variances [2]
 */
template <int NOF_PORTS>
__device__ __forceinline__ void mimo_equalize_2layer(
    const cuFloatComplex y[NOF_PORTS],
    const cuFloatComplex H[NOF_PORTS][2],
    const cuFloatComplex G_inv[4],
    const float* noise_vars,
    float tx_scaling,
    cuFloatComplex eq_out[2],
    float eq_noise_out[2])
{
    // Compute matched filter: mf = H^H * y [2x1]
    cuFloatComplex mf[2] = {make_cuFloatComplex(0.0f, 0.0f), make_cuFloatComplex(0.0f, 0.0f)};
    float avg_noise_var = 0.0f;

    #pragma unroll
    for (int p = 0; p < NOF_PORTS; p++) {
        // mf[layer] = sum conj(H[p][layer]) * y[p]
        mf[0] = cuCaddf(mf[0], cuCmulf(cuConjf(H[p][0]), y[p]));
        mf[1] = cuCaddf(mf[1], cuCmulf(cuConjf(H[p][1]), y[p]));
        avg_noise_var += noise_vars[p];
    }
    avg_noise_var /= NOF_PORTS;

    // ZF equalization: eq = G^{-1} * mf
    float inv_scaling = 1.0f / tx_scaling;

    cuFloatComplex eq0 = cuCaddf(cuCmulf(G_inv[0], mf[0]), cuCmulf(G_inv[1], mf[1]));
    cuFloatComplex eq1 = cuCaddf(cuCmulf(G_inv[2], mf[0]), cuCmulf(G_inv[3], mf[1]));

    eq_out[0] = make_cuFloatComplex(eq0.x * inv_scaling, eq0.y * inv_scaling);
    eq_out[1] = make_cuFloatComplex(eq1.x * inv_scaling, eq1.y * inv_scaling);

    // Per-layer noise variance: σ²_layer = avg_noise_var * G^{-1}[layer][layer] / tx_scaling²
    float noise_scale = avg_noise_var / (tx_scaling * tx_scaling);
    eq_noise_out[0] = noise_scale * G_inv[0].x;  // G_inv[0][0] is real
    eq_noise_out[1] = noise_scale * G_inv[3].x;  // G_inv[1][1] is real
}

/**
 * @brief 4-layer MIMO ZF equalization
 *
 * Computes equalized symbols for all 4 layers:
 *   eq = G^{-1} * H^H * y
 *
 * @tparam NOF_PORTS  Number of RX ports
 * @param y           Received symbols [NOF_PORTS]
 * @param H           Channel matrix H[port][layer]
 * @param G_inv       Inverse Gram matrix [16] (4x4 row-major)
 * @param noise_vars  Per-port noise variances [NOF_PORTS]
 * @param tx_scaling  Transmit scaling factor
 * @param eq_out      Output: Equalized symbols [4]
 * @param eq_noise_out Output: Per-layer noise variances [4]
 */
template <int NOF_PORTS>
__device__ __forceinline__ void mimo_equalize_4layer(
    const cuFloatComplex y[NOF_PORTS],
    const cuFloatComplex H[NOF_PORTS][4],
    const cuFloatComplex G_inv[16],
    const float* noise_vars,
    float tx_scaling,
    cuFloatComplex eq_out[4],
    float eq_noise_out[4])
{
    // Compute matched filter: mf = H^H * y [4x1]
    cuFloatComplex mf[4];
    float avg_noise_var = 0.0f;

    #pragma unroll
    for (int l = 0; l < 4; l++) {
        mf[l] = make_cuFloatComplex(0.0f, 0.0f);
    }

    #pragma unroll
    for (int p = 0; p < NOF_PORTS; p++) {
        #pragma unroll
        for (int l = 0; l < 4; l++) {
            mf[l] = cuCaddf(mf[l], cuCmulf(cuConjf(H[p][l]), y[p]));
        }
        avg_noise_var += noise_vars[p];
    }
    avg_noise_var /= NOF_PORTS;

    // ZF equalization: eq = G^{-1} * mf
    float inv_scaling = 1.0f / tx_scaling;

    #pragma unroll
    for (int l = 0; l < 4; l++) {
        cuFloatComplex eq = make_cuFloatComplex(0.0f, 0.0f);
        #pragma unroll
        for (int k = 0; k < 4; k++) {
            eq = cuCaddf(eq, cuCmulf(G_inv[l * 4 + k], mf[k]));
        }
        eq_out[l] = make_cuFloatComplex(eq.x * inv_scaling, eq.y * inv_scaling);

        // Noise variance from diagonal of G^{-1}
        float noise_scale = avg_noise_var / (tx_scaling * tx_scaling);
        eq_noise_out[l] = noise_scale * G_inv[l * 4 + l].x;  // Diagonal is real
    }
}

/* ============================================================================
 * 5G NR DMRS Layer Separation Constants
 * ============================================================================ */

/**
 * @brief DMRS Type 1 OCC (Orthogonal Cover Code) patterns
 *
 * Type 1 DMRS uses CDM groups with frequency-domain OCC:
 * - CDM Group 0: subcarriers 0,2,4,6,8,10 (DMRS indices 0-5)
 * - CDM Group 1: subcarriers 1,3,5,7,9,11 (DMRS indices 0-5)
 *
 * Within each CDM group, layers are separated by frequency OCC:
 * - Layer 0,2: w_f[0] = [+1, +1] (even DMRS in CDM group)
 * - Layer 1,3: w_f[1] = [+1, -1] (odd DMRS in CDM group)
 *
 * OCC despreading for 2 layers in same CDM group:
 *   h0 = (rx[k] * conj(p[k]) + rx[k+1] * conj(p[k+1])) / 2
 *   h1 = (rx[k] * conj(p[k]) - rx[k+1] * conj(p[k+1])) / 2
 *
 * For 4 layers:
 *   CDM Group 0: layers 0,1 with OCC [+1,+1], [+1,-1]
 *   CDM Group 1: layers 2,3 with OCC [+1,+1], [+1,-1]
 */

// OCC pattern indices for layer separation
// Layer 0: CDM 0, OCC [+1, +1]
// Layer 1: CDM 0, OCC [+1, -1]
// Layer 2: CDM 1, OCC [+1, +1]
// Layer 3: CDM 1, OCC [+1, -1]
__device__ __constant__ int MIMO_LAYER_CDM_GROUP[4] = {0, 0, 1, 1};
__device__ __constant__ int MIMO_LAYER_OCC_SIGN[4] = {1, -1, 1, -1};  // Second OCC element

/**
 * @brief Apply OCC despreading for 2-layer MIMO channel estimation
 *
 * Separates layers 0 and 1 from CDM group 0 using frequency OCC.
 *
 * @param h_even  Channel estimate from even DMRS RE pair (rx * conj(pilot))
 * @param h_odd   Channel estimate from odd DMRS RE pair
 * @param h0_out  Output: Layer 0 channel estimate
 * @param h1_out  Output: Layer 1 channel estimate
 */
__device__ __forceinline__ void mimo_occ_despread_2layer(
    cuFloatComplex h_even,
    cuFloatComplex h_odd,
    cuFloatComplex* h0_out,
    cuFloatComplex* h1_out)
{
    // Layer 0: OCC [+1, +1] -> (h_even + h_odd) / 2
    // Layer 1: OCC [+1, -1] -> (h_even - h_odd) / 2
    *h0_out = make_cuFloatComplex(
        (h_even.x + h_odd.x) * 0.5f,
        (h_even.y + h_odd.y) * 0.5f);
    *h1_out = make_cuFloatComplex(
        (h_even.x - h_odd.x) * 0.5f,
        (h_even.y - h_odd.y) * 0.5f);
}
