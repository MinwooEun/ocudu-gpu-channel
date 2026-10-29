// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/**
 * @file transport_block.h
 * @brief 5G NR Transport Block Processing Interface
 *
 * High-level interface for complete transport block encoding and decoding,
 * including CRC attachment, code block segmentation, LDPC coding, and rate matching.
 */

#pragma once

#include "ldpc_decoder.h"
#include "ldpc_encoder.h"
#include "nr_ldpc_defs.h"
#include "rate_matching.h"
#include <cuda_runtime.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Transport Block Encoder handle (opaque)
 */
typedef struct tb_encoder_ctx* tb_encoder_handle_t;

/**
 * @brief Transport Block Decoder handle (opaque)
 */
typedef struct tb_decoder_ctx* tb_decoder_handle_t;

/**
 * @brief TB Encoder configuration
 */
typedef struct {
  int   tb_size_bits;       // Transport block size A
  int   num_layers;         // Number of layers (for rate matching)
  int   modulation_order;   // Q_m (2,4,6,8)
  int   num_allocated_res;  // G - number of coded bits
  int   redundancy_version; // rv (0-3)
  float code_rate;          // Target code rate

  // Scrambling parameters (per 3GPP TS 38.211)
  uint16_t n_RNTI;            // Radio Network Temporary Identifier
  uint16_t n_ID;              // Scrambling identity (0-1023)
  uint8_t  q;                 // Codeword index (0 or 1)
  bool     enable_scrambling; // Enable scrambling (default: true for 5G NR)

  // LDPC parameters (from CPU segmenter for consistency)
  int base_graph;      // LDPC base graph (1 or 2, 0 = compute internally)
  int num_code_blocks; // Number of codeblocks C (0 = compute internally)
  int lifting_size;    // Z - LDPC lifting size (0 = compute internally)
  int nof_filler_bits; // F - Number of filler bits (0 = compute internally)

  // Rate matching parameters (from CPU segmenter for multi-CB consistency)
  int nof_short_segments; // Number of CBs with E_short (0 = compute internally)
  int E_short;            // Rate-matched bits for short CBs (0 = compute internally)
  int E_long;             // Rate-matched bits for long CBs (0 = compute internally)
} tb_encoder_config_t;

/**
 * @brief TB Decoder configuration
 */
typedef struct {
  int   tb_size_bits;       // Expected transport block size
  int   num_layers;         // Number of layers
  int   modulation_order;   // Q_m
  int   num_received_bits;  // E - number of received LLRs
  int   redundancy_version; // rv
  float code_rate;          // Code rate
  int   max_iterations;     // LDPC decoder iterations
  float llr_clamp;          // LLR clipping value

  // Scrambling parameters (must match encoder)
  uint16_t n_RNTI;            // Radio Network Temporary Identifier
  uint16_t n_ID;              // Scrambling identity (0-1023)
  uint8_t  q;                 // Codeword index (0 or 1)
  bool     enable_scrambling; // Enable descrambling (default: true for 5G NR)

  // Offset min-sum for high erasure ratio decoding (default: false)
  // Enable when using perfect LLRs with low code rates (>35% erasure columns)
  // Keep disabled for noisy channel reception
  bool use_offset_minsum;

  // Skip final sync for CRC result (default: false)
  // When true, tb_decode_result_t::crc_pass will be from PREVIOUS decode call.
  // Use for max throughput when pipelining multiple TBs.
  bool skip_crc_sync;
} tb_decoder_config_t;

/**
 * @brief TB decode result
 */
typedef struct {
  int   crc_pass;        // 1 if TB CRC passed, 0 otherwise
  int   num_cb_crc_pass; // Number of CBs with passing CRC
  int   num_code_blocks; // Total number of code blocks
  float avg_iterations;  // Average LDPC iterations
} tb_decode_result_t;

// ============================================================================
// Transport Block Encoder Functions
// ============================================================================

/**
 * @brief Create TB encoder context
 * @param handle Output encoder handle
 * @return Status code
 */
nr_ldpc_status_t tb_encoder_create(tb_encoder_handle_t* handle);

/**
 * @brief Destroy TB encoder context
 * @param handle Encoder handle
 */
void tb_encoder_destroy(tb_encoder_handle_t handle);

/**
 * @brief Configure TB encoder
 * @param handle Encoder handle
 * @param cfg TB encoder configuration
 * @return Status code
 */
