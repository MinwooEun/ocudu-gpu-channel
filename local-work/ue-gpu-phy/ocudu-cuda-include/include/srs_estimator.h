// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/*
 * OCUDU PHY CUDA - CUDA-accelerated 5G NR PHY processing
 *
 * GPU Sounding Reference Signal channel estimator.
 */

#pragma once

#include "nr_ldpc_defs.h"
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SRS_ESTIMATOR_MAX_RX_PORTS 4
#define SRS_ESTIMATOR_MAX_TX_PORTS 4
#define SRS_ESTIMATOR_MAX_SEQUENCE_LENGTH 1632
#define SRS_ESTIMATOR_MAX_DFT_SIZE 4096

typedef struct {
  float real;
  float imag;
} srs_estimator_cf_t;

typedef struct {
  int nof_rx_ports;
  int nof_tx_ports;
  int nof_symbols;
  int start_symbol;
  int sequence_length;
  int comb_size;
  int grid_nof_ports;
  int grid_nof_symbols;
  int grid_nof_subcarriers;
  int scs_khz;
  int dft_size;
  int correlation_window_size;
  int ta_max_samples;
  int interleaved_pilots;
  int mapping_initial_subcarrier[SRS_ESTIMATOR_MAX_TX_PORTS];
  int rx_ports[SRS_ESTIMATOR_MAX_RX_PORTS];
} srs_estimator_config_t;

typedef struct {
  srs_estimator_cf_t coeff[SRS_ESTIMATOR_MAX_RX_PORTS * SRS_ESTIMATOR_MAX_TX_PORTS];
  float              epre_linear;
  float              rsrp_linear;
  float              noise_variance;
  float              epre_dB;
  float              rsrp_dB;
} srs_estimator_metrics_t;

typedef struct {
  float time_alignment_s;
  float resolution_s;
  float min_s;
  float max_s;
} srs_estimator_time_alignment_t;

struct srs_estimator_ctx;
typedef struct srs_estimator_ctx* srs_estimator_handle_t;

nr_ldpc_status_t srs_estimator_create(srs_estimator_handle_t* handle);

void srs_estimator_destroy(srs_estimator_handle_t handle);

nr_ldpc_status_t srs_estimator_configure(srs_estimator_handle_t        handle,
                                         const srs_estimator_config_t* cfg,
                                         const srs_estimator_cf_t*     sequences,
                                         void*                         stream);

nr_ldpc_status_t srs_estimator_estimate_auto_ta(srs_estimator_handle_t          handle,
                                                const void*                     d_grid_cbf16,
                                                float                           max_time_alignment_s,
                                                srs_estimator_time_alignment_t* time_alignment,
                                                srs_estimator_metrics_t*        metrics,
                                                void*                           stream);

#ifdef __cplusplus
}
#endif
