// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/*
 * OCUDU PHY CUDA - CUDA-accelerated 5G NR PHY processing
 *
 * Fused PUSCH End-to-End Processing with Integrated Channel Estimation
 *
 * This module provides a fully GPU-accelerated PUSCH receive chain that
 * eliminates the need for CPU channel estimation:
 *   Grid (H2D) → DMRS Pilot Gen → Channel Estimation → Equalization → Demod → Descramble
 *
 * Benefits:
 * - ~50% reduction in H2D transfer (no pre-computed estimates needed)
 * - Eliminates CPU channel estimation overhead
 * - Keeps all intermediate data on GPU
 */

#pragma once

#include "dmrs_utils.h"
#include "nr_ldpc_defs.h"
#include <cuda_runtime.h>

/* Equalizer algorithm type — originally from equalization.h (now deprecated) */
#ifndef EQUALIZER_ALGORITHM_TYPE_DEFINED
#define EQUALIZER_ALGORITHM_TYPE_DEFINED
typedef enum { EQUALIZER_ZF = 0, EQUALIZER_MMSE = 1, EQUALIZER_MMSE_IRC = 2 } equalizer_algorithm_t;
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* PUSCH E2E handle (opaque) */
struct pusch_e2e_ctx;
typedef struct pusch_e2e_ctx* pusch_e2e_handle_t;

/* PUSCH E2E configuration */
typedef struct {
  /* Grid dimensions */
  int nof_prb;              /* Number of PRBs in allocation */
  int nof_symbols;          /* Number of OFDM symbols */
  int nof_rx_ports;         /* Number of receive ports (1, 2, 4, or 8) */
  int nof_tx_layers;        /* Number of transmit layers (1, 2, 3, or 4) */
  int grid_nof_subcarriers; /* Total subcarriers in grid */
  int grid_nof_symbols;     /* Total symbols in grid */

  /* DMRS configuration */
  dmrs_type_t dmrs_type;                   /* DMRS Type 1 or 2 */
  int         dmrs_symbol_mask;            /* Bitmask of DMRS symbols (14 bits for normal CP) */
  int         nof_cdm_groups_without_data; /* 1, 2, or 3 */
  uint32_t    scrambling_id;               /* DMRS scrambling ID */
  int         n_scid;                      /* Sequence initialization */
  int         slot_idx;                    /* Slot index in frame */
  float       dmrs_scaling;                /* DMRS amplitude scaling */

  /* Modulation and scrambling */
  int      mod_order; /* Bits per symbol: 2=QPSK, 4=16QAM, 6=64QAM, 8=256QAM */
  uint16_t rnti;      /* RNTI for data scrambling */
  uint16_t n_id;      /* Scrambling ID for data */

  /* Allocation */
  int start_prb;    /* Starting PRB in grid */
  int start_symbol; /* Starting symbol index */

  /* Processing options */
  float                 tx_scaling;          /* TX scaling factor for equalization */
  equalizer_algorithm_t equalizer_algorithm; /* ZF, MMSE, or MMSE-IRC */

  /* Subcarrier spacing in kHz (15, 30, 60, 120) — needed for TA computation */
  int scs_khz;

  /* Low-PAPR DMRS configuration for transform precoding (MSG3/DFT-s-OFDM) */
  int use_low_papr_dmrs; /* 1 for transform precoding, 0 for pseudo-random */
  int n_rs_id;           /* Reference signal sequence ID (0-1007) for low-PAPR */

  /* CFO compensation: apply estimated CFO to channel estimates during equalization */
  int compensate_cfo; /* 1 = enabled (default), 0 = disabled */

  /* Noise estimation mode for equalization:
   *   0 = cross-validation: σ² from var(H across DMRS syms) × 2.5
   *   1 = pilot-residual (recommended): σ² from |y - H_avg × pilot|² / N_pilots
   * Pilot-residual matches CPU estimate_noise() and is robust under
   * frequency-selective fading. Cross-validation uses empirical 2.5x
   * calibration that over-estimates noise under fading channels. */
  int noise_mode; /* 0 = cross-validation, 1 = pilot-residual (recommended) */

  /* Time-domain interpolation mode for channel estimates:
   *   0 = average (default): mean of all DMRS estimates for every data symbol
   *   1 = linear: linear interpolation between bracketing DMRS + edge extrapolation
   * Average mode matches CPU "average" strategy and gives ~2.5dB better CE SNR
   * under AWGN, closing the 0.2dB BLER gap at 256QAM waterfall. */
  int time_interp_mode; /* 0 = average (default), 1 = linear */

  /* Compute CPU-style hard-decision EVM on device. Disabled by default so the
   * latency path only pays this cost when EVM metrics or EVM-based SINR are requested. */
  int enable_evm_metric; /* 1 = accumulate EVM, 0 = skip */
} pusch_e2e_config_t;

