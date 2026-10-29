// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/**
 * @file rate_matching.h
 * @brief 5G NR Rate Matching Interface
 *
 * CUDA-accelerated rate matching and de-rate matching for 5G NR LDPC codes.
 * Implements circular buffer rate matching per 3GPP TS 38.212.
 */

#pragma once

#include "nr_ldpc_defs.h"
#include <cuda_runtime.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Rate Matching handle (opaque)
 */
typedef struct rate_matcher_ctx* rate_matcher_handle_t;

/**
 * @brief Create rate matching context
 * @param handle Output handle
 * @return Status code
 */
nr_ldpc_status_t rate_matcher_create(rate_matcher_handle_t* handle);

/**
 * @brief Destroy rate matching context
 * @param handle Rate matcher handle
 */
void rate_matcher_destroy(rate_matcher_handle_t handle);

/**
 * @brief Configure rate matcher for encoding direction (bit selection)
 * @param handle Rate matcher handle
 * @param ldpc_cfg LDPC configuration
 * @param rm_cfg Rate matching configuration
 * @return Status code
 */
nr_ldpc_status_t rate_matcher_configure_tx(rate_matcher_handle_t         handle,
                                           const nr_ldpc_config_t*       ldpc_cfg,
                                           const nr_rate_match_config_t* rm_cfg);

/**
 * @brief Configure rate matcher for decoding direction (de-rate matching)
 * @param handle Rate matcher handle
 * @param ldpc_cfg LDPC configuration
 * @param rm_cfg Rate matching configuration
 * @return Status code
 */
nr_ldpc_status_t rate_matcher_configure_rx(rate_matcher_handle_t         handle,
                                           const nr_ldpc_config_t*       ldpc_cfg,
                                           const nr_rate_match_config_t* rm_cfg);

/**
 * @brief Perform rate matching (bit selection from circular buffer)
 * @param handle Rate matcher handle
 * @param d_encoded_bits Device pointer to LDPC encoded bits (N bits as uint32_t)
 * @param d_rate_matched Device pointer to output rate matched bits
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t rate_matcher_match(rate_matcher_handle_t handle,
                                    const uint32_t*       d_encoded_bits,
                                    uint32_t*             d_rate_matched,
                                    cudaStream_t          stream);

/**
 * @brief Perform batch rate matching for multiple code blocks (uniform E, F)
 * @param handle Rate matcher handle (configured for per-CB parameters)
 * @param d_encoded_bits Device pointer to encoded bits (num_cbs CBs, contiguous)
 * @param d_rate_matched Device pointer to output rate matched bits
 * @param num_cbs Number of code blocks to process
 * @param stream CUDA stream
 * @return Status code
 *
 * NOTE: All CBs must have the same E and configuration. This is much faster
 * than calling rate_matcher_match in a loop - single kernel launch for all CBs!
 */
nr_ldpc_status_t rate_matcher_match_batch(rate_matcher_handle_t handle,
                                          const uint32_t*       d_encoded_bits,
                                          uint32_t*             d_rate_matched,
                                          int                   num_cbs,
                                          cudaStream_t          stream);

/**
 * @brief Perform batch rate matching with configurable output stride
 *
 * This variant allows specifying a custom output stride per CB, which is needed
 * when rate matching CBs with different E values into a uniform buffer layout.
 *
 * @param handle Rate matcher handle (configured for the E value of these CBs)
 * @param d_encoded_bits Input encoded bits (num_cbs * encoded_words per CB)
 * @param d_rate_matched Output rate matched bits (num_cbs * output_word_stride)
 * @param num_cbs Number of codeblocks
 * @param output_word_stride Output stride per CB in words (0 = use (E+31)/32)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t rate_matcher_match_batch_strided(rate_matcher_handle_t handle,
                                                  const uint32_t*       d_encoded_bits,
                                                  uint32_t*             d_rate_matched,
                                                  int                   num_cbs,
                                                  int                   output_word_stride,
                                                  cudaStream_t          stream);

/**
 * @brief Perform de-rate matching (LLR combining into circular buffer)
 * @param handle Rate matcher handle
 * @param d_received_llrs Device pointer to received LLRs (E values)
 * @param d_output_llrs Device pointer to output LLRs (N values)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t rate_matcher_dematch(rate_matcher_handle_t handle,
                                      const float*          d_received_llrs,
                                      float*                d_output_llrs,
                                      cudaStream_t          stream);

/**
 * @brief Compute k0 (starting position) for given redundancy version
 * @param bg Base graph (1 or 2)
 * @param Z Lifting size
 * @param rv Redundancy version (0-3)
 * @param N_cb Circular buffer size
 * @return k0 value
 */
int rate_matcher_compute_k0(int bg, int Z, int rv, int N_cb);

/**
 * @brief Get rate matched output size
 * @param handle Rate matcher handle
 * @return E (rate matched output bits)
 */
int rate_matcher_get_output_bits(rate_matcher_handle_t handle);

// ============================================================================
// Bit Interleaving Functions (per 3GPP TS 38.212 Section 5.4.2.2)
// ============================================================================

