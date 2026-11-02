// Replay the observed byte-range relationship through the unchanged RLC library.
#include "rlc_test_common.h"
#include "srsran/common/test_common.h"
#include "srsran/rlc/rlc_am_nr.h"
#include <cstdio>
#include <cstring>
using namespace srsran;
int main(int argc,char** argv)
{
  srslog::init();
  auto& logger=srslog::fetch_basic_logger("RLC_REPLAY");
  logger.set_level(srslog::basic_levels::info);
  rlc_am_tester tester(true,nullptr);timer_handler timers(8);
  rlc_am rlc(srsran_rat_t::nr,logger,1,&tester,&tester,&timers);
  auto cfg=rlc_config_t::default_rlc_am_nr_config(18);
  if(!rlc.configure(cfg))return 2;
  auto deliver=[&](unsigned so,unsigned length){
    uint8_t pdu[2048]={};
    // 18-bit SN617, middle segment, no poll bit; only payload content is synthetic.
    pdu[0]=0xb0;pdu[1]=0x02;pdu[2]=0x69;pdu[3]=so>>8;pdu[4]=so&255;
    std::printf("DELIVER SN617 [%u,%u]\n",so,so+length-1);std::fflush(stdout);
    rlc.write_pdu(pdu,length+5);
  };
  if(argc>1 && std::strcmp(argv[1],"outer-first")==0){deliver(656,109);deliver(684,12);}
  else {deliver(684,12);deliver(656,109);}
  for(unsigned i=0;i<100;i++)timers.step_all();
  auto* rx=dynamic_cast<rlc_am_nr_rx*>(rlc.get_rx());
  rlc_am_nr_status_pdu_t status(rlc_am_nr_sn_size_t::size18bits);
  std::puts("GENERATE STATUS");std::fflush(stdout);
  rx->get_status_pdu(&status,4096);
  std::puts("STATUS COMPLETED");srslog::flush();return 0;
}
