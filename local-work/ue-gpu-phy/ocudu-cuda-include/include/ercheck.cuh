// SPDX-FileCopyrightText: Copyright (C) 2021-2026 DeepSig Inc
// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI
// Portions of this file may implement 3GPP specifications, which may be subject to additional licensing requirements.

/**
 * @file ercheck.cuh
 * @brief Macros implementing CUDA error checking
 * 
 */

#pragma once
#include <cstdio>

// Logs the active CUDA error to stderr
#define LOGERROR(call, errorstring, f, lno)             \
    do {                                                \
        std::fprintf (stderr,                           \
        "CUDA error %s at %s:%d -- %s\n",               \
        call,                                           \
        f,                                              \
        lno,                                            \
        errorstring);                                          \
    } while(0)


// Checks NVIDIA CUDA error returned by argument 'call' and returns NR_LDPC_ERROR_CUDA_FAILED if it failed
//
// Example:
//
// nr_ldpc_status_t myfunction()
// {
//     ...
//     CHECK_NVFAILURE_LDPC(cudaMemsetAsync(ptr, 0, bytes, stream));
//     return NR_LDPC_SUCCESS;
// }
//
#define CHECK_NVFAILURE_LDPC(call)                      \
    do {                                                \
        cudaError_t err_ = (call);                      \
        if (err_ != cudaSuccess) {                      \
            LOGERROR(#call, cudaGetErrorString(err_),   \
                __FILE__, __LINE__);                    \
            return NR_LDPC_ERROR_CUDA_FAILED;           \
        }                                               \
    } while (0)

// Checks NVIDIA CUDA error returned by argument 'call' and returns Boolean 'false' if it failed
//
// Example:
//
// bool myfunction()
// {
//     ...
//     CHECK_NVFAILURE_BOOL(cudaMemsetAsync(ptr, 0, bytes, stream));
//     return true; // success
// }
//
#define CHECK_NVFAILURE_BOOL(call)                      \
    do {                                                \
        cudaError_t err_ = (call);                      \
        if (err_ != cudaSuccess) {                      \
            LOGERROR(#call, cudaGetErrorString(err_),   \
                __FILE__, __LINE__);                    \
            return false;           \
        }                                               \
    } while (0)

// Checks NVIDIA CUDA error returned by argument 'call' and optionally returns a value if it failed
//
// Example 1:
//
// void myfunction()
// {
//     ...
//     CHECK_NVFAILURE(cudaMemsetAsync(ptr, 0, bytes, stream));
// }
//
// Example 2:
//
// bool myfunction()
// {
//     ...
//     CHECK_NVFAILURE(cudaMemsetAsync(ptr, 0, bytes, stream), false);
//     return true; // success
// }
//
// Example 3:
//
// int myfunction()
// {
//     ...
//     CHECK_NVFAILURE(cudaMemsetAsync(ptr, 0, bytes, stream), -1);
//     return 0; // success
// }
//
#define CHECK_NVFAILURE(call,...)                       \
    do {                                                \
        cudaError_t err_ = (call);                      \
        if (err_ != cudaSuccess) {                      \
            LOGERROR(#call, cudaGetErrorString(err_),   \
                __FILE__, __LINE__);                    \
            return __VA_ARGS__;                         \
        }                                               \
    } while (0)
