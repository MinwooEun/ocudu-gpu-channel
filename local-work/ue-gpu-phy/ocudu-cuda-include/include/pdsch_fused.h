// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/**
 * @file pdsch_fused.h
 * @brief Fused PDSCH TX kernels for maximum efficiency
 *
 * Combines scrambling + modulation into single kernel launches to eliminate
 * intermediate memory writes and kernel overhead.
 *
 * Performance gains:
 * - Eliminates 1 kernel launch (scramble + modulate → 1 fused kernel)
 * - Eliminates intermediate scrambled bits buffer
 * - Direct FP16 output reduces memory bandwidth by 50%
 */

#pragma once

#include <cuda_runtime.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Fused scrambling + modulation with FP16 output
 *
 * Single kernel that performs:
 * 1. XOR input bits with scrambling sequence
 * 2. Modulate to constellation points
 * 3. Output as FP16 complex (__half2)
 *
 * @param d_bits Input rate-matched bits (packed uint32)
 * @param d_scramble_seq Scrambling sequence (packed uint32)
 * @param d_symbols_half Output FP16 complex symbols (__half2*)
 * @param num_bits Number of input bits
 * @param mod_order Modulation order (2=QPSK, 4=16QAM, 6=64QAM, 8=256QAM)
 * @param stream CUDA stream
 * @return 0 on success
 */
int pdsch_fused_scramble_modulate_half(const uint32_t* d_bits,
                                       const uint32_t* d_scramble_seq,
                                       void*           d_symbols_half,
                                       int             num_bits,
                                       int             mod_order,
                                       cudaStream_t    stream);

/**
 * @brief Fused scrambling + modulation with FP32 output
 *
 * Same as pdsch_fused_scramble_modulate_half but with FP32 complex output.
 *
 * @param d_bits Input rate-matched bits (packed uint32)
 * @param d_scramble_seq Scrambling sequence (packed uint32)
 * @param d_symbols Output FP32 complex symbols (cuFloatComplex)
 * @param num_bits Number of input bits
 * @param mod_order Modulation order
 * @param stream CUDA stream
 * @return 0 on success
 */
int pdsch_fused_scramble_modulate(const uint32_t* d_bits,
                                  const uint32_t* d_scramble_seq,
                                  void*           d_symbols,
                                  int             num_bits,
                                  int             mod_order,
                                  cudaStream_t    stream);

/**
 * @brief Configuration for fused LDPC→Symbol TX pipeline
 */
typedef struct {
  int N_cb;            ///< Circular buffer size
  int N_full;          ///< Full codeword size
  int k0;              ///< Starting position in circular buffer
  int Kd;              ///< Payload bits in CB coordinates
  int F;               ///< Filler bits
  int puncture_offset; ///< Offset for punctured bits (2*Z)
  int encoded_stride;  ///< Words per CB in encoded buffer
  int nof_short;       ///< Number of short CBs
  int E_short;         ///< Bits per short CB
  int E_long;          ///< Bits per long CB
  int num_cbs;         ///< Number of code blocks
  int mod_order;       ///< Modulation order (2, 4, 6, 8)
  int total_symbols;   ///< Total output symbols
} pdsch_fused_tx_config_t;

/**
 * @brief Fused LDPC encoded → Rate Match → Interleave → Scramble → INT8 Symbols
 *
 * Maximum efficiency TX path that combines 4 operations into 1 kernel:
 * 1. Rate matching (circular buffer selection with filler skipping)
 * 2. Bit interleaving (per 3GPP TS 38.212)
 * 3. Scrambling (on-the-fly Gold sequence via LFSR)
 * 4. Modulation to INT8 constellation points
 *
 * Eliminates:
 * - Rate-matched bits buffer (~3KB per CB)
 * - Packed bytes buffer (~3KB per CB)
 * - 2-3 kernel launches
 * - Separate gold_sequence_generate_kernel (scrambling generated on-the-fly)
 *
 * @param d_encoded LDPC encoded bits (from ldpc_encoder)
 * @param c_init Scrambling sequence c_init (from scrambler_get_c_init)
 * @param d_symbols_int8 Output INT8 symbols (2 bytes per symbol)
 * @param cfg Configuration parameters
 * @param stream CUDA stream
 * @return 0 on success, -1 on error
 */
int pdsch_fused_encode_to_symbols_int8(const uint32_t*                d_encoded,
                                       uint32_t                       c_init,
                                       int8_t*                        d_symbols_int8,
                                       const pdsch_fused_tx_config_t* cfg,
                                       cudaStream_t                   stream);

