#include "ocudu_gpu_channel/mutable_params.h"

#include "ocudu_gpu_channel/config.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <string>

namespace ocg {

namespace {

double param_or(const ModelStep& step, const std::string& name, double fallback)
{
  const auto it = step.params.find(name);
  return it == step.params.end() ? fallback : it->second;
}

}  // namespace

MutableParams populate_mutable_params_from_yaml(
    const ModelConfig& model,
    double reference_power,
    std::uint64_t sample_rate_hz)
{
  (void)sample_rate_hz;   // not used in v1; kept for signature symmetry

  MutableParams out;

  // Scan chain for the first PathLoss / Cfo / Awgn step.
  for (const auto& step : model.chain) {
    switch (step.type) {
      case ModelStepType::PathLoss:
        out.path_loss_db = static_cast<float>(param_or(step, "path_loss_db", 0.0));
        break;
      case ModelStepType::Cfo:
      case ModelStepType::Phase:
        out.cfo_hz = static_cast<float>(param_or(step, "cfo_hz", 0.0));
        break;
      case ModelStepType::Awgn: {
        // v1-fin-A: only the YAML `snr_db` value is mutable from the
        // control plane. Explicit `noise_power` stays an absolute YAML-
        // only knob — the runtime exposes dB-relative SNR, not absolute
        // power. If the chain step uses noise_power, awgn_snr_db keeps
        // its struct default; the backend's AWGN path detects the
        // explicit noise_power and bypasses live.
        (void)reference_power;
        if (step.params.find("noise_power") == step.params.end()) {
          out.awgn_snr_db = static_cast<float>(param_or(step, "snr_db", 60.0));
        }
        break;
      }
      case ModelStepType::Tdl:
        // Tap params handled below from chain[0].taps[0].
        break;
      case ModelStepType::Gain:
        // A constant; not a runtime-mutable parameter.
        break;
    }
  }

  // Leading tap of the leading tdl step (if present).
  if (!model.chain.empty() && model.chain.front().type == ModelStepType::Tdl) {
    const auto& leading = model.chain.front();
    if (!leading.taps.empty()) {
      const auto& tap0 = leading.taps.front();
      out.tap0_delay_samples = static_cast<float>(tap0.delay_samples);
      out.tap0_gain_db       = static_cast<float>(tap0.gain_db);
      out.tap0_phase_rad     = static_cast<float>(tap0.phase_rad);
      out.los_k_db           = static_cast<float>(tap0.los_k_db);
    }
  }

  return out;
}

}  // namespace ocg
