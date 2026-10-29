// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define OCUDU_LOWPHY_PRACH_RX_MAX_FD_OCCASIONS 16

typedef struct ocudu_lowphy_prach_rx_handle ocudu_lowphy_prach_rx_handle_t;

typedef struct {
  int   dft_size;
  int   sequence_length;
  int   nof_symbols;
  int   nof_fd_occasions;
  int   input_nof_samples;
  int   cyclic_prefix_length;
  int   prach_grid_size;
  int   k_start[OCUDU_LOWPHY_PRACH_RX_MAX_FD_OCCASIONS];
  int   output_symbol_stride;
  int   output_fd_stride;
  int   input_is_device;
  float dft_scale;
} ocudu_lowphy_prach_rx_config_t;

int ocudu_lowphy_prach_rx_create(const ocudu_lowphy_prach_rx_config_t* config, ocudu_lowphy_prach_rx_handle_t** handle);
void ocudu_lowphy_prach_rx_destroy(ocudu_lowphy_prach_rx_handle_t* handle);
int  ocudu_lowphy_prach_rx_update_config(ocudu_lowphy_prach_rx_handle_t*       handle,
                                         const ocudu_lowphy_prach_rx_config_t* config);

int ocudu_lowphy_prach_rx_process(ocudu_lowphy_prach_rx_handle_t* handle,
                                  const void*                     input_cf32,
                                  void*                           output_cbf16,
                                  void*                           external_stream);

int ocudu_lowphy_prach_rx_process_ci16(ocudu_lowphy_prach_rx_handle_t* handle,
                                       const void*                     input_ci16,
                                       float                           input_scale,
                                       void*                           output_cbf16,
                                       void*                           external_stream);

int   ocudu_lowphy_prach_rx_synchronize(ocudu_lowphy_prach_rx_handle_t* handle);
void* ocudu_lowphy_prach_rx_get_completion_event(ocudu_lowphy_prach_rx_handle_t* handle);
void* ocudu_lowphy_prach_rx_get_stream(ocudu_lowphy_prach_rx_handle_t* handle);

#ifdef __cplusplus
}
#endif
