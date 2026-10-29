// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ocudu_lowphy_puxch_rx_handle ocudu_lowphy_puxch_rx_handle_t;

enum { OCUDU_LOWPHY_PUXCH_RX_MAX_PORTS = 8, OCUDU_LOWPHY_PUXCH_RX_MAX_SYMBOLS = 14 };

typedef struct {
  int   dft_size;
  int   rg_size;
  int   grid_nof_subc;
  int   grid_nof_symbols;
  int   nof_ports;
  int   input_nof_samples;
  int   cyclic_prefix_length;
  int   window_offset;
  int   symbol_index;
  int   port_indices[OCUDU_LOWPHY_PUXCH_RX_MAX_PORTS];
  int   input_is_device;
  float dft_scale;
  float phase_re;
  float phase_im;
  int   use_symbol_phases;
  float symbol_phase_re[OCUDU_LOWPHY_PUXCH_RX_MAX_SYMBOLS];
  float symbol_phase_im[OCUDU_LOWPHY_PUXCH_RX_MAX_SYMBOLS];
  int   use_symbol_layout;
  int   symbol_input_nof_samples[OCUDU_LOWPHY_PUXCH_RX_MAX_SYMBOLS];
  int   symbol_cyclic_prefix_length[OCUDU_LOWPHY_PUXCH_RX_MAX_SYMBOLS];
  int   symbol_window_offset[OCUDU_LOWPHY_PUXCH_RX_MAX_SYMBOLS];
} ocudu_lowphy_puxch_rx_config_t;

int ocudu_lowphy_puxch_rx_create(const ocudu_lowphy_puxch_rx_config_t* config, ocudu_lowphy_puxch_rx_handle_t** handle);
void ocudu_lowphy_puxch_rx_destroy(ocudu_lowphy_puxch_rx_handle_t* handle);
int  ocudu_lowphy_puxch_rx_update_config(ocudu_lowphy_puxch_rx_handle_t*       handle,
                                         const ocudu_lowphy_puxch_rx_config_t* config);
int  ocudu_lowphy_puxch_rx_prime_config(ocudu_lowphy_puxch_rx_handle_t*       handle,
                                        const ocudu_lowphy_puxch_rx_config_t* config,
                                        float                                 input_scale,
                                        void*                                 external_stream);

int ocudu_lowphy_puxch_rx_process_ci16(ocudu_lowphy_puxch_rx_handle_t* handle,
                                       const void*                     input_ci16,
                                       float                           input_scale,
                                       void*                           output_cbf16,
                                       void*                           external_stream);

int ocudu_lowphy_puxch_rx_process_ci16_ports(ocudu_lowphy_puxch_rx_handle_t* handle,
                                             const void* const*              input_ports_ci16,
                                             float                           input_scale,
                                             void*                           output_cbf16,
                                             void*                           external_stream);

int ocudu_lowphy_puxch_rx_process_ci16_symbol_batch_ports(ocudu_lowphy_puxch_rx_handle_t* handle,
                                                          const void* const*              input_symbols_ports_ci16,
                                                          int                             nof_symbols,
                                                          float                           input_scale,
                                                          void*                           output_cbf16,
                                                          void*                           external_stream);

int   ocudu_lowphy_puxch_rx_synchronize(ocudu_lowphy_puxch_rx_handle_t* handle);
void* ocudu_lowphy_puxch_rx_get_completion_event(ocudu_lowphy_puxch_rx_handle_t* handle);
void* ocudu_lowphy_puxch_rx_get_stream(ocudu_lowphy_puxch_rx_handle_t* handle);

#ifdef __cplusplus
}
#endif
