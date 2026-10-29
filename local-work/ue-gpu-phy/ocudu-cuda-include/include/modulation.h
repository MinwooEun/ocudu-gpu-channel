// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/**
 * @file modulation.h
 * @brief 5G NR Modulation and Soft Demodulation
 *
 * CUDA-accelerated modulation (BPSK, QPSK, 16QAM, 64QAM, 256QAM)
 * and soft demodulation with LLR computation.
 */

#pragma once

#include <cuComplex.h>
#include <cuda_runtime.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Modulation orders
typedef enum {
  MOD_BPSK   = 1, // 1 bit/symbol
  MOD_QPSK   = 2, // 2 bits/symbol
  MOD_16QAM  = 4, // 4 bits/symbol
  MOD_64QAM  = 6, // 6 bits/symbol
  MOD_256QAM = 8  // 8 bits/symbol
} modulation_order_t;

// Modulator handle
typedef struct modulator_ctx* modulator_handle_t;

/**
 * @brief Create a modulator instance
 */
int modulator_create(modulator_handle_t* handle);

/**
 * @brief Destroy a modulator instance
 */
void modulator_destroy(modulator_handle_t handle);

/**
 * @brief Modulate bits to complex symbols
 *
 * Input format: MSB-first packed bytes (as output by TB encoder after bit interleaving).
 * This matches the 5G NR specification where bit 0 is at the MSB of byte 0.
 *
 * For QPSK: 4 symbols per byte, symbol 0 from bits [7:6], symbol 1 from bits [5:4], etc.
 * For 16QAM: 2 symbols per byte, symbol 0 from high nibble, symbol 1 from low nibble.
 * For 64QAM: 4 symbols per 3 bytes (24 bits).
 * For 256QAM: 1 symbol per byte.
 *
 * NOTE: This does NOT work directly with LDPC encoder output (LSB-first uint32_t).
 * Use TB encoder chain or convert format before calling this function.
 *
 * @param handle Modulator handle
 * @param d_bits Input bits (MSB-first packed bytes, cast as uint32_t* for alignment)
 * @param d_symbols Output complex symbols
 * @param num_bits Number of input bits
 * @param mod_order Modulation order (bits per symbol)
 * @param stream CUDA stream
 * @return 0 on success
 */
int modulator_modulate(modulator_handle_t handle,
                       const uint32_t*    d_bits,
                       cuFloatComplex*    d_symbols,
                       int                num_bits,
                       int                mod_order,
                       cudaStream_t       stream);

/**
 * @brief Add AWGN noise to complex symbols
 *
 * @param handle Modulator handle
 * @param d_symbols Input/output symbols (in-place)
 * @param num_symbols Number of symbols
 * @param noise_std Standard deviation of noise (per dimension)
 * @param stream CUDA stream
 * @return 0 on success
 */
int modulator_add_noise(modulator_handle_t handle,
                        cuFloatComplex*    d_symbols,
                        int                num_symbols,
                        float              noise_std,
                        cudaStream_t       stream);

/**
 * @brief Soft demodulate symbols to LLRs (uniform noise variance)
 *
 * @param handle Modulator handle
 * @param d_symbols Input noisy symbols
 * @param d_llrs Output LLRs (one per bit)
 * @param num_symbols Number of input symbols
 * @param mod_order Modulation order (bits per symbol)
 * @param noise_var Noise variance (sigma^2) - same for all symbols
 * @param stream CUDA stream
 * @return 0 on success
 */
int modulator_soft_demod(modulator_handle_t    handle,
                         const cuFloatComplex* d_symbols,
                         float*                d_llrs,
                         int                   num_symbols,
                         int                   mod_order,
                         float                 noise_var,
                         cudaStream_t          stream);

/**
 * @brief Soft demodulate symbols to LLRs with per-symbol noise variance
 *
 * This version supports different noise variance for each symbol, which is
 * essential for proper LLR computation after MMSE equalization where the
 * effective noise varies per subcarrier/symbol.
 *
 * @param handle Modulator handle
 * @param d_symbols Input noisy symbols (device pointer)
 * @param d_noise_vars Per-symbol noise variances (device pointer, one per symbol)
 * @param d_llrs Output LLRs (one per bit)
 * @param num_symbols Number of input symbols
 * @param mod_order Modulation order (bits per symbol)
 * @param stream CUDA stream
 * @return 0 on success
 */
