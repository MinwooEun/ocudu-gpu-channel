// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

#pragma once

#include "nr_ldpc_defs.h"
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct prach_detector_ctx* prach_detector_handle_t;

typedef struct {
  int      sequence_length;
  int      dft_size;
  int      nof_rx_ports;
  int      nof_symbols;
  int      nof_sequences;
  int      sequence_start;
  int      nof_shifts;
  int      n_cs;
  int      win_width;
  int      win_margin;
  int      max_delay_samples;
  int      start_preamble_index;
  int      nof_preamble_indices;
  int      combine_symbols;
  int      input_is_device;
  int      input_symbol_stride;
  int      input_port_stride;
  float    threshold;
  uint64_t root_cache_key;
} prach_detector_config_t;

typedef struct {
  int   valid;
  int   preamble_index;
  int   delay_samples;
  float detection_metric;
  float preamble_power;
} prach_detector_candidate_t;

typedef struct {
  float                      rssi;
  int                        nof_candidates;
  prach_detector_candidate_t candidates[64];
} prach_detector_result_t;

nr_ldpc_status_t prach_detector_create(prach_detector_handle_t* handle);

void prach_detector_destroy(prach_detector_handle_t handle);

nr_ldpc_status_t prach_detector_detect(prach_detector_handle_t        handle,
                                       const void*                    prach_cbf16,
                                       const void*                    roots_cf32,
                                       const prach_detector_config_t* config,
                                       prach_detector_result_t*       result,
                                       void*                          stream);

#ifdef __cplusplus
}
#endif