/**
 * Create PUSCH E2E processing handle.
 * @param handle Output handle
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t pusch_e2e_create(pusch_e2e_handle_t* handle);

/**
 * Pre-plan optional transform deprecoder backends on the processing stream.
 *
 * The default in-tree deprecoder does not need this. Optional backends such as
 * VkFFT use this hook to compile and cache the selected 5G NR DFT sizes during
 * processor startup instead of the slot critical path.
 *
 * @param handle Handle
 * @param stream CUDA stream used by the PUSCH E2E processor
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t pusch_e2e_preplan_transform_deprecoder(pusch_e2e_handle_t handle, cudaStream_t stream);

/**
 * Destroy PUSCH E2E processing handle.
 * @param handle Handle to destroy
 */
void pusch_e2e_destroy(pusch_e2e_handle_t handle);

/**
 * Configure PUSCH E2E processing for a transmission.
 * @param handle Handle
 * @param cfg Configuration
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t pusch_e2e_configure(pusch_e2e_handle_t handle, const pusch_e2e_config_t* cfg);

/**
 * Update per-slot config values that change between PUSCH transmissions.
 *
 * This function updates the handle's config with per-slot values without
 * triggering a full reconfiguration (which would sync the GPU).
 * Call this before pusch_e2e_process_*() when nof_prb, start_prb, slot_idx,
 * or dmrs_symbol_mask changes from the configured values.
 *
 * @param handle Handle (must be configured)
 * @param nof_prb Number of PRBs in this slot's allocation
 * @param start_prb Starting PRB index
 * @param slot_idx Slot index
 * @param dmrs_symbol_mask DMRS symbol bitmask for this slot
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t
pusch_e2e_update_slot_config(pusch_e2e_handle_t handle, int nof_prb, int start_prb, int slot_idx, int dmrs_symbol_mask);

/**
 * Lightweight update of PUSCH data scrambling parameters (RNTI / n_ID / mod_order).
 *
 * Prefer this over a full pusch_e2e_configure() when only data-scrambling identity
 * or modulation order changes (common for MCS adaptation). Structural geometry,
 * DMRS pilots, and other configure-time tables are left untouched — no DMRS
 * precompute and no cudaDeviceSynchronize on the DMRS path.
 *
 * Scramble sequence is regenerated only when c_init changes or the cached
 * sequence is shorter than needed. Capacity is grown to 256QAM worst-case so
 * MCS increases typically avoid regeneration.
 *
 * @param handle    Handle (must already be configured)
 * @param rnti      UE C-RNTI used for PUSCH data scrambling
 * @param n_id      Data scrambling identity
 * @param mod_order Modulation order (bits/symbol): 1/2/4/6/8
 */
nr_ldpc_status_t pusch_e2e_update_data_params(pusch_e2e_handle_t handle, uint16_t rnti, uint16_t n_id, int mod_order);

/**
 * Get device pointer to internally generated channel estimates.
 *
 * After calling pusch_e2e_process_with_chest(), the channel estimates
 * are available in GPU memory. This function returns a pointer to them
 * for inspection or further processing.
 *
 * @param handle Handle
 * @return Device pointer to channel estimates, or NULL if not available
 */
