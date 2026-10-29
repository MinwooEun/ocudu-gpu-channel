#include "ocudu_gpu_channel/cpu_backend.h"
#include <array>
#include <atomic>
#include <cstdint>
#include <vector>
#include <barrier>
#include <bit>
#include <iostream>
#include <mutex>
#include <set>
#include <stdexcept>
#include <thread>

namespace {
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }

ocg::TopologyConfig fixture(bool fading, bool los)
{
  ocg::TopologyConfig c;
  c.runtime.backend = ocg::Backend::Cpu;
  c.runtime.batch_samples_auto = false;
  c.runtime.batch_samples = 137;
  c.runtime.queue_samples = 4096;
  c.devices = {
      {.id="a", .sample_rate_hz=23040000, .tx_endpoint="txa", .rx_endpoint="rxa"},
      {.id="b", .sample_rate_hz=23040000, .tx_endpoint="txb", .rx_endpoint="rxb"},
      {.id="c", .sample_rate_hz=23040000, .tx_endpoint="txc", .rx_endpoint="rxc"}};
  ocg::ModelConfig model;
  model.id = "channel";
  ocg::ModelStep tdl;
  tdl.type = ocg::ModelStepType::Tdl;
  tdl.taps = {{.delay_samples=0, .gain_db=-2, .phase_rad=0.3, .is_los=los, .los_k_db=6, .los_angle_rad=0.2},
              {.delay_samples=7.25, .gain_db=-8, .phase_rad=-0.7},
              {.delay_samples=34.5, .gain_db=-11, .phase_rad=1.2}};
  tdl.taps_declared = true;
  tdl.fading_enabled = fading;
  tdl.fading_f_d_max_hz = 100;
  model.chain = {tdl,
      {.type=ocg::ModelStepType::Cfo, .params={{"cfo_hz",125}}},
      {.type=ocg::ModelStepType::Awgn, .params={{"noise_power",0.00001}}}};
  c.models.emplace(model.id, model);
  c.links = {{.from="a", .to="b", .model="channel"},
             {.from="c", .to="b", .model="channel"},
             {.from="b", .to="a", .model="channel"},
             {.from="b", .to="c", .model="channel"}};
  const auto errors = ocg::validate_config(c);
  for (const auto& error : errors) std::cerr << error << '\n';
  require(errors.empty(), "fixture validates");
  return c;
}

void backend_checks(bool fading, bool los)
{
  auto c = fixture(fading, los);
  ocg::CpuChannelProcessor serial, parallel;
  serial.prepare(c);
  parallel.prepare(c);
  auto sc = serial.collect_control_links(), pc = parallel.collect_control_links();
  const auto topology = ocg::resolve_topology(c);
  std::uint64_t fingerprint = 14695981039346656037ULL;
  for (unsigned batch = 0; batch < 20; ++batch) {
    const std::size_t count = std::array<std::size_t,4>{1,7,137,509}[batch % 4];
    if (batch == 5 || batch == 12) {
      for (auto* controls : {&sc, &pc}) {
        for (auto& [key, control] : *controls) {
          control->shadow.tap0_gain_db = -4;
          control->shadow.tap0_phase_rad = 0.8;
          // A profile replacement exercises history resets while workers join.
          if (batch == 12) {
            control->shadow_profile.n_taps = 3;
            control->shadow_profile.fading_enabled = fading;
            control->shadow_profile.fading_f_d_max_hz = 100;
            for (int k = 0; k < 3; ++k) {
              control->shadow_profile.taps[k] = c.models.at("channel").chain[0].taps[k];
              control->shadow_profile.taps[k].delay_samples += 2;
            }
            control->profile_pending = true;
          }
          control->seqno.fetch_add(1, std::memory_order_release);
        }
      }
    }
    std::array<ocg::IqBuffer,3> input;
    for (unsigned port=0;port<3;++port) {
      input[port].resize(count);
      for (std::size_t i=0;i<count;++i) input[port][i] = {
          float((i+batch+port)%31)/31, float((2*i+batch+port)%23)/23};
    }
    std::array<std::vector<ocg::SuperpositionInput>,3> lanes;
    for (const auto& lane : topology.lanes) {
      auto index = static_cast<std::size_t>(lane.dst_node[0]-'a');
      const auto source = static_cast<std::size_t>(lane.src_device[0]-'a');
      lanes[index].push_back({.link_key=lane.key, .model=ocg::find_model(c,lane.model_id),
          .samples=input[source], .rx_port=lane.rx_port, .tx_port=lane.tx_port});
    }
    std::array<ocg::IqBuffer,3> expected{ocg::IqBuffer(count),ocg::IqBuffer(count),ocg::IqBuffer(count)};
    std::array<ocg::IqBuffer,3> actual{ocg::IqBuffer(count),ocg::IqBuffer(count),ocg::IqBuffer(count)};
    for (int i=0;i<3;++i) serial.process_superposition(std::string(1, static_cast<char>('a'+i)),lanes[i],nullptr,23040000,std::span(expected[i]));
    // Distinct receiving nodes share one pool without sharing sample outputs.
    std::exception_ptr errors[3];
    std::thread t[3];
    for (int i=0;i<3;++i) t[i]=std::thread([&,i] {
      try { parallel.process_superposition(std::string(1, static_cast<char>('a'+i)),lanes[i],nullptr,23040000,std::span(actual[i])); }
      catch (...) { errors[i]=std::current_exception(); }
    });
    for (auto& worker:t) worker.join();
    for (auto& error:errors) if(error) std::rethrow_exception(error);
    for (int row=0;row<3;++row) for(std::size_t i=0;i<count;++i) {
      for (float value : {expected[row][i].i, expected[row][i].q}) {
        fingerprint ^= std::bit_cast<std::uint32_t>(value);
        fingerprint *= 1099511628211ULL;
      }
      require(std::bit_cast<std::uint32_t>(expected[row][i].i)==std::bit_cast<std::uint32_t>(actual[row][i].i) &&
              std::bit_cast<std::uint32_t>(expected[row][i].q)==std::bit_cast<std::uint32_t>(actual[row][i].q),
              "parallel CPU must match serial IQ bit-for-bit across batches and updates");
    }
  }
  std::cout << "IQ fingerprint fading=" << fading << " los=" << los << ": " << fingerprint << '\n';
}
}
int main()
{
  try {
    backend_checks(false,false);
    backend_checks(true,false);
    backend_checks(true,true);
    std::cout << "24-worker execution and serial/parallel CPU IQ parity passed\n";
  } catch(const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
