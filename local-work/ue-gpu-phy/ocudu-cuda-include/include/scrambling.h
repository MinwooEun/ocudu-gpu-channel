// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/**
 * @file scrambling.h
 * @brief 5G NR Scrambling per 3GPP TS 38.211 Section 7.3.1
 *
 * Implements Gold sequence generation and bit scrambling/descrambling
 * for PDSCH/PUSCH data channels.
 */

#pragma once

#include "nr_ldpc_defs.h"
#include <cuda_runtime.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Scrambling configuration per 3GPP TS 38.211
 *
 * c_init = n_RNTI * 2^15 + q * 2^14 + n_s * 2^4 + n_ID
 */
typedef struct {
  uint16_t n_RNTI; /**< Radio Network Temporary Identifier (0-65535) */
  uint16_t n_ID;   /**< Scrambling identity (0-1023 for dataScramblingIdentity,
                        or 0-1007 for physical cell ID) */
  uint8_t q;       /**< Codeword index (0 or 1) */
  uint8_t n_s;     /**< Slot number within radio frame (0-19 for FDD 15kHz, 0-9 for 30kHz) */
} nr_scrambling_config_t;

/**
 * @brief Scrambler handle (opaque)
 */
typedef struct scrambler_ctx* scrambler_handle_t;

// ============================================================================
// Scrambler API
// ============================================================================

/**
 * @brief Create scrambler context
 * @param handle Pointer to receive scrambler handle
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t scrambler_create(scrambler_handle_t* handle);

/**
 * @brief Destroy scrambler context
 * @param handle Scrambler handle to destroy
 */
void scrambler_destroy(scrambler_handle_t handle);

/**
 * @brief Configure scrambler with RNTI and cell ID
 * @param handle Scrambler handle
 * @param cfg Scrambling configuration
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t scrambler_configure(scrambler_handle_t handle, const nr_scrambling_config_t* cfg);

/**
 * @brief Configure scrambler with direct c_init value
 *
 * This is used for DMRS where c_init is computed per 3GPP TS 38.211
 * Section 6.4.1.1.1.1 with a formula different from data scrambling.
 *
 * @param handle Scrambler handle
 * @param c_init Direct c_init value (up to 31 bits)
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t scrambler_configure_c_init(scrambler_handle_t handle, uint32_t c_init);

/**
 * @brief Generate scrambling sequence for given length
 *
 * Pre-generates the Gold sequence which can be reused for multiple
 * scramble/descramble operations with the same length.
 *
 * @param handle Scrambler handle
 * @param num_bits Number of bits in sequence
 * @param stream CUDA stream for async execution
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t scrambler_generate_sequence(scrambler_handle_t handle, int num_bits, cudaStream_t stream);

/**
 * @brief Generate scrambling sequence with offset
 *
 * Pre-generates the Gold sequence starting from a given bit offset.
 * This is equivalent to calling advance() followed by generate_sequence()
 * but more efficient as the sequence is generated directly at the offset.
 *
 * @param handle Scrambler handle
 * @param num_bits Number of bits in sequence to generate
 * @param offset Starting bit offset (bits to skip before generating)
 * @param stream CUDA stream for async execution
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t
scrambler_generate_sequence_with_offset(scrambler_handle_t handle, int num_bits, int offset, cudaStream_t stream);

/**
 * @brief Advance the scrambler state by N bits
 *
 * Sets the internal offset that will be applied to subsequent operations.
 * The offset is cumulative until reset by configure() or set_offset().
 *
 * @param handle Scrambler handle
 * @param count Number of bits to advance
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t scrambler_advance(scrambler_handle_t handle, int count);

/**
 * @brief Set the absolute bit offset for sequence generation
 *
 * Sets the offset from which sequence generation starts. Unlike advance(),
 * this sets an absolute offset rather than adding to the current offset.
 *
 * @param handle Scrambler handle
 * @param offset Absolute bit offset
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t scrambler_set_offset(scrambler_handle_t handle, int offset);

/**
 * @brief Get the current bit offset
 *
 * @param handle Scrambler handle
 * @return Current bit offset
 */
