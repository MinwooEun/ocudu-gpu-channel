// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/**
 * @file nr_ldpc_defs.h
 * @brief 5G NR LDPC Constants and Definitions
 *
 * Based on 3GPP TS 38.212 specifications for LDPC coding.
 * Extracted from NVIDIA Aerial CUDA-Accelerated RAN.
 */

#pragma once

#include <cstdint>

// LDPC Base Graph Constants
#define NR_LDPC_MAX_LIFTING_SIZE 384
#define NR_LDPC_MIN_PARITY_NODES 4

// Base Graph 1 (BG1) parameters
#define NR_LDPC_BG1_PARITY_NODES 46
#define NR_LDPC_BG1_VAR_NODES 68
#define NR_LDPC_BG1_INFO_NODES 22
#define NR_LDPC_BG1_ROWS 46
#define NR_LDPC_BG1_COLS 68
#define NR_LDPC_BG1_NNZ 316

// Base Graph 2 (BG2) parameters - 3GPP TS 38.212 compliant
#define NR_LDPC_BG2_PARITY_NODES 42
#define NR_LDPC_BG2_VAR_NODES 52
#define NR_LDPC_BG2_INFO_NODES 10
#define NR_LDPC_BG2_ROWS 42
#define NR_LDPC_BG2_COLS 52
#define NR_LDPC_BG2_NNZ 197

// Puncturing
#define NR_LDPC_NUM_PUNCTURED_NODES 2
#define NR_LDPC_BG1_UNPUNCTURED_VARS (NR_LDPC_BG1_VAR_NODES - NR_LDPC_NUM_PUNCTURED_NODES)
#define NR_LDPC_BG2_UNPUNCTURED_VARS (NR_LDPC_BG2_VAR_NODES - NR_LDPC_NUM_PUNCTURED_NODES)

// Maximum code block sizes
#define NR_LDPC_MAX_CB_INFO_BITS 8448     // K_cb max for BG1
#define NR_LDPC_MAX_CB_INFO_BITS_BG2 3840 // K_cb max for BG2
#define NR_LDPC_MAX_ENCODED_BITS 26112    // Maximum encoded bits per CB

// Transport Block parameters
#define NR_MAX_TBS_BITS 1277992   // ~160KB max TBS
#define NR_MAX_NUM_CBS_PER_TB 152 // Maximum code blocks per TB
#define NR_TB_CRC24A_BITS 24      // CRC-24A for large TBs
#define NR_TB_CRC16_BITS 16       // CRC-16 for small TBs
#define NR_CB_CRC24B_BITS 24      // CRC-24B for code blocks

// CRC Polynomials (from 3GPP TS 38.212)
#define NR_CRC24A_POLY                                                                                                 \
  0x1864cfb // g_CRC24A(D) = D^24 + D^23 + D^18 + D^17 + D^14 + D^11 + D^10 + D^7 + D^6 + D^5 + D^4 + D^3 + D + 1
#define NR_CRC24B_POLY 0x1800063 // g_CRC24B(D) = D^24 + D^23 + D^6 + D^5 + D + 1
#define NR_CRC16_POLY 0x11021    // g_CRC16(D) = D^16 + D^12 + D^5 + 1

// Rate matching parameters
#define NR_MAX_REDUNDANCY_VERSIONS 4

// Lifting size sets (iLS)
#define NR_LDPC_NUM_LIFTING_SETS 8
#define NR_LDPC_NUM_LIFTING_SIZES 51

// Supported lifting sizes per set
static const int NR_LDPC_LIFTING_SIZES[NR_LDPC_NUM_LIFTING_SIZES] = {
    2,  3,   4,   5,   6,   7,   8,   9,   10,  11,  12,  13,  14,  15,  16,  18,  20,
    22, 24,  26,  28,  30,  32,  36,  40,  44,  48,  52,  56,  60,  64,  72,  80,  88,
    96, 104, 112, 120, 128, 144, 160, 176, 192, 208, 224, 240, 256, 288, 320, 352, 384};

