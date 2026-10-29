// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ocudu_ofh_compression_handle ocudu_ofh_compression_handle_t;

/// Details of the most recent CUDA runtime failure observed by a compression handle.
///
/// The string pointers are owned by the CUDA runtime or the compression backend and remain valid for the lifetime of
/// the process. A successful operation clears the error code and reports operation "none".
typedef struct {
  int         cuda_error_code;
  const char* operation;
  const char* error_name;
  const char* error_description;
} ocudu_ofh_compression_error_info_t;

enum { OCUDU_OFH_COMPRESSION_TYPE_NONE = 0, OCUDU_OFH_COMPRESSION_TYPE_BFP = 1 };

int ocudu_ofh_compression_available(void);
int ocudu_ofh_compression_create(ocudu_ofh_compression_handle_t** handle);
/// Preallocates device and pinned-host output workspaces used by device-grid compression to host buffers.
int ocudu_ofh_compression_reserve_host_buffer_compression(ocudu_ofh_compression_handle_t* handle,
                                                          unsigned                        max_output_bytes);
/// Preallocates the buffers and events used by asynchronous direct decompression.
int   ocudu_ofh_compression_reserve_direct_decompression(ocudu_ofh_compression_handle_t* handle,
                                                         unsigned                        max_input_bytes,
                                                         unsigned                        max_output_bytes);
void  ocudu_ofh_compression_destroy(ocudu_ofh_compression_handle_t* handle);
void* ocudu_ofh_compression_get_stream(ocudu_ofh_compression_handle_t* handle);
/// Returns 1 when all work enqueued on the handle has completed, 0 while work is pending and -1 on a CUDA error.
int ocudu_ofh_compression_query_completion(ocudu_ofh_compression_handle_t* handle);
int ocudu_ofh_compression_synchronize(ocudu_ofh_compression_handle_t* handle);
int ocudu_ofh_compression_get_last_error(const ocudu_ofh_compression_handle_t* handle,
                                         ocudu_ofh_compression_error_info_t*   error_info);

int ocudu_ofh_compress(ocudu_ofh_compression_handle_t* handle,
                       int                             compression_type,
                       void*                           output_bytes,
                       const void*                     input_cbf16,
                       unsigned                        nof_prbs,
                       unsigned                        data_width,
                       float                           iq_scaling);

int ocudu_ofh_decompress(ocudu_ofh_compression_handle_t* handle,
                         int                             compression_type,
                         void*                           output_cbf16,
                         const void*                     input_bytes,
                         unsigned                        nof_prbs,
                         unsigned                        data_width);

int ocudu_ofh_compress_device_grid(ocudu_ofh_compression_handle_t* handle,
                                   int                             compression_type,
                                   void*                           output_bytes,
                                   const void*                     input_grid_cbf16,
                                   unsigned                        nof_symbols,
                                   unsigned                        nof_subc,
                                   unsigned                        port,
                                   unsigned                        symbol,
                                   unsigned                        start_prb,
                                   unsigned                        nof_prbs,
                                   unsigned                        data_width,
                                   float                           iq_scaling);

int ocudu_ofh_decompress_to_device_grid(ocudu_ofh_compression_handle_t* handle,
                                        int                             compression_type,
                                        void*                           output_grid_cbf16,
                                        const void*                     input_bytes,
                                        unsigned                        nof_symbols,
                                        unsigned                        nof_subc,
                                        unsigned                        port,
                                        unsigned                        symbol,
                                        unsigned                        start_prb,
                                        unsigned                        nof_prbs,
                                        unsigned                        data_width);

int ocudu_ofh_decompress_to_device_grid_async(ocudu_ofh_compression_handle_t* handle,
                                              int                             compression_type,
                                              void*                           output_grid_cbf16,
                                              const void*                     input_bytes,
                                              unsigned                        nof_symbols,
                                              unsigned                        nof_subc,
                                              unsigned                        port,
                                              unsigned                        symbol,
                                              unsigned                        start_prb,
                                              unsigned                        nof_prbs,
                                              unsigned                        data_width);

int ocudu_ofh_decompress_to_device_prach_buffer_async(ocudu_ofh_compression_handle_t* handle,
                                                      int                             compression_type,
                                                      void*                           output_prach_cbf16,
                                                      unsigned                        output_offset_re,
                                                      const void*                     input_bytes,
                                                      unsigned                        input_start_re,
                                                      unsigned                        nof_re,
                                                      unsigned                        nof_prbs,
                                                      unsigned                        data_width);

