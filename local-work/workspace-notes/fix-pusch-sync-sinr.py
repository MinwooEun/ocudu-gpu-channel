from pathlib import Path
import sys
root=Path('/home/hyunsoo/ocudu-native-workspace/src/ocudu-cuda')
if sys.argv[1]=='test':
 p=root/'tests/integrationtests/phy/upper/channel_processors/pusch_gpu_cpu_comparison_test.cpp';s=p.read_text()
 s=s.replace('static bool live_cfo_regression = false;', 'static bool live_cfo_regression = false;\nstatic bool sync_sinr_regression = false;')
 s=s.replace('                                          "gpu",','                                          sync_sinr_regression ? "gpu-demod" : "gpu",')
 s=s.replace('"R:P:S:N:Lh"','"R:P:S:N:LHh"')
 s=s.replace("      case 'L':", "      case 'H':\n        sync_sinr_regression = true;\n        break;\n      case 'L':")
 anchor='      fmt::print("CFO interpolation regression: PASS (CPU/GPU CRC and payload parity)\\n");'
 assert s.count(anchor)==1
 s=s.replace(anchor,'''      if (sync_sinr_regression) {
        for (const auto& r : all_results) {
          report_error_if_not(r.cpu_sinr_stats.get_nof_observations() == nof_repetitions &&
                              r.gpu_sinr_stats.get_nof_observations() == nof_repetitions &&
                              std::abs(r.gpu_sinr_stats.get_mean() - r.cpu_sinr_stats.get_mean()) <= 0.5F,
                              "Synchronous GPU post-equalization SINR disagrees with CPU");
        }
        fmt::print("Synchronous SINR regression: PASS (GPU demodulation, host-visible decode)\\n");
      }
'''+anchor)
 s=s.replace('    print_header();','    report_error_if_not(!sync_sinr_regression || live_cfo_regression, "-H requires -L");\n    print_header();')
 s=s.replace('  fmt::print("\\t-L', '  fmt::print("\\t-H       Exercise synchronous GPU SINR reporting with host-visible decoding (requires -L).\\n");\n  fmt::print("\\t-L')
 p.write_text(s)
 p=root/'tests/integrationtests/phy/upper/channel_processors/CMakeLists.txt';s=p.read_text();a='add_test(pusch_gpu_cpu_cfo_interpolation_test pusch_gpu_cpu_comparison_test -L -P 27 -R 10 -S 30 -N 1)';assert s.count(a)==1;s=s.replace(a,a+'\nadd_test(pusch_gpu_cpu_sync_sinr_test pusch_gpu_cpu_comparison_test -L -H -P 27 -R 10 -S 30 -N 1)');p.write_text(s)
elif sys.argv[1]=='fix':
 p=root/'lib/phy/upper/channel_processors/pusch/pusch_demodulator_gpu_impl.cpp';s=p.read_text();old='''  // Match the host-facing CPU goodness metric by preferring the
  // post-equalization EVM-derived SINR whenever the kernel provides it.
  if (std::isfinite(gpu_evm) && gpu_evm > 0.0f) {
    stats.sinr_dB.emplace(-20.0f * std::log10(gpu_evm));
  } else if (std::isfinite(gpu_sinr_db)) {''';new='''  // Use the same post-equalization noise-variance SINR as the CPU and
  // deferred resident path. EVM is a separate metric; substituting it here
  // inflates scheduler SINR for synchronous/UCI-bearing transmissions.
  if (std::isfinite(gpu_sinr_db)) {''';assert s.count(old)==1;p.write_text(s.replace(old,new))
else:raise ValueError('expected test or fix')