const void* pusch_e2e_get_estimates(pusch_e2e_handle_t handle);

/**
 * Process PUSCH with fully GPU-resident noise estimation (no CPU inputs).
 *
 * This function performs the COMPLETE PUSCH receive chain on GPU, including
 * noise variance estimation from DMRS residuals. No CPU-computed values needed:
 * 1. Generate DMRS pilot symbols
 * 2. Extract DMRS from grid and compute LSE channel estimates
 * 3. Estimate noise variance from DMRS residuals (NEW!)
 * 4. Interpolate channel estimates to all data REs
 * 5. MMSE-IRC equalization
 * 6. Soft demodulation
 * 7. Descrambling
 *
 * This eliminates the last CPU dependency in the PUSCH chain.
 *
 * @param handle Handle (must be configured)
 * @param d_grid_cbf16 Device pointer to grid [nof_ports, nof_symbols, nof_subcarriers] (cbf16)
 * @param d_llrs_half Output: Device pointer to LLRs [nof_data_re * mod_order] (fp16)
 * @param d_re_indices Device pointer to data RE indices [nof_data_re] (int)
 * @param nof_data_re Number of data REs to process
 * @param stream CUDA stream
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t pusch_e2e_process_full_gpu(pusch_e2e_handle_t handle,
                                            const void*        d_grid_cbf16,
                                            void*              d_llrs_half,
                                            const int*         d_re_indices,
                                            int                nof_data_re,
                                            cudaStream_t       stream);

/**
 * Process PUSCH with GPU channel estimation AND transform deprecoding (DFT-s-OFDM).
 *
 * Same as pusch_e2e_process_full_gpu() but applies IDFT (inverse DFT) to
 * equalized symbols before soft demodulation. Used for DFT-s-OFDM uplink.
 *
 * @param handle Handle (must be configured)
 * @param d_grid_cbf16 Device pointer to grid [nof_ports, nof_symbols, nof_subcarriers] (cbf16)
 * @param d_llrs_half Output: Device pointer to LLRs [nof_data_re * mod_order] (fp16)
 * @param d_re_indices Device pointer to data RE indices [nof_data_re] (int)
 * @param nof_data_re Number of data REs to process
 * @param dft_size DFT size for transform deprecoding (12 * nof_prbs)
 * @param nof_ofdm_symbols Number of OFDM data symbols
 * @param stream CUDA stream
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t pusch_e2e_process_full_gpu_with_deprecoding(pusch_e2e_handle_t handle,
                                                             const void*        d_grid_cbf16,
                                                             void*              d_llrs_half,
                                                             const int*         d_re_indices,
                                                             int                nof_data_re,
                                                             int                dft_size,
                                                             int                nof_ofdm_symbols,
                                                             cudaStream_t       stream);

/**
 * Get device pointer to GPU-computed noise variances.
 *
 * After calling pusch_e2e_process_full_gpu(), the noise variances computed
 * from DMRS residuals are available in GPU memory.
 *
 * @param handle Handle
 * @return Device pointer to per-port noise variances [nof_rx_ports], or NULL
 */
const float* pusch_e2e_get_noise_vars(pusch_e2e_handle_t handle);

// Superseded by the async SINR path (pusch_e2e_sinr_async_launch + pusch_e2e_sinr_get_result).
float pusch_e2e_get_sinr_db(pusch_e2e_handle_t handle, cudaStream_t stream);

/**
 * Launch async D2H transfer of SINR accumulation values.
 *
 * Queues tiny async D2H copies of post-equalization SINR/EVM accumulators
 * and DMRS-derived EPRE/RSRP/TA/CFO metrics to pinned host memory. Call this
 * right after the E2E kernel, then later call pusch_e2e_sinr_get_result()
 * after synchronizing to read the values.
 *
 * @param handle Handle
 * @param stream CUDA stream (async copies are enqueued on this stream)
 */
void pusch_e2e_sinr_async_launch(pusch_e2e_handle_t handle, cudaStream_t stream);