int ocudu_ofh_compress_device_grid_ports(ocudu_ofh_compression_handle_t* handle,
                                         int                             compression_type,
                                         void*                           output_bytes,
                                         unsigned                        output_port_stride_bytes,
                                         const void*                     input_grid_cbf16,
                                         unsigned                        nof_symbols,
                                         unsigned                        nof_subc,
                                         unsigned                        first_port,
                                         unsigned                        nof_ports,
                                         unsigned                        symbol,
                                         unsigned                        start_prb,
                                         unsigned                        nof_prbs,
                                         unsigned                        data_width,
                                         float                           iq_scaling);

int ocudu_ofh_compress_device_grid_ports_to_host_buffers(ocudu_ofh_compression_handle_t* handle,
                                                         int                             compression_type,
                                                         void* const*                    output_host_buffers,
                                                         unsigned                        nof_output_buffers,
                                                         unsigned                        output_buffer_size_bytes,
                                                         const void*                     input_grid_cbf16,
                                                         unsigned                        nof_symbols,
                                                         unsigned                        nof_subc,
                                                         unsigned                        first_port,
                                                         unsigned                        nof_ports,
                                                         unsigned                        symbol,
                                                         unsigned                        start_prb,
                                                         unsigned                        nof_prbs,
                                                         unsigned                        data_width,
                                                         float                           iq_scaling);

int ocudu_ofh_compress_device_grid_ports_to_device(ocudu_ofh_compression_handle_t* handle,
                                                   int                             compression_type,
                                                   void*                           output_device_bytes,
                                                   unsigned                        output_port_stride_bytes,
                                                   const void*                     input_grid_cbf16,
                                                   unsigned                        nof_symbols,
                                                   unsigned                        nof_subc,
                                                   unsigned                        first_port,
                                                   unsigned                        nof_ports,
                                                   unsigned                        symbol,
                                                   unsigned                        start_prb,
                                                   unsigned                        nof_prbs,
                                                   unsigned                        data_width,
                                                   float                           iq_scaling);

int ocudu_ofh_compress_device_grid_ports_to_device_async(ocudu_ofh_compression_handle_t* handle,
                                                         int                             compression_type,
                                                         void*                           output_device_bytes,
                                                         unsigned                        output_port_stride_bytes,
                                                         const void*                     input_grid_cbf16,
                                                         unsigned                        nof_symbols,
                                                         unsigned                        nof_subc,
                                                         unsigned                        first_port,
                                                         unsigned                        nof_ports,
                                                         unsigned                        symbol,
                                                         unsigned                        start_prb,
                                                         unsigned                        nof_prbs,
                                                         unsigned                        data_width,
                                                         float                           iq_scaling);

int ocudu_ofh_compress_device_grid_symbol_batch(ocudu_ofh_compression_handle_t* handle,
                                                int                             compression_type,
                                                void*                           output_bytes,
                                                unsigned                        output_symbol_stride_bytes,
                                                unsigned                        output_port_stride_bytes,
                                                const void*                     input_grid_cbf16,
                                                unsigned                        nof_grid_symbols,
                                                unsigned                        nof_subc,
                                                unsigned                        first_port,
                                                unsigned                        nof_ports,
                                                unsigned                        first_symbol,
                                                unsigned                        nof_symbols,
                                                unsigned                        start_prb,
                                                unsigned                        nof_prbs,
                                                unsigned                        data_width,
                                                float                           iq_scaling);

int ocudu_ofh_compress_device_grid_symbol_batch_to_device(ocudu_ofh_compression_handle_t* handle,
                                                          int                             compression_type,
                                                          void*                           output_device_bytes,
                                                          unsigned                        output_symbol_stride_bytes,
                                                          unsigned                        output_port_stride_bytes,
                                                          const void*                     input_grid_cbf16,
                                                          unsigned                        nof_grid_symbols,
                                                          unsigned                        nof_subc,
                                                          unsigned                        first_port,
                                                          unsigned                        nof_ports,
                                                          unsigned                        first_symbol,
                                                          unsigned                        nof_symbols,
                                                          unsigned                        start_prb,
                                                          unsigned                        nof_prbs,
                                                          unsigned                        data_width,
                                                          float                           iq_scaling);

