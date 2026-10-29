// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/*
 * OCUDU PHY CUDA - CUDA-accelerated 5G NR PHY processing
 *
 * Lightweight DMRS utility functions used by pusch_e2e.cu.
 * The full DMRS generator (dmrs.h / dmrs.cu) is deprecated.
 */

#pragma once

#include <stdint.h>

/* DMRS Type enumeration */
#ifndef OCUDU_PHY_CUDA_DMRS_TYPE_DEFINED
#define OCUDU_PHY_CUDA_DMRS_TYPE_DEFINED
typedef enum {
  DMRS_TYPE_1 = 1, /* Type 1: 6 REs per PRB (every other subcarrier) */
  DMRS_TYPE_2 = 2  /* Type 2: 4 REs per PRB (groups of 2) */
} dmrs_type_t;
#endif

/**
 * Compute DMRS c_init per TS 38.211 6.4.1.1.1.1:
 *   c_init = (2^17 * (14 * n_s + l + 1) * (2*N_ID + 1) + 2*N_ID + n_SCID) mod 2^31
 */
static inline uint32_t dmrs_compute_c_init(int slot_idx, int symbol_idx, uint32_t scrambling_id, int n_scid)
{
  uint64_t term1 = (1ULL << 17) * (14ULL * slot_idx + symbol_idx + 1) * (2ULL * scrambling_id + 1);
  uint64_t term2 = 2ULL * scrambling_id + n_scid;
  return (uint32_t)((term1 + term2) & 0x7fffffff);
}

/**
 * Get number of DMRS REs per PRB for a given DMRS type.
 */
static inline int dmrs_get_re_per_prb(dmrs_type_t type)
{
  switch (type) {
    case DMRS_TYPE_1:
      return 6;
    case DMRS_TYPE_2:
      return 4;
    default:
      return 6;
  }
}