/**
 * @brief Fused LDPC encoded → Rate Match → Interleave → Scramble → INT8 Symbols
 *
 * Same pipeline as pdsch_fused_encode_to_symbols_int8(), but consumes a
 * precomputed packed Gold sequence. This avoids per-symbol LFSR jumps in the
 * hot fused kernel and lets callers reuse cached scrambler sequences.
 *
 * @param d_encoded LDPC encoded bits (from ldpc_encoder)
 * @param d_scramble_seq Packed Gold sequence, MSB-first within each uint32_t
 * @param d_symbols_int8 Output INT8 symbols (2 bytes per symbol)
 * @param cfg Configuration parameters
 * @param stream CUDA stream
 * @return 0 on success, -1 on error
 */
int pdsch_fused_encode_to_symbols_int8_precomputed(const uint32_t*                d_encoded,
                                                   const uint32_t*                d_scramble_seq,
                                                   int8_t*                        d_symbols_int8,
                                                   const pdsch_fused_tx_config_t* cfg,
                                                   cudaStream_t                   stream);

/**
 * @brief Fused LDPC encoded → Rate Match → Interleave → Scramble → BF16 resource grid.
 *
 * This device-grid variant maps a contiguous slice of the PDSCH symbol stream
 * directly into real resource-grid coordinates, avoiding the intermediate INT8
 * symbol buffer and the separate INT8-to-BF16 grid-mapper launch.
 *
 * The RE offset list contains one offset per allocated RE within a single port.
 * For one layer, each RE is replicated to all ports. For diagonal multi-layer
 * mapping, nof_layers must equal nof_ports and layer i maps to port i.
 *
 * @param d_encoded LDPC encoded bits
 * @param d_scramble_seq Packed Gold sequence, MSB-first within each uint32_t
 * @param d_re_offsets Linear RE offsets within one output port grid
 * @param d_grid_bf16 Output BF16 IQ grid, two uint16_t words per RE
 * @param cfg Configuration parameters
 * @param symbol_offset First modulation symbol of this mapped slice
 * @param nof_re Number of REs in the slice
 * @param nof_ports Number of output ports
 * @param nof_layers Number of input layers
 * @param nof_grid_re_per_port Number of REs in one full port grid
 * @param weight_real Real precoding weight applied to mapped symbols
 * @param stream CUDA stream
 * @return 0 on success, -1 on error
 */
int pdsch_fused_encode_to_bf16_grid_precomputed(const uint32_t*                d_encoded,
                                                const uint32_t*                d_scramble_seq,
                                                const uint32_t*                d_re_offsets,
                                                uint16_t*                      d_grid_bf16,
                                                const pdsch_fused_tx_config_t* cfg,
                                                int                            symbol_offset,
                                                int                            nof_re,
                                                int                            nof_ports,
                                                int                            nof_layers,
                                                int                            nof_grid_re_per_port,
                                                float                          weight_real,
                                                cudaStream_t                   stream);

/**
 * @brief Batched variant of pdsch_fused_encode_to_symbols_int8_precomputed().
 *
 * Processes multiple homogeneous TBs in one launch. The scrambling sequence is
 * restarted for every TB, so all TBs must use the same PDSCH scrambling
 * parameters.
 *
 * @param d_encoded LDPC encoded bits for num_tbs contiguous TBs
 * @param d_scramble_seq Packed Gold sequence for one TB
 * @param d_symbols_int8 Output INT8 symbols for num_tbs contiguous TBs
 * @param cfg Per-TB configuration parameters
 * @param num_tbs Number of homogeneous TBs in the batch
 * @param stream CUDA stream
 * @return 0 on success, -1 on error
 */
int pdsch_fused_encode_to_symbols_int8_precomputed_batch(const uint32_t*                d_encoded,
                                                         const uint32_t*                d_scramble_seq,
                                                         int8_t*                        d_symbols_int8,
                                                         const pdsch_fused_tx_config_t* cfg,
                                                         int                            num_tbs,
                                                         cudaStream_t                   stream);

/**
 * @brief Rate-Matched → Interleave → Scramble → INT8 Symbols (No RM in kernel)
 *
 * Used with fused encoder + rate matcher. Takes pre-rate-matched bits and
 * performs only interleaving, scrambling, and modulation.
 *
 * @param d_rate_matched Rate-matched bits (from fused encoder)
 * @param c_init Scrambling sequence c_init (from scrambler_get_c_init)
 * @param d_symbols_int8 Output INT8 symbols
 * @param rm_stride Words per CB in rate-matched buffer
 * @param nof_short Number of short CBs
 * @param E_short Bits per short CB
 * @param E_long Bits per long CB
 * @param mod_order Modulation order (2, 4, 6, 8)
 * @param total_symbols Total output symbols
 * @param stream CUDA stream
 * @return 0 on success
 */
int pdsch_fused_from_rate_matched_to_symbols_int8(const uint32_t* d_rate_matched,
                                                  uint32_t        c_init,
                                                  int8_t*         d_symbols_int8,
                                                  int             rm_stride,
                                                  int             nof_short,
                                                  int             E_short,
                                                  int             E_long,
                                                  int             mod_order,
                                                  int             total_symbols,
                                                  cudaStream_t    stream);

#ifdef __cplusplus
}
#endif
