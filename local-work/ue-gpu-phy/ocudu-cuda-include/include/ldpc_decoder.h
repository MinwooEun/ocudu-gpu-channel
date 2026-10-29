// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/**
 * @file ldpc_decoder.h
 * @brief 5G NR LDPC Decoder Interface
 *
 * CUDA-accelerated LDPC decoder using min-sum algorithm for 5G NR.
 * This is the optimized decoder with half-precision, codeword pairing,
 * and early termination for maximum throughput.
 */

#pragma once

#include "nr_ldpc_defs.h"
#include <cuda_runtime.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief LDPC Decoder handle (opaque)
 */
typedef struct ldpc_decoder_ctx* ldpc_decoder_handle_t;

/**
 * @brief CRC type for early termination
 *
 * 5G NR uses different CRCs depending on transport block size and segmentation:
 * - CRC16:  Single-CB, TB <= 3824 bits
 * - CRC24A: Single-CB, TB > 3824 bits
 * - CRC24B: Multi-CB (always attached to each code block)
 */
typedef enum {
  LDPC_CRC_NONE = 0, // No CRC check (confidence-only termination)
  LDPC_CRC_16   = 1, // CRC16 for single-CB small TB
  LDPC_CRC_24A  = 2, // CRC24A for single-CB large TB
  LDPC_CRC_24B  = 3  // CRC24B for multi-CB (default)
} ldpc_crc_type_t;

/**
 * @brief Decoder configuration
 */
typedef struct {
  int   max_iterations;           // Maximum number of decoder iterations (default: 10)
  float min_sum_scale;            // Min-sum normalization factor (default: 0.75, ignored if auto_scale=true)
  float min_sum_offset;           // Min-sum offset (default: 0, set >0 for offset min-sum)
  float llr_clamp;                // LLR clipping value (default: 32.0)
  bool  early_termination;        // Enable early termination on parity check (default: true)
  bool  output_soft;              // Output soft decisions (LLRs) instead of hard
  bool  auto_scale;               // Use rate-adaptive scaling per cuPHY tables (default: true)
  bool  skip_iteration_stats;     // DEPRECATED: use deferred_iteration_stats instead
  bool  deferred_iteration_stats; // Enable async iteration tracking without blocking decode (default: false)
  int   syndrome_tolerance;       // Number of failing parity rows to tolerate for early termination (default: 0)
                                  // When > 0, allows early exit when <= tolerance rows fail parity check.
                                  // Useful for FP16 decoder where parity columns may not fully converge
                                  // even when information bits are correct (CRC will still validate).
  bool crc_early_termination;     // Enable CRC-based early termination (default: true)
                                  // When enabled, uses hybrid confidence + CRC check:
                                  // 1. Fast confidence check (|APP| > threshold) on info bits
                                  // 2. If confident, compute CRC to verify correctness
                                  // 3. Terminate early only if CRC passes
                                  // This matches CPU decoder behavior and achieves Iter=1-2 at high SNR.
  ldpc_crc_type_t crc_type;       // CRC type to check (default: LDPC_CRC_24B)
                                  // LDPC_CRC_NONE: Confidence-only (no CRC check)
                                  // LDPC_CRC_16:   Single-CB, TB <= 3824 bits
                                  // LDPC_CRC_24A:  Single-CB, TB > 3824 bits
                                  // LDPC_CRC_24B:  Multi-CB (CRC24B per code block)
  float confidence_threshold;     // Confidence threshold for CRC early termination (default: 0.25)
                                  // Lower values trigger more CRC checks but catch convergence earlier.
                                  // 0.25-0.5 recommended for FP16 decoder.
  bool use_boxplus;               // Use box-plus algorithm instead of min-sum (default: false)
                                  // Box-plus: single-pass with prefix products (faster, more stable)
                                  // Min-sum: two-pass with min finding (standard, well-tested)
                                  // Box-plus can be 10-15% faster but needs BLER validation.
} ldpc_decoder_params_t;

/**
 * @brief Initialize default decoder parameters
 * @param params Output parameter structure
 */
void ldpc_decoder_params_init(ldpc_decoder_params_t* params);

// ============================================================================
// LDPC Decoder API (Optimized: half-precision, codeword pairing, early termination)
// ============================================================================

/**
 * @brief Create LDPC decoder context
 * Uses half-precision, codeword pairing, and early termination for maximum throughput
 */
nr_ldpc_status_t ldpc_decoder_create(ldpc_decoder_handle_t* handle);