nr_ldpc_status_t tb_encoder_configure(tb_encoder_handle_t handle, const tb_encoder_config_t* cfg);

/**
 * @brief Lock encoder into resident RT mode: subsequent configure never allocates.
 *
 * Call after startup warmup. Any configure that would need buffers larger than
 * the max preallocation made at create() fails with NR_LDPC_ERROR_INVALID_CONFIG
 * instead of cudaMalloc on the slot path.
 */
void tb_encoder_lock_rt(tb_encoder_handle_t handle);

/**
 * @brief Update only scrambling identity (n_RNTI / n_ID / q) on an already-configured encoder.
 *
 * Use when LDPC/RM/mod shape is unchanged (same TBS, Z, F, G, RV, layers, Qm) but the
 * grant RNTI or cell scrambling ID changed. Avoids destroy/recreate of graph caches,
 * LDPC reconfigure, and buffer realloc — the dominant cost of a full tb_encoder_configure
 * on the OTA RAR path (every RA-RNTI / C-RNTI).
 *
 * @param handle Encoder handle (must already be configured for the desired encode shape)
 * @param n_RNTI Radio Network Temporary Identifier
 * @param n_ID   Scrambling identity
 * @param q      Codeword index (0 or 1)
 * @return Status code
 */
nr_ldpc_status_t
tb_encoder_reconfigure_scrambling(tb_encoder_handle_t handle, uint16_t n_RNTI, uint16_t n_ID, uint8_t q);

/**
 * @brief Encode a transport block (complete chain)
 *
 * Performs: CRC attachment -> Segmentation -> LDPC encoding -> Rate matching
 *
 * @param handle Encoder handle
 * @param d_tb_input Device pointer to transport block bits (A bits as uint8_t)
 * @param d_output Device pointer to output (G rate-matched bits as uint8_t)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t
tb_encoder_encode(tb_encoder_handle_t handle, const uint8_t* d_tb_input, uint8_t* d_output, cudaStream_t stream);

/**
 * @brief Get TB encoder output size
 * @param handle Encoder handle
 * @return Output size in bits
 */
int tb_encoder_get_output_bits(tb_encoder_handle_t handle);

/**
 * @brief Get number of code blocks for current TB
 * @param handle Encoder handle
 * @return Number of code blocks
 */
int tb_encoder_get_num_code_blocks(tb_encoder_handle_t handle);

/**
 * @brief Get base graph (1 or 2) for current TB configuration
 * @param handle Encoder handle
 * @return Base graph (1 or 2)
 */
int tb_encoder_get_base_graph(tb_encoder_handle_t handle);

/**
 * @brief Get lifting size (Z) for current TB configuration
 * @param handle Encoder handle
 * @return Lifting size Z
 */
int tb_encoder_get_lifting_size(tb_encoder_handle_t handle);

/**
 * @brief Encode transport block to raw rate-matched bits (no modulation)
 *
 * Outputs the full rate-matched scrambled bit stream suitable for bit-level
 * BLER testing. This outputs sum(E_i) bits where E_i is the rate-matched
 * length of each code block.
 *
 * Pipeline: TB CRC → CB Seg → CB CRC → LDPC → Rate Match → Scramble → Bits
 *
 * @param handle Encoder handle
 * @param d_tb_input Device pointer to transport block bits (A bits as uint8_t)
 * @param d_output Device pointer to output bits (total_E_bits as uint8_t packed bytes)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t
tb_encoder_encode_bits(tb_encoder_handle_t handle, const uint8_t* d_tb_input, uint8_t* d_output, cudaStream_t stream);

/**
 * @brief Get total E bits (sum of all CB rate-matched lengths)
 * @param handle Encoder handle
 * @return Total E bits
 */
int tb_encoder_get_total_E_bits(tb_encoder_handle_t handle);

