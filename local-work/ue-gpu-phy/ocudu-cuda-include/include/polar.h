// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/**
 * @file polar.h
 * @brief CUDA-accelerated 5G NR polar coding primitives.
 */

#pragma once

#include "nr_ldpc_defs.h"
#include <cuda_fp16.h>
#include <cuda_runtime.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define POLAR_MAX_N 1024
#define POLAR_MAX_E 8192
#define POLAR_MAX_N_LOG 10
#define POLAR_MAX_SSC_OPS (4 * POLAR_MAX_N)
#define POLAR_UCI_MAX_CODEBLOCK_PAYLOAD_BITS POLAR_MAX_N

#define POLAR_NODE_RATE_0 0
#define POLAR_NODE_RATE_R 2
#define POLAR_NODE_RATE_1 3

#define POLAR_SSC_OP_RATE_0 0
#define POLAR_SSC_OP_RATE_1 1
#define POLAR_SSC_OP_F 2
#define POLAR_SSC_OP_G 3
#define POLAR_SSC_OP_COMBINE 4
#define POLAR_SSC_OP_REP 5
#define POLAR_SSC_OP_SPC 6
#define POLAR_SSC_OP_G0 7

typedef enum { POLAR_IBIL_NOT_PRESENT = 0, POLAR_IBIL_PRESENT = 1 } polar_ibil_t;

typedef struct {
  int      K;
  int      E;
  int      n_max;
  int      n;
  int      N;
  int      n_pc;
  int      n_wm_pc;
  int      ibil;
  int      num_frozen;
  uint8_t  frozen_mask[POLAR_MAX_N];
  uint16_t pc_set[4];
  uint8_t  node_rate[(POLAR_MAX_N_LOG + 1) * POLAR_MAX_N];
  uint16_t nof_ssc_ops;
  uint8_t  ssc_op_type[POLAR_MAX_SSC_OPS];
  uint8_t  ssc_op_stage[POLAR_MAX_SSC_OPS];
  uint16_t ssc_op_start[POLAR_MAX_SSC_OPS];
  uint16_t block_interleaver[POLAR_MAX_N];
  uint16_t ch_input_for_output[POLAR_MAX_E];
  uint16_t ch_output_for_input[POLAR_MAX_E];
} polar_code_config_t;

typedef struct polar_ctx* polar_handle_t;

typedef struct {
  uint8_t  payload[POLAR_UCI_MAX_CODEBLOCK_PAYLOAD_BITS];
  uint16_t nof_bits;
  uint8_t  status;
  uint8_t  decoded;
} polar_uci_decode_result_t;

nr_ldpc_status_t polar_code_configure(polar_code_config_t* cfg, int K, int E, int n_max, polar_ibil_t ibil);

nr_ldpc_status_t polar_create(polar_handle_t* handle);
void             polar_destroy(polar_handle_t handle);
nr_ldpc_status_t polar_configure(polar_handle_t handle, const polar_code_config_t* cfg);
nr_ldpc_status_t polar_configure_async(polar_handle_t handle, const polar_code_config_t* cfg, cudaStream_t stream);

nr_ldpc_status_t
polar_encode_rate_match_u8(polar_handle_t handle, uint8_t* d_output, const uint8_t* d_input, cudaStream_t stream);

nr_ldpc_status_t
polar_rate_dematch_decode_half(polar_handle_t handle, uint8_t* d_output, const __half* d_input, cudaStream_t stream);

nr_ldpc_status_t polar_uci_rate_dematch_decode_crc_half(polar_handle_t             handle,
                                                        polar_uci_decode_result_t* d_result,
                                                        const __half*              d_input,
                                                        int                        nof_payload_bits,
                                                        int                        nof_filler_bits,
                                                        int                        crc_order,
                                                        cudaStream_t               stream);

#ifdef __cplusplus
}
#endif
