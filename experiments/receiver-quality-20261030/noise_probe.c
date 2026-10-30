/* Diagnostic mutation: isolate the effect of DMRS residual noise on equalization. */
#include "srsran/phy/ch_estimation/dmrs_sch.h"
#include <stdlib.h>
#include <stdio.h>
static int mode=-1;
int __real_srsran_dmrs_sch_estimate(srsran_dmrs_sch_t*,const srsran_slot_cfg_t*,const srsran_sch_cfg_nr_t*,const srsran_sch_grant_nr_t*,const cf_t*,srsran_chest_dl_res_t*);
int __wrap_srsran_dmrs_sch_estimate(srsran_dmrs_sch_t* q,const srsran_slot_cfg_t* slot,const srsran_sch_cfg_nr_t* cfg,const srsran_sch_grant_nr_t* grant,const cf_t* symbols,srsran_chest_dl_res_t* res) {
 if(mode<0){const char* s=getenv("OCG_DIAG_ZERO_NOISE");mode=(s&&s[0]=='1');fprintf(stderr,"event=diag_dmrs_noise zero=%d\n",mode);}
 int r=__real_srsran_dmrs_sch_estimate(q,slot,cfg,grant,symbols,res);
 if(r==0 && mode)res->noise_estimate=0.0f;
 return r;
}