/**
 * @brief Configure LDPC decoder
 */
nr_ldpc_status_t
ldpc_decoder_configure(ldpc_decoder_handle_t handle, const nr_ldpc_config_t* cfg, const ldpc_decoder_params_t* params);

/**
 * @brief Decode single codeword
 */
nr_ldpc_status_t
ldpc_decoder_decode(ldpc_decoder_handle_t handle, const float* d_llr_input, uint32_t* d_output, cudaStream_t stream);

/**
 * @brief Decode batch of codewords with codeword pairing
 */
nr_ldpc_status_t ldpc_decoder_decode_batch(ldpc_decoder_handle_t handle,
                                           const float*          d_llr_input,
                                           uint32_t*             d_output,
                                           int                   num_codewords,
                                           cudaStream_t          stream);

/**
 * @brief Decode batch of codewords with half-precision (fp16) input
 *
 * Same as ldpc_decoder_decode_batch but accepts __half LLRs directly,
 * avoiding fp32->fp16 conversion overhead. Use this for end-to-end
 * GPU pipelines where upstream produces fp16 LLRs.
 */
nr_ldpc_status_t ldpc_decoder_decode_batch_half(ldpc_decoder_handle_t handle,
                                                const void*           d_llr_input_half,
                                                uint32_t*             d_output,
                                                int                   num_codewords,
                                                cudaStream_t          stream,
                                                int                   workspace_buffer_index = -1);

/**
 * @brief Decode BG1/Z384 codeblocks directly from rate-matched fp16 LLRs.
 *
 * This latency path fuses deinterleave, descrambling, de-rate matching and
 * LDPC APP initialization for no-repetition PUSCH codeblocks. It is intended
 * for wideband high-MCS PUSCH where E <= Ncb - F for every codeblock.
 */
/**
 * @brief Optional fused TB output for the direct decode path (OCUDU_LDPC_FUSED_TB).
 *
 * When provided (and the env knob allows it), the direct decode kernel writes each
 * codeblock's info bits straight into the TB byte stream, replacing the desegment
 * pass. The caller must then run the TB CRC itself (e.g. tb_check_crc24a_async) on
 * the same stream. Requirements enforced by the decoder: byte-aligned cb_info_bits
 * and tb_bits.
 */
typedef struct {
  uint8_t* d_tb_output;  // Device TB byte stream (payload + TB CRC bytes)
  int      tb_bits;      // Total TB bits including TB CRC (byte-aligned)
  int      cb_info_bits; // Info bits contributed per CB (byte-aligned)
} ldpc_fused_tb_output_t;

nr_ldpc_status_t ldpc_decoder_decode_batch_half_from_rate_matched(ldpc_decoder_handle_t handle,
                                                                  const void*           d_rate_matched_llrs_half,
                                                                  uint32_t*             d_output,
                                                                  int                   num_codewords,
                                                                  int                   Q_m,
                                                                  int                   N_cb,
                                                                  int                   k0,
                                                                  const int*            d_rm_lengths,
                                                                  const unsigned int*   d_rm_offsets,
                                                                  const unsigned int*   d_scramble_sequence,
                                                                  int                   scramble_offset,
                                                                  cudaStream_t          stream,
                                                                  int                   workspace_buffer_index = -1,
                                                                  const ldpc_fused_tb_output_t* fused_tb = nullptr,
                                                                  bool* fused_tb_engaged                 = nullptr);

/**
 * @brief Pre-allocate workspace for CUDA graph compatibility
 *
 * Ensures internal buffers are allocated for up to max_batch_size codewords.
 * Call this before CUDA graph capture to prevent allocations during capture.
 * The decoder must be configured before calling this function.
 *
 * @param handle Decoder handle
 * @param max_batch_size Maximum batch size to support
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t ldpc_decoder_preallocate_workspace(ldpc_decoder_handle_t handle, int max_batch_size);

/**
 * @brief Destroy decoder
 */
void ldpc_decoder_destroy(ldpc_decoder_handle_t handle);

/**
 * @brief Get output words for decoder
 */
int ldpc_decoder_get_output_words(ldpc_decoder_handle_t handle);

