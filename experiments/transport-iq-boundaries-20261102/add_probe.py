import pathlib,sys,difflib
src=pathlib.Path(sys.argv[1]);dst=pathlib.Path(sys.argv[2]);s=src.read_text();old=s
needle='  const auto run_producer = [&](std::size_t n) {'
s=s.replace(needle,'''  std::atomic<long long> boundary_window_start{0};
  const char* boundary_epoch = std::getenv("OCG_WINDOW_EPOCH_FILE");
  const char* boundary_counters = std::getenv("OCG_COUNTER_DIR");
  const bool boundary_probe = boundary_epoch && boundary_counters;
  const long long boundary_duration = std::getenv("OCG_WINDOW_NS") ? std::stoll(std::getenv("OCG_WINDOW_NS")) : 0;
'''+needle)
needle='      long long previous_loop_end_ns = 0;'
s=s.replace(needle,needle+'''
      std::uint64_t probe_calls=0,probe_samples=0,probe_rebases=0,probe_debt=0,probe_cpu=0,probe_over=0;
      long long probe_first=0,probe_last=0;
      double probe_room=0,probe_data=0,probe_read=0,probe_process=0,probe_max=0;
      std::array<std::uint64_t,4001> probe_hist{};
''')
s=s.replace('const auto process_cpu_start = room_diag_on ? thread_cpu_ns() : 0;', 'const auto process_cpu_start = (room_diag_on || boundary_probe) ? thread_cpu_ns() : 0;')
needle='        const auto due = pacer.charge(rate_now, count);'
s=s.replace(needle,needle+'''
        const auto probe_shift = have_pace_due && due>expected_pace_due ?
          std::chrono::duration_cast<std::chrono::nanoseconds>(due-expected_pace_due).count() : 0;
''')
needle='        const auto t_commit_start = std::chrono::steady_clock::now();'
assert s.count(needle)==1;s=s.replace(needle,needle+'\n        const auto probe_process_cpu = boundary_probe ? thread_cpu_ns()-process_cpu_start : 0;')
needle='        diag.last_samples.store(count);'
assert s.count(needle)==1;s=s.replace(needle,'''        if (boundary_probe) {
          const auto now_ns=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
          const auto begin_ns=boundary_window_start.load(std::memory_order_relaxed);
          if (begin_ns && now_ns>=begin_ns && now_ns<begin_ns+boundary_duration) {
            ++probe_calls;probe_samples+=count;if(!probe_first)probe_first=now_ns;probe_last=now_ns;
            if(probe_shift>0){++probe_rebases;probe_debt+=probe_shift;}
            probe_cpu+=probe_process_cpu;probe_room+=room_us;probe_data+=data_us;probe_read+=read_us;probe_process+=process_us;
            probe_max=std::max(probe_max,process_us);++probe_hist[std::min<std::size_t>(4000,static_cast<std::size_t>(process_us/10))];
            if(process_us*1000>batch_duration.count())++probe_over;
          }
        }
'''+needle)
needle='      if (room_diag_on) {\n        std::ofstream po('
assert s.count(needle)==1
s=s.replace(needle,'''      if(boundary_probe){
        std::ofstream probe_out(std::string(boundary_counters)+"/"+node.id+".csv");
        if(!probe_out)throw std::runtime_error("boundary counter output failed");
        std::uint64_t acc=0,p99_bin=0;
        for(std::size_t i=0;i<probe_hist.size();++i){acc+=probe_hist[i];if(acc>=static_cast<std::uint64_t>(std::ceil(probe_calls*.99))){p99_bin=i;break;}}
        probe_out<<"node,calls,samples,rebases,debt_ns,process_cpu_ns,room_us_sum,data_us_sum,read_us_sum,process_us_sum,process_p99_upper_us,process_max_us,process_over_budget,first_ns,last_ns\\n";
        probe_out<<node.id<<','<<probe_calls<<','<<probe_samples<<','<<probe_rebases<<','<<probe_debt<<','<<probe_cpu<<','<<probe_room<<','<<probe_data<<','<<probe_read<<','<<probe_process<<','<<(p99_bin+1)*10<<','<<probe_max<<','<<probe_over<<','<<probe_first<<','<<probe_last<<'\\n';
      }
'''+needle)
needle='  while (!stop_requested.load()) {\n    const auto now = std::chrono::steady_clock::now();'
assert s.count(needle)==1
s=s.replace(needle,needle+'''
    if(boundary_probe && boundary_window_start.load(std::memory_order_relaxed)==0){
      std::ifstream epoch_input(boundary_epoch);long long epoch_ns=0;if(epoch_input>>epoch_ns)boundary_window_start.store(epoch_ns,std::memory_order_relaxed);
    }
''')
assert s!=old;dst.write_text(s);dst.with_suffix('.patch').write_text(''.join(difflib.unified_diff(old.splitlines(True),s.splitlines(True),fromfile='a/src/broker.cpp',tofile='b/src/broker.cpp')))
