// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/**
 * @file ldpc_encoder.h
 * @brief 5G NR LDPC Encoder Interface
 *
 * CUDA-accelerated LDPC encoder for 5G NR transport blocks.
 * Uses parallel encoding with warp-level __ballot_sync.
 */

#pragma once

#include "nr_ldpc_defs.h"
#include <cuda_runtime.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief LDPC Encoder handle (opaque)
 */
typedef struct ldpc_encoder_ctx* ldpc_encoder_handle_t;

// ============================================================================
// LDPC Encoder API
// ============================================================================

/**
 * @brief Create LDPC encoder context
 */
nr_ldpc_status_t ldpc_encoder_create(ldpc_encoder_handle_t* handle);

/**
 * @brief Configure LDPC encoder
 */
nr_ldpc_status_t ldpc_encoder_configure(ldpc_encoder_handle_t handle, const nr_ldpc_config_t* cfg);

/**
 * @brief Encode a single codeword
 */
nr_ldpc_status_t
ldpc_encoder_encode(ldpc_encoder_handle_t handle, const uint32_t* d_input, uint32_t* d_output, cudaStream_t stream);

/**
 * @brief Encode batch of codewords
 */
nr_ldpc_status_t ldpc_encoder_encode_batch(ldpc_encoder_handle_t handle,
                                           const uint32_t*       d_input,
                                           uint32_t*             d_output,
                                           int                   num_codewords,
                                           cudaStream_t          stream);

/**
 * @brief Destroy encoder
 */
void ldpc_encoder_destroy(ldpc_encoder_handle_t handle);

/**
 * @brief Get input words for encoder
 */
int ldpc_encoder_get_input_words(ldpc_encoder_handle_t handle);

/**
 * @brief Get output words for encoder
 */
int ldpc_encoder_get_output_words(ldpc_encoder_handle_t handle);

/**
 * @brief Get input bits for encoder
 */
int ldpc_encoder_get_input_bits(ldpc_encoder_handle_t handle);

/**
 * @brief Get output bits for encoder
 */
int ldpc_encoder_get_output_bits(ldpc_encoder_handle_t handle);

/**
 * @brief Rate matching configuration for fused encoder
 */
typedef struct {
  int N_cb;               /**< Circular buffer size (N_full - 2*Z) */
  int k0;                 /**< Starting position in circular buffer */
  int E;                  /**< Rate-matched output bits per CB */
  int Kd;                 /**< Actual info bits (excluding filler) in CB coords */
  int F;                  /**< Filler bits */
  int puncture_offset;    /**< Offset for punctured bits (2*Z) */
  int output_word_stride; /**< Output stride per CB in words (0 = auto) */
} ldpc_rate_match_config_t;

#ifdef __cplusplus
}
#endif