int modulator_soft_demod_per_symbol(modulator_handle_t    handle,
                                    const cuFloatComplex* d_symbols,
                                    const float*          d_noise_vars,
                                    float*                d_llrs,
                                    int                   num_symbols,
                                    int                   mod_order,
                                    cudaStream_t          stream);

/**
 * @brief Soft demodulate to half-precision (fp16) LLRs with per-symbol noise variance
 *
 * Same as modulator_soft_demod_per_symbol but outputs __half LLRs directly.
 * Use for end-to-end fp16 GPU pipelines to avoid fp32->fp16 conversion
 * in downstream operations (scrambling, rate matching, LDPC decoding).
 *
 * @param handle Modulator handle
 * @param d_symbols Input noisy symbols (device pointer, cuFloatComplex)
 * @param d_noise_vars Per-symbol noise variances (device pointer, float)
 * @param d_llrs_half Output half-precision LLRs (__half*, one per bit)
 * @param num_symbols Number of input symbols
 * @param mod_order Modulation order (bits per symbol)
 * @param stream CUDA stream
 * @return 0 on success
 */
int modulator_soft_demod_per_symbol_half(modulator_handle_t    handle,
                                         const cuFloatComplex* d_symbols,
                                         const float*          d_noise_vars,
                                         void*                 d_llrs_half,
                                         int                   num_symbols,
                                         int                   mod_order,
                                         cudaStream_t          stream);

/**
 * @brief Modulate bits to INT8 complex symbols (ci8_t format)
 *
 * Direct modulation to INT8 output, eliminating intermediate FP32 buffer.
 * Output format: 2 bytes per symbol (int8_t real, int8_t imag).
 * Uses unnormalized constellation points (±1, ±3, ±5, ±7 for 64QAM).
 *
 * This is the most efficient path for TX when downstream uses ci8_t:
 * rate-matched bits → modulate → INT8 symbols (no FP32 intermediate).
 *
 * @param handle Modulator handle
 * @param d_bits Input bits (packed uint32_t)
 * @param d_symbols_int8 Output INT8 complex symbols (int8_t*, 2 bytes/symbol)
 * @param num_bits Number of input bits
 * @param mod_order Modulation order (2=QPSK, 4=16QAM, 6=64QAM, 8=256QAM)
 * @param stream CUDA stream
 * @return 0 on success
 */
int modulator_modulate_int8(modulator_handle_t handle,
                            const uint32_t*    d_bits,
                            int8_t*            d_symbols_int8,
                            int                num_bits,
                            int                mod_order,
                            cudaStream_t       stream);

/**
 * @brief Fused scrambling + modulation (single kernel for TX path)
 *
 * Combines scrambling and modulation in a single kernel to eliminate
 * intermediate memory traffic. This is the fastest path for TX:
 * rate-matched bits → fused scramble+modulate → complex symbols.
 *
 * @param handle Modulator handle
 * @param d_bits Input rate-matched bits (packed uint32_t, MSB-first)
 * @param d_scramble_seq Scrambling sequence (from scrambler_get_sequence_ptr)
 * @param d_symbols Output complex symbols
 * @param num_bits Number of bits to process
 * @param mod_order Modulation order (2=QPSK, 4=16QAM, 6=64QAM, 8=256QAM)
 * @param stream CUDA stream
 * @return 0 on success, -1 on error
 */
int modulator_scramble_and_modulate(modulator_handle_t handle,
                                    const uint32_t*    d_bits,
                                    const uint32_t*    d_scramble_seq,
                                    cuFloatComplex*    d_symbols,
                                    int                num_bits,
                                    int                mod_order,
                                    cudaStream_t       stream);

/**
 * @brief Fused scrambling + modulation with INT8 output
 *
 * Single kernel that performs:
 * 1. XOR input bits with scrambling sequence
 * 2. Modulate to INT8 constellation points (unnormalized)
 *
 * Output format: 2 bytes per symbol (int8_t real, int8_t imag).
 * Uses unnormalized constellation points (±1, ±3, ±5, ±7 for 64QAM).
 *
 * This eliminates the need for separate scrambling and FP32→INT8 conversion.
 *
 * @param handle Modulator handle
 * @param d_bits Input rate-matched bits (packed uint32)
 * @param d_scramble_seq Scrambling sequence (packed uint32)
 * @param d_symbols_int8 Output INT8 complex symbols (2 bytes per symbol)
 * @param num_bits Number of input bits
 * @param mod_order Modulation order (2=QPSK, 4=16QAM, 6=64QAM, 8=256QAM)
 * @param stream CUDA stream
 * @return 0 on success, -1 on error
 */