/**
 * @brief Get average iterations from the last decode operation
 *
 * Returns the average number of LDPC decoder iterations across all codewords
 * from the most recent decode call. Useful for monitoring early termination
 * effectiveness and SNR estimation.
 *
 * When deferred_iteration_stats is enabled, this function will block until
 * the async D2H copy completes (syncs on internal event). For non-blocking
 * behavior, use ldpc_decoder_get_avg_iterations_async() instead.
 *
 * @param handle Decoder handle
 * @return Average iterations (0.0 if no decode has been performed or stats disabled)
 */
float ldpc_decoder_get_avg_iterations(ldpc_decoder_handle_t handle);

/**
 * @brief Check if deferred iteration stats are ready (non-blocking)
 *
 * When deferred_iteration_stats is enabled, this checks if the async D2H
 * copy has completed without blocking.
 *
 * @param handle Decoder handle
 * @return true if stats are ready to read, false if still pending
 */
bool ldpc_decoder_iteration_stats_ready(ldpc_decoder_handle_t handle);

/**
 * @brief Enqueue the postponed iteration-stats D2H copy (OCUDU_LDPC_STATS_AFTER_DESEG).
 *
 * When OCUDU_LDPC_STATS_AFTER_DESEG=1 and deferred_iteration_stats is enabled, decode
 * calls postpone the iteration-stats D2H so the caller can enqueue TB desegmentation/CRC
 * immediately after the decode kernel (avoids a costly kernel→D2H→kernel stream boundary).
 * The caller must invoke this after enqueueing the deseg work; it is a no-op otherwise.
 *
 * @param handle Decoder handle
 * @param stream Stream to enqueue the copy on (must order after the decode kernel)
 */
nr_ldpc_status_t ldpc_decoder_flush_iteration_stats(ldpc_decoder_handle_t handle, cudaStream_t stream);

/**
 * @brief Get average iterations without blocking (async-safe)
 *
 * Returns the average iteration count if available, or the cached value
 * from the previous decode if stats are still pending.
 *
 * @param handle Decoder handle
 * @param ready Output: set to true if returned value is from current decode
 * @return Average iterations (cached value if not ready)
 */
float ldpc_decoder_get_avg_iterations_async(ldpc_decoder_handle_t handle, bool* ready);

// ============================================================================
// CRC Results Access API
// ============================================================================

/**
 * @brief Check if decoder has CRC results available
 *
 * Returns true if the decoder has CRC results buffers allocated and CRC early
 * termination is enabled. When true, CRC results from the LDPC kernel can be
 * reused instead of computing CRC separately.
 *
 * @param handle Decoder handle
 * @return true if CRC results are available
 */
bool ldpc_decoder_has_crc_results(ldpc_decoder_handle_t handle);

/**
 * @brief Get pointer to device CRC results buffer
 *
 * Returns a pointer to the device buffer containing CRC results from the last
 * decode operation. CRC value is 0 if passed, non-zero if failed.
 *
 * @param handle Decoder handle
 * @return Device pointer to CRC results, or NULL if not available
 */
int* ldpc_decoder_get_crc_results_ptr(ldpc_decoder_handle_t handle);

/**
 * @brief Get CRC results on host
 *
 * Copies CRC results from device to host and returns pointer to host buffer.
 * This function blocks until the copy completes.
 *
 * @param handle Decoder handle
 * @param num_cbs Number of codeblocks to copy
 * @param stream CUDA stream for the copy
 * @return Host pointer to CRC results, or NULL if not available
 */
const int* ldpc_decoder_get_crc_results_host(ldpc_decoder_handle_t handle, int num_cbs, cudaStream_t stream);

/**
 * @brief Reverse bits within each byte of LDPC decoder output (GPU kernel).
 *
 * Converts from LSB-first-per-byte (GPU kernel output format) to
 * MSB-first-per-byte (3GPP bit_buffer format). This eliminates the
 * CPU-side extract_decoded_bits() bit reversal loop.
 *
 * @param handle Decoder handle (used to determine output stride)
 * @param d_output Device pointer to packed output bits (modified in-place)
 * @param nof_cbs Number of codeblocks
 * @param stream CUDA stream for the kernel
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t
ldpc_decoder_reformat_output_bits(ldpc_decoder_handle_t handle, uint32_t* d_output, int nof_cbs, cudaStream_t stream);

/**
 * @brief Get the output stride (words per codeblock) for the current decoder config.
 *
 * @param handle Decoder handle
 * @return Number of uint32_t words per codeblock output, or 0 if handle is invalid
 */
int ldpc_decoder_get_output_words(ldpc_decoder_handle_t handle);

#ifdef __cplusplus
}
#endif
