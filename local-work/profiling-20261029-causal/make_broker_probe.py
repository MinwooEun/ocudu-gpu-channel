from pathlib import Path
p=Path(__file__).parent;s=(p.parent/'profiling-20261028/src/src/broker.cpp').read_text()
s='#include <condition_variable>\n'+s
s=s.replace('  bool spin = false;','  bool producer_notify = false;\n  bool rep_notify = false;\n  bool spin = false;',1)
s=s.replace('  BrokerDiagKnobs knobs;','  BrokerDiagKnobs knobs;\n  knobs.producer_notify = std::getenv("OCG_CAUSAL_PRODUCER_NOTIFY") != nullptr;\n  knobs.rep_notify = std::getenv("OCG_CAUSAL_REP_NOTIFY") != nullptr;',1)
s=s.replace('  std::mutex rx_mutex;','  std::mutex rx_mutex;\n  std::condition_variable rx_ready;',1)
s=s.replace('          out.rx_slots.push_back(count);','          out.rx_slots.push_back(count);\n          if (knobs.rep_notify) out.rx_ready.notify_one();',1)
s=s.replace('          wait_tick(knobs, t_pop_start);','''          if (knobs.rep_notify) {
            std::unique_lock<std::mutex> lock(port.rx_mutex);
            port.rx_ready.wait_for(lock, std::chrono::milliseconds(1), [&] {
              return !port.rx_slots.empty() || stop_requested.load();
            });
          } else {
            wait_tick(knobs, t_pop_start);
          }''',1)
s=s.replace('  std::mutex ring_mutex;', '  std::mutex ring_mutex;\n  std::condition_variable tx_ready;',1)
s=s.replace('            trace.add(HopEvent::PullRingPushed, pending);','            if (knobs.producer_notify) dev.tx_ready.notify_all();\n            trace.add(HopEvent::PullRingPushed, pending);',1)
s=s.replace('            std::size_t common = node.batch;','            PortRuntime* empty_source = nullptr;\n            std::uint64_t empty_cursor = 0;\n            std::size_t common = node.batch;',1)
s=s.replace('              common = std::min<std::size_t>(common, static_cast<std::size_t>(avail));','              if (avail == 0 && !empty_source) { empty_source = &src; empty_cursor = cur; }\n              common = std::min<std::size_t>(common, static_cast<std::size_t>(avail));',1)
s=s.replace('            wait_tick(knobs, wait_start);','''            if (knobs.producer_notify && empty_source) {
              std::unique_lock<std::mutex> lock(empty_source->ring_mutex);
              empty_source->tx_ready.wait_for(lock, std::chrono::milliseconds(1), [&] {
                return empty_source->tx_ring.next_sequence() > empty_cursor || stop_requested.load();
              });
            } else {
              wait_tick(knobs, wait_start);
            }''',1)
(p/'broker-probe.cpp').write_text(s)