/**
 * Read SINR from previously launched async D2H transfer.
 *
 * Returns post-equalization SINR from averaged equalizer noise variance,
 * matching the CPU demodulator SINR. Falls back to DMRS pilot-ratio SINR only
 * when no post-equalization accumulator is available.
 *
 * Must be called after pusch_e2e_sinr_async_launch() and after the stream
 * has been synchronized (or an event on the stream has been waited on).
 *
 * @param handle Handle
 * @return SINR in dB, or -INFINITY if no valid data
 */
float pusch_e2e_sinr_get_result(pusch_e2e_handle_t handle);

/**
 * Read EPRE from previously launched async D2H transfer.
 *
 * Returns the Energy Per Resource Element computed from DMRS received symbols.
 * Must be called after pusch_e2e_sinr_async_launch() and after the stream
 * has been synchronized.
 *
 * @param handle Handle
 * @return EPRE in dB, or -INFINITY if no valid data
 */
float pusch_e2e_epre_get_result(pusch_e2e_handle_t handle);

/**
 * Read RSRP (dB) from previously launched async D2H transfer.
 *
 * Returns the average per-port RSRP computed from DMRS channel estimates.
 * Must be called after pusch_e2e_sinr_async_launch() and stream sync.
 *
 * @param handle Handle
 * @return RSRP in dB, or -INFINITY if no valid data
 */
float pusch_e2e_rsrp_get_result(pusch_e2e_handle_t handle);

/**
 * Read TA (seconds) from previously launched async D2H transfer.
 *
 * Returns the time alignment estimated via phase-slope across DMRS pilots.
 * Must be called after pusch_e2e_sinr_async_launch() and stream sync.
 *
 * @param handle Handle
 * @return TA in seconds, or NAN if no valid data
 */
float pusch_e2e_ta_get_result(pusch_e2e_handle_t handle);

/**
 * Read CFO (Hz) from previously launched async D2H transfer.
 *
 * Returns the carrier frequency offset estimated from phase rotation between
 * consecutive DMRS symbols. Requires >= 2 DMRS symbols.
 * Must be called after pusch_e2e_sinr_async_launch() and stream sync.
 *
 * @param handle Handle
 * @return CFO in Hz, or NAN if not available (< 2 DMRS symbols)
 */
float pusch_e2e_cfo_get_result(pusch_e2e_handle_t handle);

/**
 * Read EVM from previously launched async D2H transfer.
 *
 * Returns CPU-style hard-decision/remodulated symbol EVM when enabled in the
 * PUSCH E2E configuration. Must be called after pusch_e2e_sinr_async_launch()
 * and stream sync.
 *
 * @param handle Handle
 * @return EVM as a linear ratio, or NAN if not available
 */
float pusch_e2e_evm_get_result(pusch_e2e_handle_t handle);

/**
 * Print diagnostic information about the GPU channel estimation.
 *
 * @param handle Handle
 * @param stream CUDA stream (will synchronize to ensure kernel completion)
 */
void pusch_e2e_print_diagnostics(pusch_e2e_handle_t handle, cudaStream_t stream);

/**
 * Warm up the GPU PUSCH E2E pipeline by running a minimal configuration.
 *
 * This should be called during initialization (before real-time operation)
 * to trigger JIT compilation of CUDA kernels, avoiding first-call latency.
 *
 * @param handle Handle
 * @param stream CUDA stream
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t pusch_e2e_warmup(pusch_e2e_handle_t handle, cudaStream_t stream);

/**
 * Warm up the transform-precoded low-PAPR PUSCH path used by Msg3.
 *
 * This runs a bounded valid DFT-s-OFDM configuration during initialization so
 * first-use kernel setup and dynamic shared-memory attributes do not happen in
 * the OTA Msg3 timing window.
 *
 * @param handle Handle
 * @param stream CUDA stream
 * @param nof_prb Number of PRBs to warm, clamped internally to a valid value
 * @param nof_rx_ports Number of RX ports to warm, clamped internally to supported values
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t
pusch_e2e_warmup_transform_deprecoding(pusch_e2e_handle_t handle, cudaStream_t stream, int nof_prb, int nof_rx_ports);

/* ============================================================================
 * OPTIMIZED API - Uses fused FP16 kernels for maximum performance
 *
 * These functions use optimized kernel fusion strategies:
 * - Fused LSE + Frequency Interpolation with FP16 output
 * - Parallel processing of all DMRS symbols in single kernel
 * - On-the-fly time interpolation in E2E kernel (no separate pass)
 * - 50% memory bandwidth reduction via FP16 channel estimates
 *
 * Performance: ~2x speedup for CHest+EQ portion of pipeline
 * ============================================================================ */