int modulator_scramble_and_modulate_int8(modulator_handle_t handle,
                                         const uint32_t*    d_bits,
                                         const uint32_t*    d_scramble_seq,
                                         int8_t*            d_symbols_int8,
                                         int                num_bits,
                                         int                mod_order,
                                         cudaStream_t       stream);

/**
 * @brief Batch fused scrambling + modulation (all CBs in single kernel)
 *
 * Processes all code blocks in a single kernel launch, eliminating
 * per-CB kernel launch overhead. Use for multi-CB transport blocks.
 *
 * @param handle Modulator handle
 * @param d_bits Input rate-matched bits for all CBs (packed uint32_t)
 * @param d_scramble_seq Scrambling sequence (global, not per-CB)
 * @param d_symbols Output complex symbols for all CBs
 * @param bits_per_cb Bits per code block
 * @param words_per_cb Words per CB in input buffer (stride)
 * @param num_cbs Number of code blocks
 * @param mod_order Modulation order (2=QPSK, 4=16QAM, 6=64QAM, 8=256QAM)
 * @param stream CUDA stream
 * @return 0 on success, -1 on error
 */
int modulator_scramble_and_modulate_batch(modulator_handle_t handle,
                                          const uint32_t*    d_bits,
                                          const uint32_t*    d_scramble_seq,
                                          cuFloatComplex*    d_symbols,
                                          int                bits_per_cb,
                                          int                words_per_cb,
                                          int                num_cbs,
                                          int                mod_order,
                                          cudaStream_t       stream);

/**
 * @brief Fused soft demodulation + descrambling to FP16 output.
 *
 * Used by the non-resident PUSCH GPU batch path. The production resident PUSCH
 * path uses the fused PUSCH E2E FP16 output kernels directly.
 */
int modulator_soft_demod_descramble_half(modulator_handle_t    handle,
                                         const cuFloatComplex* d_symbols,
                                         const float*          d_noise_vars,
                                         const uint32_t*       d_scramble_seq,
                                         void*                 d_llrs_half,
                                         int                   num_symbols,
                                         int                   mod_order,
                                         cudaStream_t          stream);

/**
 * @brief Get number of symbols for given bits and modulation
 */
int modulator_get_num_symbols(int num_bits, int mod_order);

/**
 * @brief Convert SNR (dB) to noise standard deviation
 *
 * @param snr_db SNR in dB (Eb/N0)
 * @param code_rate Code rate
 * @param mod_order Modulation order (bits per symbol)
 * @return Noise standard deviation per dimension
 */
float snr_to_noise_std(float snr_db, float code_rate, int mod_order);

// ============================================================================
// Non-fused kernels for verification
// ============================================================================

/**
 * @brief Soft demodulate symbols to FP32 LLRs WITHOUT descrambling
 *
 * Verification kernel for checking soft-demod correctness before descrambling is applied.
 * Output can be compared directly with CPU soft demod output (before descrambling).
 *
 * @param handle Modulator handle
 * @param d_symbols Input complex symbols
 * @param d_noise_vars Per-symbol noise variance
 * @param d_llrs Output FP32 LLRs (NOT descrambled)
 * @param num_symbols Number of symbols
 * @param mod_order Modulation order (2=QPSK, 4=16QAM, 6=64QAM, 8=256QAM)
 * @param stream CUDA stream
 * @return 0 on success, -1 on error
 */
int modulator_soft_demod_only_fp32(modulator_handle_t    handle,
                                   const cuFloatComplex* d_symbols,
                                   const float*          d_noise_vars,
                                   float*                d_llrs,
                                   int                   num_symbols,
                                   int                   mod_order,
                                   cudaStream_t          stream);

/**
 * @brief Apply descrambling to FP32 LLRs in-place
 *
 * Verification kernel for applying descrambling separately after soft demod.
 * Flips sign of LLR where scrambling bit is 1.
 *
 * @param handle Modulator handle
 * @param d_llrs Input/output FP32 LLRs (modified in-place)
 * @param d_scramble_seq Scrambling sequence (from scrambler_get_sequence_ptr)
 * @param num_bits Number of LLRs/bits
 * @param stream CUDA stream
 * @return 0 on success, -1 on error
 */
int modulator_descramble_llrs_fp32(modulator_handle_t handle,
                                   float*             d_llrs,
                                   const uint32_t*    d_scramble_seq,
                                   int                num_bits,
                                   cudaStream_t       stream);

#ifdef __cplusplus
}
#endif