/**
 * @brief Encode transport block to UNPACKED bits (optional interleaving, NO byte packing)
 *
 * This is designed for bits-only interface for PyTorch training loops.
 * Outputs one uint8_t per bit (value 0 or 1), suitable for direct bit-level operations.
 *
 * Pipeline: TB CRC → CB Seg → CB CRC → LDPC → Rate Match → [Interleave] → Scramble → Unpacked bits
 *
 * Unlike tb_encoder_encode_bits() which outputs packed bytes,
 * this function outputs unpacked bits (with OPTIONAL QAM bit interleaving, but NO byte packing).
 * This matches the full TX chain (optional interleaving + scrambling) but provides unpacked bits output.
 *
 * @param handle Encoder handle
 * @param d_tb_input Device pointer to transport block bits (A bits as uint8_t, packed LSB-first)
 * @param d_output Device pointer to output bits (total_E_bits as uint8_t, unpacked, values 0 or 1)
 * @param enable_interleaving Enable QAM bit interleaving (true/false)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t tb_encoder_encode_to_unpacked_bits(tb_encoder_handle_t handle,
                                                    const uint8_t*      d_tb_input,
                                                    uint8_t*            d_output,
                                                    bool                enable_interleaving,
                                                    cudaStream_t        stream);

/**
 * @brief Warm up the TB encoder (trigger JIT compilation)
 *
 * Runs a dummy encode operation to force CUDA kernel JIT compilation.
 * Call this during initialization to avoid first-call latency during
 * real-time operation.
 *
 * @param handle Encoder handle
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t tb_encoder_warmup(tb_encoder_handle_t handle, cudaStream_t stream);

/**
 * @brief Encode TB directly to INT8 symbols (ultra-fast fused path)
 *
 * Complete TX chain in minimal kernel launches:
 *   TB CRC → Segment → CB CRC → LDPC Encode → Rate Match → Scramble → Modulate → INT8
 *
 * This is the fastest path for PDSCH TX, eliminating intermediate buffers.
 * Output is INT8 I/Q pairs suitable for direct DAC output or frequency-domain processing.
 *
 * @param handle Encoder handle
 * @param d_tb_input Device pointer to transport block bits (A bits as uint8_t)
 * @param d_symbols_int8 Device pointer to output INT8 symbols (2 bytes per symbol: I, Q)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t tb_encoder_encode_to_symbols_int8(tb_encoder_handle_t handle,
                                                   const uint8_t*      d_tb_input,
                                                   int8_t*             d_symbols_int8,
                                                   cudaStream_t        stream);

/**
 * @brief Encode TB directly to INT8 symbols using a precomputed device TB CRC.
 *
 * This is equivalent to tb_encoder_encode_to_symbols_int8(), but skips the TB
 * CRC compute kernel and uses d_tb_crc as the already computed CRC value. It is
 * intended only for explicit opt-in paths that already have a trustworthy TB
 * CRC available before enqueueing GPU work. The normal PDSCH path keeps the TB
 * CRC computation GPU resident.
 *
 * @param handle Encoder handle
 * @param d_tb_input Device pointer to transport block bits (A bits as uint8_t)
 * @param d_tb_crc Device pointer to precomputed TB CRC (uint32_t, low bits used)
 * @param d_symbols_int8 Device pointer to output INT8 symbols (2 bytes per symbol: I, Q)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t tb_encoder_encode_to_symbols_int8_precomputed_crc(tb_encoder_handle_t handle,
                                                                   const uint8_t*      d_tb_input,
                                                                   const uint32_t*     d_tb_crc,
                                                                   int8_t*             d_symbols_int8,
                                                                   cudaStream_t        stream);

/**
 * @brief Encode TB directly into a BF16 device resource grid.
 *
 * This GPU-resident path performs CRC, segmentation, LDPC, rate matching,
 * interleaving, scrambling, modulation, and real-grid mapping. It avoids the
 * intermediate INT8 symbol buffer and the separate INT8-to-BF16 grid mapper.
 *
 * @param handle Encoder handle
 * @param d_tb_input Device pointer to transport block bytes
 * @param d_re_offsets Device pointer to one-port linear RE offsets
 * @param d_grid_bf16 Device pointer to BF16 IQ grid, two uint16_t words per RE
 * @param symbol_offset First symbol in the encoded TB stream to map
 * @param nof_re Number of REs to map
 * @param nof_ports Number of output ports
 * @param nof_layers Number of input layers
 * @param nof_grid_re_per_port Number of REs in one full port grid
 * @param weight_real Real precoding weight
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t tb_encoder_encode_to_bf16_grid(tb_encoder_handle_t handle,
                                                const uint8_t*      d_tb_input,
                                                const uint32_t*     d_re_offsets,
                                                uint16_t*           d_grid_bf16,
                                                int                 symbol_offset,
                                                int                 nof_re,
                                                int                 nof_ports,
                                                int                 nof_layers,
                                                int                 nof_grid_re_per_port,
                                                float               weight_real,
                                                cudaStream_t        stream);

// ============================================================================
// Batch Transport Block Encoder Functions
// ============================================================================

/**
 * @brief Batch TB Encoder handle (opaque)
 *
 * Processes multiple TBs in a single pipeline execution for higher efficiency.
 * All TBs in a batch must have the same configuration.
 */