int ocudu_ofh_compress_device_grid_symbol_batch_to_host_buffers(ocudu_ofh_compression_handle_t* handle,
                                                                int                             compression_type,
                                                                void* const*                    output_host_buffers,
                                                                unsigned                        nof_output_buffers,
                                                                unsigned    output_buffer_size_bytes,
                                                                const void* input_grid_cbf16,
                                                                unsigned    nof_grid_symbols,
                                                                unsigned    nof_subc,
                                                                unsigned    first_port,
                                                                unsigned    nof_ports,
                                                                unsigned    first_symbol,
                                                                unsigned    nof_symbols,
                                                                unsigned    start_prb,
                                                                unsigned    nof_prbs,
                                                                unsigned    data_width,
                                                                float       iq_scaling);

int ocudu_ofh_compress_device_grid_symbol_batch_to_device_async(ocudu_ofh_compression_handle_t* handle,
                                                                int                             compression_type,
                                                                void*                           output_device_bytes,
                                                                unsigned    output_symbol_stride_bytes,
                                                                unsigned    output_port_stride_bytes,
                                                                const void* input_grid_cbf16,
                                                                unsigned    nof_grid_symbols,
                                                                unsigned    nof_subc,
                                                                unsigned    first_port,
                                                                unsigned    nof_ports,
                                                                unsigned    first_symbol,
                                                                unsigned    nof_symbols,
                                                                unsigned    start_prb,
                                                                unsigned    nof_prbs,
                                                                unsigned    data_width,
                                                                float       iq_scaling);

int ocudu_ofh_decompress_to_device_grid_ports(ocudu_ofh_compression_handle_t* handle,
                                              int                             compression_type,
                                              void*                           output_grid_cbf16,
                                              const void*                     input_bytes,
                                              unsigned                        input_port_stride_bytes,
                                              unsigned                        nof_symbols,
                                              unsigned                        nof_subc,
                                              unsigned                        first_port,
                                              unsigned                        nof_ports,
                                              unsigned                        symbol,
                                              unsigned                        start_prb,
                                              unsigned                        nof_prbs,
                                              unsigned                        data_width);

int ocudu_ofh_decompress_device_bytes_to_device_grid_ports(ocudu_ofh_compression_handle_t* handle,
                                                           int                             compression_type,
                                                           void*                           output_grid_cbf16,
                                                           const void*                     input_device_bytes,
                                                           unsigned                        input_port_stride_bytes,
                                                           unsigned                        nof_symbols,
                                                           unsigned                        nof_subc,
                                                           unsigned                        first_port,
                                                           unsigned                        nof_ports,
                                                           unsigned                        symbol,
                                                           unsigned                        start_prb,
                                                           unsigned                        nof_prbs,
                                                           unsigned                        data_width);

int ocudu_ofh_decompress_to_device_grid_symbol_batch(ocudu_ofh_compression_handle_t* handle,
                                                     int                             compression_type,
                                                     void*                           output_grid_cbf16,
                                                     const void*                     input_bytes,
                                                     unsigned                        input_symbol_stride_bytes,
                                                     unsigned                        input_port_stride_bytes,
                                                     unsigned                        nof_grid_symbols,
                                                     unsigned                        nof_subc,
                                                     unsigned                        first_port,
                                                     unsigned                        nof_ports,
                                                     unsigned                        first_symbol,
                                                     unsigned                        nof_symbols,
                                                     unsigned                        start_prb,
                                                     unsigned                        nof_prbs,
                                                     unsigned                        data_width);

int ocudu_ofh_decompress_device_bytes_to_device_grid_symbol_batch(ocudu_ofh_compression_handle_t* handle,
                                                                  int                             compression_type,
                                                                  void*                           output_grid_cbf16,
                                                                  const void*                     input_device_bytes,
                                                                  unsigned input_symbol_stride_bytes,
                                                                  unsigned input_port_stride_bytes,
                                                                  unsigned nof_grid_symbols,
                                                                  unsigned nof_subc,
                                                                  unsigned first_port,
                                                                  unsigned nof_ports,
                                                                  unsigned first_symbol,
                                                                  unsigned nof_symbols,
                                                                  unsigned start_prb,
                                                                  unsigned nof_prbs,
                                                                  unsigned data_width);

#ifdef __cplusplus
}
#endif
