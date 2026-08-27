#pragma once

#include "ocudu_gpu_channel/config.h"
#include "ocudu_gpu_channel/processing.h"
#include <chrono>
#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>

namespace ocg {

struct BrokerStats {
  std::uint64_t tx_pulls = 0;
  std::uint64_t rx_requests = 0;
  std::uint64_t rx_starvations = 0;
  std::uint64_t tx_queue_overflows = 0;
  std::uint64_t tx_sequence_gaps = 0;
  std::uint64_t zmq_errors = 0;
};

// Bounded wire-boundary capture, off unless a directory is set.
//
// Each port records the first `samples_per_port` IQ samples it pulled off its
// peer's TX, and the first it replied with on its own RX, writing both once at
// shutdown. Nothing is recorded from inside the channel call: these are the two
// wires, so an independent checker can verify that what left the broker is the
// DECLARED matrix applied to what entered it. Judging a matrix from the
// broker's own accounting would only restate the broker's opinion of itself.
//
// The buffers are preallocated to their limit and each is touched by exactly
// one thread (the port's puller, the port's REP worker), so the capture adds a
// bounds check and a copy to each wire operation and no allocation or I/O.
struct WireCaptureConfig {
  std::string directory;             // empty = capture disabled
  std::size_t samples_per_port = 0;  // per port, per direction
  // Samples to let past before recording starts, per port per direction. A
  // radio's first samples are its ramp-up -- an OCUDU gNB emits silence until
  // its lower PHY is radiating -- and a window of silence measures nothing.
  // Both directions skip the same count, so a captured output row still lines
  // up sample-for-sample with the captured input columns.
  std::size_t skip_samples = 0;
  // Anchor the window to activity instead of to a constant.
  //
  // skip_samples is counted in SAMPLE time, but the traffic a live gate needs
  // to observe is scheduled in WALL time after the UE attaches, and the two
  // clocks do not share an origin: the broker cannot advance a node until
  // every incoming lane has data, so sample time does not start until the last
  // radio connects, and it then runs below real time under load. A constant
  // therefore lands somewhere different on every run. Naming the port whose
  // transmit input arms the capture makes the window start from the first
  // sample that radio actually sent, on every run.
  //
  // Empty = disabled, and skip_samples is used unchanged.
  //
  // ALIGNMENT IS NOT PROVEN FOR MULTI-PORT CAPTURES. Every port applies the one
  // armed offset to its OWN sample counter, and those counters are not equal:
  // measured on a live run, gnb0_p0 stood at 239,823,660 while ue0_p0 stood at
  // 239,846,412 -- about one batch apart. A shared offset therefore preserves
  // alignment only to the extent the counters already agree, which is an
  // assumption, not a guarantee.
  //
  // Observed 2026-08-27 on the CSI-on 4T4R capture taken with a trigger on
  // ue0_p0: the uplink rows verified (4.6e-05 against 1e-04) while the
  // downlink row did not (max |y - Hx| = 0.93). 93.5% of samples matched
  // exactly and the 6.5% that did not is the downlink duty cycle, i.e. exactly
  // the samples carrying signal, and no lag from -8 to +8 batches collapsed
  // it. The uplink pair involves the trigger port's own counter; the downlink
  // pair does not. That is consistent with this offset being right for the port
  // it was measured on and wrong for others, and it has not been isolated.
  //
  // test_broker's scenario_capture_trigger covers a SINGLE port only. Until a
  // multi-port alignment test exists, score matrix captures with the fixed
  // skip, not the trigger. Tracked as V8 in RANK1_REVIEW_MILESTONES.md.
  std::string trigger_port;
  // Samples to let past after the trigger fires. Sized to cover the skew
  // between ports so that none of them has already passed the armed offset
  // when it is published.
  std::size_t trigger_margin_samples = 0;
};

class Broker {
public:
  explicit Broker(TopologyConfig config);

  // Must be called before run(); ignored once the workers are up.
  void set_wire_capture(WireCaptureConfig capture);
  // Let a node advance while a DECLARED incoming lane has never delivered a
  // sample, treating that lane as silence until its peer speaks.
  //
  // Off by default, and deliberately so. Without it a node waits on
  // min(available) across every declared lane, and a peer that has never
  // connected is indistinguishable from one that is briefly caught up -- so a
  // cell cannot run until the LAST radio is up, and the radios that are
  // already up cannot attach by construction. With it, the cell runs from the
  // first radio. What it does NOT fix is the sink side, where a port whose
  // radio has not connected still accumulates output; see V3 in
  // RANK1_REVIEW_MILESTONES.md.
  void set_admit_cold_sources(bool admit);

  BrokerStats run(std::chrono::milliseconds duration);

  // Phase 3 C3: expose per-link BrokerLinkControl pointers so the ControlServer
  // can resolve link_ids in incoming REQs. Forwarded from the underlying
  // ChannelProcessor. Map ownership is transferred to the caller; pointers
  // remain valid for the life of this Broker.
  std::unordered_map<std::string, BrokerLinkControl*> collect_control_links();

private:
  TopologyConfig config_;
  WireCaptureConfig capture_;
  bool admit_cold_sources_ = false;
  std::unique_ptr<ChannelProcessor> processor_;
};

} // namespace ocg