typedef struct tb_batch_encoder_ctx* tb_batch_encoder_handle_t;

/**
 * @brief Batch TB Encoder configuration
 */
typedef struct {
  tb_encoder_config_t tb_cfg;         // Per-TB config (all TBs in batch use same config)
  int                 max_batch_size; // Maximum number of TBs to process in one batch
} tb_batch_encoder_config_t;

/**
 * @brief Create batch TB encoder context
 * @param handle Output encoder handle
 * @return Status code
 */
nr_ldpc_status_t tb_batch_encoder_create(tb_batch_encoder_handle_t* handle);

/**
 * @brief Destroy batch TB encoder context
 * @param handle Encoder handle
 */
void tb_batch_encoder_destroy(tb_batch_encoder_handle_t handle);

/**
 * @brief Configure batch TB encoder
 * @param handle Encoder handle
 * @param cfg Batch encoder configuration
 * @return Status code
 */
nr_ldpc_status_t tb_batch_encoder_configure(tb_batch_encoder_handle_t handle, const tb_batch_encoder_config_t* cfg);

/**
 * @brief Encode a batch of transport blocks (high throughput!)
 *
 * Processes multiple TBs in a single pipeline execution:
 * - Single kernel launch for all CRCs (parallel CRC computation)
 * - Single kernel launch for all segmentation
 * - Single LDPC encoder call for all CBs from all TBs
 * - Single rate matching call for all CBs
 * - Single interleave+scramble+pack for all output
 *
 * @param handle Batch encoder handle
 * @param d_tb_inputs Device pointer to N contiguous TBs (each tb_size_bits/8 bytes)
 * @param d_outputs Device pointer to N contiguous outputs (each output_bits/8 bytes)
 * @param num_tbs Number of TBs to encode (must be <= max_batch_size)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t tb_batch_encoder_encode(tb_batch_encoder_handle_t handle,
                                         const uint8_t*            d_tb_inputs,
                                         uint8_t*                  d_outputs,
                                         int                       num_tbs,
                                         cudaStream_t              stream);

/**
 * @brief Encode a homogeneous batch of transport blocks to PDSCH INT8 symbols
 *
 * This path mirrors tb_encoder_encode_to_symbols_int8() for multiple TBs:
 * TB CRC → Segment → CB CRC → LDPC Encode → RM/Interleave/Scramble/Modulate.
 * The scrambling sequence is restarted for each TB, so all TBs must share the
 * same scrambling configuration.
 *
 * @param handle Batch encoder handle
 * @param d_tb_inputs Device pointer to N contiguous TB payloads
 * @param d_symbols_int8 Device pointer to N contiguous symbol outputs
 * @param num_tbs Number of TBs to encode
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t tb_batch_encoder_encode_to_symbols_int8(tb_batch_encoder_handle_t handle,
                                                         const uint8_t*            d_tb_inputs,
                                                         int8_t*                   d_symbols_int8,
                                                         int                       num_tbs,
                                                         cudaStream_t              stream);

/**
 * @brief Get per-TB output size in bits
 * @param handle Batch encoder handle
 * @return Output size per TB in bits
 */
int tb_batch_encoder_get_output_bits(tb_batch_encoder_handle_t handle);

/**
 * @brief Get per-TB input size in bits
 * @param handle Batch encoder handle
 * @return Input TB size in bits
 */
int tb_batch_encoder_get_input_bits(tb_batch_encoder_handle_t handle);

// ============================================================================
// Transport Block Decoder Functions
// ============================================================================

/**
 * @brief Create TB decoder context
 * @param handle Output decoder handle
 * @return Status code
 */
nr_ldpc_status_t tb_decoder_create(tb_decoder_handle_t* handle);

/**
 * @brief Destroy TB decoder context
 * @param handle Decoder handle
 */
void tb_decoder_destroy(tb_decoder_handle_t handle);

/**
 * @brief Configure TB decoder
 * @param handle Decoder handle
 * @param cfg TB decoder configuration
 * @return Status code
 */