// QAM modulation orders
typedef enum {
  NR_MOD_BPSK   = 1,
  NR_MOD_QPSK   = 2,
  NR_MOD_16QAM  = 4,
  NR_MOD_64QAM  = 6,
  NR_MOD_256QAM = 8
} nr_modulation_t;

// LDPC Configuration structure
typedef struct {
  int  base_graph;         // 1 or 2
  int  lifting_size;       // Z value
  int  lifting_set_index;  // iLS (0-7)
  int  num_info_bits;      // K (information bits including CRC)
  int  num_parity_bits;    // N - K
  int  num_filler_bits;    // F (filler bits)
  int  num_codeword_bits;  // N (total codeword bits)
  bool puncture;           // Whether to puncture first 2*Z bits
  int  max_parity_nodes;   // Number of parity check rows
  int  redundancy_version; // rv (0-3)
} nr_ldpc_config_t;

// Transport Block Configuration
typedef struct {
  int              tb_size_bits;    // A (transport block size in bits)
  int              num_code_blocks; // C (number of code blocks)
  int              cb_size_bits;    // K (code block size including CRC)
  int              filler_bits;     // F (filler bits per CB)
  int              tb_crc_bits;     // L (16 or 24)
  int              cb_crc_bits;     // Always 24 for multiple CBs
  nr_ldpc_config_t ldpc_cfg;
} nr_tb_config_t;

// Rate Matching Configuration
typedef struct {
  int  E;              // Rate matched output length
  int  Q_m;            // Modulation order (bits per symbol)
  int  rv;             // Redundancy version (0-3)
  int  N_cb;           // Circular buffer size
  int  k0;             // Starting position in circular buffer
  bool limited_buffer; // Limited buffer rate matching
} nr_rate_match_config_t;

// Error codes
typedef enum {
  NR_LDPC_SUCCESS              = 0,
  NR_LDPC_ERROR_INVALID_BG     = 1,
  NR_LDPC_ERROR_INVALID_Z      = 2,
  NR_LDPC_ERROR_INVALID_CONFIG = 3,
  NR_LDPC_ERROR_CUDA_FAILED    = 4,
  NR_LDPC_ERROR_ALLOC_FAILED   = 5,
  NR_LDPC_ERROR_SIZE_MISMATCH  = 6
} nr_ldpc_status_t;

// Helper function declarations
#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Get the lifting set index (iLS) for a given lifting size Z
 * @param Z Lifting size
 * @return iLS value (0-7) or -1 if Z is invalid
 */
int nr_ldpc_get_lifting_set_index(int Z);

/**
 * @brief Get Kb (number of information columns) based on TBS and BG
 * @param tbs Transport block size
 * @param bg Base graph (1 or 2)
 * @return Kb value
 */
int nr_ldpc_get_Kb(int tbs, int bg);

/**
 * @brief Select base graph based on TBS and code rate
 * @param tbs Transport block size in bits
 * @param rate Code rate (R)
 * @return Base graph (1 or 2)
 */
int nr_ldpc_select_base_graph(int tbs, float rate);

/**
 * @brief Compute lifting size Z for given K and Kb
 * @param K Code block size (including CRC)
 * @param Kb Information columns
 * @return Lifting size Z
 */
int nr_ldpc_compute_lifting_size(int K, int Kb);

/**
 * @brief Initialize LDPC configuration for a transport block
 * @param cfg Output configuration
 * @param tbs Transport block size
 * @param rate Target code rate
 * @return Status code
 */
nr_ldpc_status_t nr_ldpc_init_config(nr_ldpc_config_t* cfg, int tbs, float rate);

/**
 * @brief Initialize transport block configuration
 * @param tb_cfg Output configuration
 * @param tbs Transport block size in bits
 * @param rate Target code rate
 * @return Status code
 */
nr_ldpc_status_t nr_tb_init_config(nr_tb_config_t* tb_cfg, int tbs, float rate);

#ifdef __cplusplus
}
#endif
