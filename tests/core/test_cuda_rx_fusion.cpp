#include "ocudu_gpu_channel/processing.h"
#include <array>
#include <bit>
#include <cmath>
#include <cstdlib>
#include <iostream>

void require(bool ok, const char* what) {
  if (!ok) { std::cerr << what << '\n'; std::exit(1); }
}

int main()
{
  for (const bool zero_copy : {false, true}) {
    auto cfg = ocg::load_config_file(OCG_FUSION_FIXTURE);
    cfg.runtime.backend = ocg::Backend::Cuda;
    cfg.runtime.cuda_host_memory = zero_copy ? ocg::CudaHostMemory::ZeroCopy : ocg::CudaHostMemory::Copy;
    ocg::ModelConfig rx;
    rx.id = "receiver";
    rx.chain = {{.type=ocg::ModelStepType::Gain, .params={{"gain_db",1.3}}},
                {.type=ocg::ModelStepType::Cfo, .params={{"cfo_hz",125.0}}},
                {.type=ocg::ModelStepType::Awgn, .params={{"noise_power",0.001}}},
                {.type=ocg::ModelStepType::Phase, .params={{"phase_rad",0.21}}}};
    cfg.models.emplace(rx.id,rx);
    for (auto& device : cfg.devices) if (device.id.starts_with("ue0_")) device.rx_model=rx.id;
    setenv("OCG_CUDA_FUSE_RX","0",1);
    auto separate=ocg::create_channel_processor(cfg);
    setenv("OCG_CUDA_FUSE_RX","1",1);
    auto fused=ocg::create_channel_processor(cfg);
    unsetenv("OCG_CUDA_FUSE_RX");
    const auto topology=ocg::resolve_topology(cfg);
    std::uint64_t sequence=0, compared=0;
    for (unsigned iteration=0; iteration<32; ++iteration) {
      const std::array<std::size_t,8> counts{1,23039,5,3072,23,23040,7,257};
      const auto count=counts[iteration%counts.size()];
      std::array<ocg::IqBuffer,2> input{ocg::IqBuffer(count),ocg::IqBuffer(count)};
      for (unsigned tx=0; tx<2; ++tx) for (std::size_t i=0; i<count; ++i)
        input[tx][i]={static_cast<float>(std::sin((sequence+i+tx*17)*.013)),
                      static_cast<float>(std::cos((sequence+i+tx*23)*.017))};
      std::vector<ocg::SuperpositionInput> lanes;
      for (const auto& lane : topology.lanes) if (lane.dst_node=="ue0")
        lanes.push_back({.link_key=lane.key,.model=ocg::find_model(cfg,lane.model_id),
                        .samples=input[lane.src_device=="gnb0_p0"?0:1],
                        .rx_port=lane.rx_port,.tx_port=lane.tx_port});
      std::array<ocg::IqBuffer,2> old_out{ocg::IqBuffer(count),ocg::IqBuffer(count)};
      std::array<ocg::IqBuffer,2> new_out{ocg::IqBuffer(count),ocg::IqBuffer(count)};
      std::array<std::span<ocg::IqSample>,2> old_rows{old_out[0],old_out[1]}, new_rows{new_out[0],new_out[1]};
      if (iteration==13) {
        require(separate->reset_receiver_noise("ue0"),"separate noise reset");
        require(fused->reset_receiver_noise("ue0"),"fused noise reset");
      }
      const auto* model=iteration>=24?nullptr:&cfg.models.at(rx.id);
      separate->process_superposition("ue0",lanes,model,23040000,old_rows);
      fused->process_superposition("ue0",lanes,model,23040000,new_rows);
      require(separate->last_timings().used_device_channel && fused->last_timings().used_device_channel,
              "fusion test must exercise the device channel");
      for (unsigned row=0; row<2; ++row) for (std::size_t i=0; i<count; ++i) {
        const auto a=old_out[row][i], b=new_out[row][i];
        if (std::bit_cast<std::uint32_t>(a.i)!=std::bit_cast<std::uint32_t>(b.i) ||
            std::bit_cast<std::uint32_t>(a.q)!=std::bit_cast<std::uint32_t>(b.q)) {
          std::cerr<<"mismatch zero_copy="<<zero_copy<<" iteration="<<iteration<<" row="<<row<<" sample="<<i<<'\n';
          return 1;
        }
        ++compared;
      }
      sequence+=count;
    }
    std::cout<<"receiver fusion bit-exact zero_copy="<<zero_copy<<" samples="<<compared<<'\n';
  }
}