nr_ldpc_status_t tb_decoder_configure(tb_decoder_handle_t handle, const tb_decoder_config_t* cfg);

/**
 * @brief Decode a transport block (complete chain)
 *
 * Performs: De-rate matching -> LDPC decoding -> CRC check -> Desegmentation
 *
 * @param handle Decoder handle
 * @param d_llr_input Device pointer to received LLRs (E values as float)
 * @param d_tb_output Device pointer to output TB bits (A bits as uint8_t)
 * @param result Output decode result (CRC status, iterations)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t tb_decoder_decode(tb_decoder_handle_t handle,
                                   const float*        d_llr_input,
                                   uint8_t*            d_tb_output,
                                   tb_decode_result_t* result,
                                   cudaStream_t        stream);

/**
 * @brief Decode TB from FP16 LLRs (optimized path)
 *
 * Same as tb_decoder_decode but takes half-precision LLRs.
 * Uses FP16 throughout: deinterleave → rate dematch → LDPC decode.
 * ~50% less memory bandwidth than FP32 path.
 *
 * NOTE: Assumes LLRs are already descrambled (set enable_scrambling=false).
 *
 * @param handle Decoder handle
 * @param d_llr_input_half Device pointer to FP16 LLRs (__half*)
 * @param d_tb_output Device pointer to output TB bits
 * @param result Output decode result
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t tb_decoder_decode_half(tb_decoder_handle_t handle,
                                        const void*         d_llr_input_half,
                                        uint8_t*            d_tb_output,
                                        tb_decode_result_t* result,
                                        cudaStream_t        stream);

/**
 * @brief Get expected input LLR count
 * @param handle Decoder handle
 * @return Number of input LLRs (E)
 */
int tb_decoder_get_input_llrs(tb_decoder_handle_t handle);

// ============================================================================
// CRC Utility Functions
// ============================================================================

/**
 * @brief Compute CRC-24A for transport block
 * @param d_data Device pointer to data bits
 * @param num_bits Number of data bits
 * @param d_crc Output 24-bit CRC (device)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t crc24a_compute(const uint8_t* d_data, int num_bits, uint32_t* d_crc, cudaStream_t stream);

/**
 * @brief Compute CRC-24A using caller-owned scratch for large byte-aligned blocks.
 * @param d_data Device pointer to data bits
 * @param num_bits Number of data bits
 * @param d_crc Output 24-bit CRC (device)
 * @param d_chunk_crcs Scratch array for per-chunk CRCs
 * @param d_chunk_sizes Scratch array for per-chunk byte counts
 * @param max_chunks Number of entries available in the scratch arrays
 * @param chunk_size_bytes Number of input bytes per chunk
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t crc24a_compute_with_scratch(const uint8_t* d_data,
                                             int            num_bits,
                                             uint32_t*      d_crc,
                                             uint32_t*      d_chunk_crcs,
                                             int*           d_chunk_sizes,
                                             int            max_chunks,
                                             int            chunk_size_bytes,
                                             cudaStream_t   stream);

/**
 * @brief Compute CRC-24A for multiple transport blocks in one kernel launch
 * @param d_tb_data Device pointer to strided transport block data
 * @param d_crc_out Device pointer to one 24-bit CRC result per transport block
 * @param num_tbs Number of transport blocks
 * @param tb_size_bits Number of payload bits in each transport block
 * @param tb_stride_bytes Stride between transport blocks in bytes
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t crc24a_compute_batch(const uint8_t* d_tb_data,
                                      uint32_t*      d_crc_out,
                                      int            num_tbs,
                                      int            tb_size_bits,
                                      int            tb_stride_bytes,
                                      cudaStream_t   stream);

/**
 * @brief Compute CRC-24B for code block
 * @param d_data Device pointer to data bits
 * @param num_bits Number of data bits
 * @param d_crc Output 24-bit CRC (device)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t crc24b_compute(const uint8_t* d_data, int num_bits, uint32_t* d_crc, cudaStream_t stream);

/**
 * @brief Compute CRC-16 for small transport block
 * @param d_data Device pointer to data bits
 * @param num_bits Number of data bits
 * @param d_crc Output 16-bit CRC (device)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t crc16_compute(const uint8_t* d_data, int num_bits, uint16_t* d_crc, cudaStream_t stream);

/**
 * @brief FUSED CRC-24A compute and attach (saves 1 kernel launch!)
 * @param d_tb_with_crc Device buffer with TB data (CRC will be appended)
 * @param tb_size_bits Number of TB data bits
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t crc24a_compute_and_attach(uint8_t* d_tb_with_crc, int tb_size_bits, cudaStream_t stream);

/**
 * @brief FUSED CRC-16 compute and attach (saves 1 kernel launch!)
 * @param d_tb_with_crc Device buffer with TB data (CRC will be appended)
 * @param tb_size_bits Number of TB data bits
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t crc16_compute_and_attach(uint8_t* d_tb_with_crc, int tb_size_bits, cudaStream_t stream);

/**
 * @brief Check CRC-24A on received data
 * @param d_data Device pointer to data+CRC
 * @param num_bits Total bits including CRC
 * @param stream CUDA stream
 * @return 1 if CRC passes, 0 otherwise
 */