/**
 * @brief Bit interleaving for TX path
 *
 * Interleaves bits according to modulation order per 3GPP TS 38.212.
 * For 16QAM, 64QAM, and 256QAM, bits are reordered to optimize
 * reliability of MSB/LSB positions in QAM constellation.
 *
 * @param handle Rate matcher handle
 * @param d_input Input bits (packed uint32_t)
 * @param d_output Output interleaved bits (packed uint32_t)
 * @param E Number of bits
 * @param Q_m Modulation order (2=QPSK, 4=16QAM, 6=64QAM, 8=256QAM)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t rate_matcher_interleave(rate_matcher_handle_t handle,
                                         const uint32_t*       d_input,
                                         uint32_t*             d_output,
                                         int                   E,
                                         int                   Q_m,
                                         cudaStream_t          stream);

/**
 * @brief Bit de-interleaving for RX path (LLR domain)
 *
 * De-interleaves LLRs to reverse TX interleaving.
 *
 * @param handle Rate matcher handle
 * @param d_input_llrs Input LLRs
 * @param d_output_llrs Output de-interleaved LLRs
 * @param E Number of LLRs
 * @param Q_m Modulation order
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t rate_matcher_deinterleave_llr(rate_matcher_handle_t handle,
                                               const float*          d_input_llrs,
                                               float*                d_output_llrs,
                                               int                   E,
                                               int                   Q_m,
                                               cudaStream_t          stream);

/**
 * @brief Batch bit interleaving for multiple code blocks
 *
 * @param handle Rate matcher handle
 * @param d_input Input bits for all CBs (packed, CB-contiguous)
 * @param d_output Output interleaved bits
 * @param E Bits per code block
 * @param Q_m Modulation order
 * @param num_cbs Number of code blocks
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t rate_matcher_interleave_batch(rate_matcher_handle_t handle,
                                               const uint32_t*       d_input,
                                               uint32_t*             d_output,
                                               int                   E,
                                               int                   Q_m,
                                               int                   num_cbs,
                                               cudaStream_t          stream);

/**
 * @brief Batch bit de-interleaving for multiple code blocks
 *
 * @param handle Rate matcher handle
 * @param d_input_llrs Input LLRs for all CBs
 * @param d_output_llrs Output de-interleaved LLRs
 * @param E LLRs per code block
 * @param Q_m Modulation order
 * @param num_cbs Number of code blocks
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t rate_matcher_deinterleave_llr_batch(rate_matcher_handle_t handle,
                                                     const float*          d_input_llrs,
                                                     float*                d_output_llrs,
                                                     int                   E,
                                                     int                   Q_m,
                                                     int                   num_cbs,
                                                     cudaStream_t          stream);

// ============================================================================
// Batch De-rate Matching Functions
// ============================================================================

/**
 * @brief Perform batch de-rate matching for multiple code blocks (uniform E, F)
 *
 * Processes multiple codeblocks in a single kernel launch. All CBs must have
 * the same rate-matched length E and filler bits F (which is common for most
 * CBs in a transport block).
 *
 * @param handle Rate matcher handle (configured with configure_rx)
 * @param d_received_llrs Device pointer to received LLRs for all CBs (contiguous, E * num_cbs floats)
 * @param d_output_llrs Device pointer to output LLRs for all CBs (contiguous, N_full * num_cbs floats)
 * @param num_cbs Number of code blocks to process
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t rate_matcher_dematch_batch(rate_matcher_handle_t handle,
                                            const float*          d_received_llrs,
                                            float*                d_output_llrs,
                                            int                   num_cbs,
                                            cudaStream_t          stream);

/**
 * @brief Perform batch de-rate matching with half-precision (fp16) LLRs
 *
 * Same as rate_matcher_dematch_batch but for __half LLRs.
 * Use for end-to-end fp16 GPU pipelines.
 *
 * @param handle Rate matcher handle (configured with configure_rx)
 * @param d_received_llrs_half Device pointer to received fp16 LLRs (__half*)
 * @param d_output_llrs_half Device pointer to output fp16 LLRs (__half*)
 * @param num_cbs Number of code blocks to process
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t rate_matcher_dematch_batch_half(rate_matcher_handle_t handle,
                                                 const void*           d_received_llrs_half,
                                                 void*                 d_output_llrs_half,
                                                 int                   num_cbs,
                                                 cudaStream_t          stream);

/**
 * @brief Fused deinterleave + de-rate matching for half-precision LLRs
 *
 * Combines TS 38.212 Section 5.4.2.2 bit deinterleaving and de-rate matching
 * into a single kernel, eliminating the intermediate deinterleaved buffer and
 * reducing memory bandwidth by ~2x compared to separate operations.
 *
 * When d_scramble_sequence is non-NULL, descrambling is fused into the same
 * kernel (sign flip based on scrambling bit), eliminating a separate descramble
 * kernel launch and an extra read+write pass over the input LLR buffer.
 *
 * @param handle Rate matcher handle (configured with configure_rx)
 * @param d_received_llrs_half Device pointer to interleaved FP16 LLRs (__half*)
 * @param d_output_llrs_half Device pointer to output FP16 LLRs (__half*)
 * @param Q_m Modulation order (2=QPSK, 4=16QAM, 6=64QAM, 8=256QAM)
 * @param num_cbs Number of code blocks to process
 * @param stream CUDA stream
 * @param d_scramble_sequence Packed scrambling sequence (NULL = input already descrambled)
 * @param scramble_offset Bit offset into the scrambling sequence
 * @return Status code
 */
nr_ldpc_status_t rate_matcher_deinterleave_and_dematch_batch_half(rate_matcher_handle_t handle,
                                                                  const void*           d_received_llrs_half,
                                                                  void*                 d_output_llrs_half,
                                                                  int                   Q_m,
                                                                  int                   num_cbs,
                                                                  cudaStream_t          stream,
                                                                  const unsigned int*   d_scramble_sequence,
                                                                  int                   scramble_offset);

/**
 * @brief Get full codeword LLR buffer size (N_full = N_cols * Z)
 * @param handle Rate matcher handle
 * @return N_full (full codeword size including punctured bits)
 */
int rate_matcher_get_full_size(rate_matcher_handle_t handle);

#ifdef __cplusplus
}
#endif