int scrambler_get_offset(scrambler_handle_t handle);

/**
 * @brief Scramble bits (TX path)
 *
 * Performs XOR of input bits with scrambling sequence.
 * output[i] = input[i] XOR sequence[i]
 *
 * @param handle Scrambler handle
 * @param d_input Input bits (packed uint32_t)
 * @param d_output Output bits (packed uint32_t), can be same as input
 * @param num_bits Number of bits to scramble
 * @param stream CUDA stream
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t scrambler_scramble(scrambler_handle_t handle,
                                    const uint32_t*    d_input,
                                    uint32_t*          d_output,
                                    int                num_bits,
                                    cudaStream_t       stream);

/**
 * @brief Scramble bits in-place (TX path convenience function)
 *
 * @param handle Scrambler handle
 * @param d_bits Bits to scramble in-place (packed uint32_t)
 * @param num_bits Number of bits
 * @param stream CUDA stream
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t
scrambler_scramble_inplace(scrambler_handle_t handle, uint32_t* d_bits, int num_bits, cudaStream_t stream);

/**
 * @brief Descramble soft LLRs (RX path)
 *
 * Flips sign of LLRs where scrambling sequence bit is 1.
 * output[i] = (sequence[i] == 1) ? -input[i] : input[i]
 *
 * @param handle Scrambler handle
 * @param d_input_llrs Input LLRs
 * @param d_output_llrs Output LLRs, can be same as input
 * @param num_bits Number of LLR values
 * @param stream CUDA stream
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t scrambler_descramble_llr(scrambler_handle_t handle,
                                          const float*       d_input_llrs,
                                          float*             d_output_llrs,
                                          int                num_bits,
                                          cudaStream_t       stream);

/**
 * @brief Descramble soft LLRs in-place (RX path convenience function)
 *
 * @param handle Scrambler handle
 * @param d_llrs LLRs to descramble in-place
 * @param num_bits Number of LLR values
 * @param stream CUDA stream
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t
scrambler_descramble_llr_inplace(scrambler_handle_t handle, float* d_llrs, int num_bits, cudaStream_t stream);

/**
 * @brief Descramble half-precision (fp16) LLRs in-place
 *
 * Same as scrambler_descramble_llr_inplace but for __half LLRs.
 * Flips sign bit directly in fp16 representation for maximum efficiency.
 *
 * @param handle Scrambler handle
 * @param d_llrs_half LLRs to descramble in-place (__half*)
 * @param num_bits Number of LLR values
 * @param stream CUDA stream
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t
scrambler_descramble_llr_half_inplace(scrambler_handle_t handle, void* d_llrs_half, int num_bits, cudaStream_t stream);

/**
 * @brief Get the c_init value for current configuration
 *
 * Useful for diagnostics and verification against reference implementations.
 *
 * @param handle Scrambler handle
 * @return c_init value (32-bit)
 */
uint32_t scrambler_get_c_init(scrambler_handle_t handle);

/**
 * @brief Pre-allocate sequence buffer for CUDA graph compatibility
 *
 * Ensures the internal sequence buffer is allocated for up to max_bits.
 * Call this before CUDA graph capture to prevent allocations during capture.
 *
 * @param handle Scrambler handle
 * @param max_bits Maximum number of bits to support
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t scrambler_preallocate_sequence(scrambler_handle_t handle, int max_bits);

/**
 * @brief Get device pointer to the scrambling sequence
 *
 * Returns a pointer to the packed uint32 scrambling sequence on GPU.
 * The sequence must have been generated with scrambler_generate_sequence()
 * before calling this function.
 *
 * @param handle Scrambler handle
 * @return Device pointer to packed scrambling sequence, or nullptr if not generated
 */
const unsigned int* scrambler_get_sequence_ptr(scrambler_handle_t handle);

#ifdef __cplusplus
}
#endif