int crc24a_check(const uint8_t* d_data, int num_bits, cudaStream_t stream);

/**
 * @brief Check CRC-24B on received code block
 * @param d_data Device pointer to data+CRC
 * @param num_bits Total bits including CRC
 * @param stream CUDA stream
 * @return 1 if CRC passes, 0 otherwise
 */
int crc24b_check(const uint8_t* d_data, int num_bits, cudaStream_t stream);

/**
 * @brief Check CRC-16 on received small transport block
 * @param d_data Device pointer to data+CRC
 * @param num_bits Total bits including CRC
 * @param stream CUDA stream
 * @return 1 if CRC passes, 0 otherwise
 */
int crc16_check(const uint8_t* d_data, int num_bits, cudaStream_t stream);

/**
 * @brief CRC type for batch checking
 */
typedef enum { CRC_TYPE_24A = 0, CRC_TYPE_24B = 1, CRC_TYPE_16 = 2 } crc_type_t;

/**
 * @brief Batch CRC check on packed decoder output
 *
 * Checks CRC for multiple codeblocks where data is in packed uint32_t format
 * (LSB first, as output by LDPC decoder). Converts to MSB-first byte format
 * internally for CRC computation.
 *
 * @param d_packed_data Device pointer to packed uint32_t decoder output
 * @param words_per_cb Number of uint32_t words per codeblock (stride)
 * @param d_bits_per_cb Device pointer to array of bit counts per CB (including CRC)
 * @param num_cbs Number of codeblocks
 * @param crc_type CRC polynomial type (CRC_TYPE_24A, CRC_TYPE_24B, CRC_TYPE_16)
 * @param d_results Device pointer to output array (1=pass, 0=fail per CB)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t crc_check_batch_packed(const uint32_t* d_packed_data,
                                        int             words_per_cb,
                                        const int*      d_bits_per_cb,
                                        int             num_cbs,
                                        crc_type_t      crc_type,
                                        int*            d_results,
                                        cudaStream_t    stream);

/**
 * @brief Batch CRC check with uniform bit count
 *
 * Optimized version when all CBs have the same bit count.
 *
 * @param d_packed_data Device pointer to packed uint32_t decoder output
 * @param words_per_cb Number of uint32_t words per codeblock (stride)
 * @param bits_per_cb Bit count per CB (including CRC), same for all CBs
 * @param num_cbs Number of codeblocks
 * @param crc_type CRC polynomial type
 * @param d_results Device pointer to output array (1=pass, 0=fail per CB)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t crc_check_batch_packed_uniform(const uint32_t* d_packed_data,
                                                int             words_per_cb,
                                                int             bits_per_cb,
                                                int             num_cbs,
                                                crc_type_t      crc_type,
                                                int*            d_results,
                                                cudaStream_t    stream);

/**
 * @brief Initialize CRC lookup tables for CUDA graph compatibility
 *
 * Pre-initializes the reflected CRC slicing-by-4 lookup tables in constant memory.
 * Call this before CUDA graph capture to prevent cudaMemcpyToSymbol during capture.
 *
 * This is safe to call multiple times; subsequent calls are no-ops.
 * @return true = success, false = failure
 */
bool crc_init_tables(void);

// ============================================================================
// Transport Block Desegmentation Functions
// ============================================================================

/**
 * @brief TB desegmentation configuration
 */
