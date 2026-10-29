// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ocudu_lowphy_tx_handle ocudu_lowphy_tx_handle_t;

enum { OCUDU_LOWPHY_TX_MAX_SYMBOLS = 28, OCUDU_LOWPHY_TX_MAX_PORTS = 8 };

typedef struct {
  int   dft_size;
  int   rg_size;
  int   nof_ports;
  int   nof_symbols;
  int   nof_samples;
  int   cp_lengths[OCUDU_LOWPHY_TX_MAX_SYMBOLS];
  int   symbol_offsets[OCUDU_LOWPHY_TX_MAX_SYMBOLS];
  float phase_re[OCUDU_LOWPHY_TX_MAX_SYMBOLS];
  float phase_im[OCUDU_LOWPHY_TX_MAX_SYMBOLS];
  float ofdm_scale;
  float amplitude_gain;
  float clipping_ceiling;
  int   clipping_enabled;
} ocudu_lowphy_tx_config_t;

int  ocudu_lowphy_tx_create(const ocudu_lowphy_tx_config_t* config, ocudu_lowphy_tx_handle_t** handle);
void ocudu_lowphy_tx_destroy(ocudu_lowphy_tx_handle_t* handle);
int  ocudu_lowphy_tx_update_config(ocudu_lowphy_tx_handle_t* handle, const ocudu_lowphy_tx_config_t* config);
int  ocudu_lowphy_tx_register_host_output(ocudu_lowphy_tx_handle_t* handle, void* ptr, size_t bytes);

int ocudu_lowphy_tx_process(ocudu_lowphy_tx_handle_t* handle,
                            const void*               d_grid_cbf16,
                            void* const*              h_output_ports,
                            void*                     external_stream);

int ocudu_lowphy_tx_process_host_grid(ocudu_lowphy_tx_handle_t* handle,
                                      const void*               h_grid_cbf16,
                                      void* const*              h_output_ports,
                                      void*                     external_stream);

int   ocudu_lowphy_tx_synchronize(ocudu_lowphy_tx_handle_t* handle);
void* ocudu_lowphy_tx_get_completion_event(ocudu_lowphy_tx_handle_t* handle);
void* ocudu_lowphy_tx_get_stream(ocudu_lowphy_tx_handle_t* handle);

#ifdef __cplusplus
}
#endif