/**
 * Process PUSCH with optimized fused FP16 kernels.
 *
 * This is the fastest GPU-resident PUSCH path, using:
 * - Single-kernel LSE + Freq interpolation with FP16 output
 * - Parallel DMRS symbol processing
 * - Fused time interpolation in E2E kernel
 *
 * @param handle Handle (must be configured)
 * @param d_grid_cbf16 Device pointer to grid [nof_ports, nof_symbols, nof_subcarriers] (cbf16)
 * @param d_llrs_half Output: Device pointer to FP16 LLRs [nof_data_re * mod_order]
 * @param d_re_indices Device pointer to data RE indices [nof_data_re] (int)
 * @param nof_data_re Number of data REs to process
 * @param stream CUDA stream
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t pusch_e2e_process_full_gpu_optimized(pusch_e2e_handle_t handle,
                                                      const void*        d_grid_cbf16,
                                                      void*              d_llrs_half,
                                                      const int*         d_re_indices,
                                                      int                nof_data_re,
                                                      cudaStream_t       stream);

/**
 * Process PUSCH MIMO with FP16 LLR output for GPU-resident decode.
 *
 * This path is the multi-layer counterpart of pusch_e2e_process_full_gpu_optimized:
 * it keeps descrambled LLRs in FP16 device memory using codeword order
 * [RE][layer][bit]. Currently supports 2, 3 and 4 layers.
 *
 * @param handle Handle (must be configured)
 * @param d_grid_cbf16 Device pointer to grid [nof_ports, nof_symbols, nof_subcarriers] (cbf16)
 * @param d_llrs_half Output: Device pointer to FP16 LLRs [nof_data_re * nof_layers * mod_order]
 * @param d_re_indices Device pointer to data RE indices [nof_data_re] (int)
 * @param nof_data_re Number of data REs to process
 * @param stream CUDA stream
 * @return NR_LDPC_SUCCESS on success
 */
nr_ldpc_status_t pusch_e2e_process_full_gpu_optimized_mimo_half(pusch_e2e_handle_t handle,
                                                                const void*        d_grid_cbf16,
                                                                void*              d_llrs_half,
                                                                const int*         d_re_indices,
                                                                int                nof_data_re,
                                                                cudaStream_t       stream);

/**
 * Set equalized symbol output buffers for external soft demapping.
 *
 * When non-null, the E2E kernel writes equalized symbols and per-RE/layer noise
 * variance to these buffers (in addition to standard LLR output).
 * Set both to NULL to disable (default).
 *
 * @param handle              Handle (must be configured)
 * @param d_eq_symbols_out    [nof_data_re] float2 output buffer, or NULL to disable
 * @param d_eq_noise_var_out  [nof_data_re] float output buffer, or NULL to disable
 */
void pusch_e2e_set_eq_output(pusch_e2e_handle_t handle, float2* d_eq_symbols_out, float* d_eq_noise_var_out);

/**
 * Returns the internal FP16 channel-estimate buffer for diagnostics.
 *
 * The optimized FP16 MIMO path stores estimates as
 * [dmrs_symbol][prb][rx_port][tx_layer][subcarrier_in_prb], with each element
 * encoded as CUDA half2 {real, imag}. The pointer remains owned by the handle.
 */
const void* pusch_e2e_get_estimates_fp16(pusch_e2e_handle_t handle);

#ifdef __cplusplus
}
#endif