typedef struct {
  int num_code_blocks; // Number of code blocks (C)
  int tb_size_bits;    // Transport block size in bits (A)
  int cb_info_bits;    // Information bits per CB (K - filler - CRC bits)
  int cb_stride_words; // Stride between CBs in uint32_t words
  int tb_crc_bits;     // TB CRC size: 24 for CRC-24A (A > 3824), 16 for CRC-16
  int cb_crc_bits;     // CB CRC size: 24 for multi-CB, 0 for single CB
  int nof_filler_bits; // Filler bits per CB (F) — skipped at start of each CB
} tb_desegment_config_t;

/**
 * @brief TB desegmentation result
 */
typedef struct {
  int tb_crc_pass; // 1 if TB CRC passed, 0 otherwise
} tb_desegment_result_t;

/**
 * @brief Desegment code blocks and check TB CRC on GPU
 *
 * Takes packed uint32_t decoder output (LSB first bit ordering) and:
 * 1. Concatenates CB data bits (excluding CB CRC) into transport block
 * 2. Checks TB CRC (CRC-24A or CRC-16 depending on TB size)
 *
 * This avoids D2H transfer of individual CB data, instead performing
 * desegmentation and CRC check entirely on GPU.
 *
 * @param d_packed_cbs Device pointer to packed CB decoder output (uint32_t per CB)
 * @param d_tb_output Device pointer to output TB bytes (A/8 bytes)
 * @param cfg Desegmentation configuration
 * @param result Output result (TB CRC status)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t tb_desegment_and_check_crc(const uint32_t*              d_packed_cbs,
                                            uint8_t*                     d_tb_output,
                                            const tb_desegment_config_t* cfg,
                                            tb_desegment_result_t*       result,
                                            cudaStream_t                 stream);

/**
 * @brief Async version of tb_desegment_and_check_crc
 *
 * Same as tb_desegment_and_check_crc but writes CRC result to device memory
 * instead of synchronizing and returning on host.
 *
 * @param d_packed_cbs Device pointer to packed CB decoder output
 * @param d_tb_output Device pointer to output TB bytes
 * @param cfg Desegmentation configuration
 * @param d_crc_result Device pointer for CRC result (1=pass, 0=fail)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t tb_desegment_and_check_crc_async(const uint32_t*              d_packed_cbs,
                                                  uint8_t*                     d_tb_output,
                                                  const tb_desegment_config_t* cfg,
                                                  int*                         d_crc_result,
                                                  cudaStream_t                 stream);

/**
 * @brief Standalone async TB CRC-24A check over an already-assembled TB byte stream.
 *
 * Runs the slicing-by-4 CRC kernel used by the fused deseg path as its own launch;
 * use when the TB bytes were produced by an earlier kernel on the same stream
 * (e.g. the fused-TB LDPC decode path). Writes 1 (pass) or 0 (fail) to d_crc_result.
 *
 * @param d_tb_output Device pointer to TB bytes (payload + TB CRC)
 * @param tb_bytes Total TB bytes including CRC
 * @param d_crc_result Device pointer for CRC result (1=pass, 0=fail)
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t
tb_check_crc24a_async(const uint8_t* d_tb_output,
                      int            tb_bytes,
                      int*           d_crc_result,
                      void*        d_scratch_partials, /* >= scratch_slots * sizeof(uint2), or null for single-block */
                      int          scratch_slots,
                      cudaStream_t stream);

// ============================================================================
// LLR Gather Utility
// ============================================================================

/**
 * @brief Gather scattered FP16 LLR segments into contiguous memory
 *
 * Replaces N separate cudaMemcpyAsync D2D calls with a single kernel launch.
 * Used by non-uniform CB path when CBs have different rate-matched lengths.
 *
 * @param d_src_half Device pointer to source FP16 LLRs (scattered)
 * @param d_dst_half Device pointer to destination (contiguous output)
 * @param h_src_offsets Host pointer to per-segment source offsets (in elements)
 * @param d_src_offsets Device scratch for offsets (pre-allocated, >= num_segments * sizeof(unsigned))
 * @param segment_length Elements per segment (group_E)
 * @param num_segments Number of segments to gather
 * @param stream CUDA stream
 * @return Status code
 */
nr_ldpc_status_t gather_llr_segments_half(const void*         d_src_half,
                                          void*               d_dst_half,
                                          const unsigned int* h_src_offsets,
                                          unsigned int*       d_src_offsets,
                                          int                 segment_length,
                                          int                 num_segments,
                                          cudaStream_t        stream);

#ifdef __cplusplus
}
#endif
