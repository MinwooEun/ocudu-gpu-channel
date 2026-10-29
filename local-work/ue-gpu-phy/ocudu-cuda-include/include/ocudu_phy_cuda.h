// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/**
 * @file ocudu_phy_cuda.h
 * @brief OCUDU PHY CUDA - CUDA acceleration for OCUDU
 *
 * Complete library for 5G NR LDPC encoding and decoding with CUDA acceleration.
 *
 * Features:
 * - LDPC encoding/decoding for Base Graph 1 and 2
 * - Rate matching and de-rate matching
 * - Transport block processing with CRC
 *
 * Usage example:
 * @code
 * #include "ocudu_phy_cuda.h"
 *
 * // Create encoder/decoder
 * tb_encoder_handle_t enc;
 * tb_decoder_handle_t dec;
 * tb_encoder_create(&enc);
 * tb_decoder_create(&dec);
 *
 * // Configure for transport block
 * tb_encoder_config_t enc_cfg = {
 *     .tb_size_bits = 8000,
 *     .code_rate = 0.5f,
 *     .modulation_order = 2,
 *     .redundancy_version = 0
 * };
 * tb_encoder_configure(enc, &enc_cfg);
 *
 * // Encode and decode...
 *
 * // Cleanup
 * tb_encoder_destroy(enc);
 * tb_decoder_destroy(dec);
 * @endcode
 */

#pragma once

// Core definitions
#include "nr_ldpc_defs.h"

// Component interfaces
#include "ldpc_decoder.h"
#include "ldpc_encoder.h"
#include "low_phy_prach_rx.h"
#include "low_phy_puxch_rx.h"
#include "low_phy_tx.h"
#include "modulation.h"
#include "ofh_compression.h"
#include "pdsch_fused.h"
#include "polar.h"
#include "prach_detector.h"
#include "pusch_e2e.h"
#include "rate_matching.h"
#include "scrambling.h"
#include "transport_block.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Library version
 */
#define OCUDU_PHY_CUDA_VERSION_MAJOR 1
#define OCUDU_PHY_CUDA_VERSION_MINOR 0
#define OCUDU_PHY_CUDA_VERSION_PATCH 0

/**
 * @brief Get library version string
 * @return Version string
 */
const char* ocudu_phy_cuda_version(void);

/**
 * @brief Initialize the CUDA runtime and validate device availability.
 * @return Status code
 */
nr_ldpc_status_t ocudu_phy_cuda_init(void);

/**
 * @brief Cleanup library resources and reset the active CUDA device.
 */
void ocudu_phy_cuda_cleanup(void);

/**
 * @brief Get error string for status code
 * @param status Status code
 * @return Error string
 */
const char* nr_ldpc_get_error_string(nr_ldpc_status_t status);

/**
 * @brief Print library configuration and capabilities
 */
void ocudu_phy_cuda_print_info(void);

#ifdef __cplusplus
}
#endif
