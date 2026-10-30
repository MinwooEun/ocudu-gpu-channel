#include "srsran/phy/utils/vector.h"
#include <stdio.h>
#include <complex.h>
#include <math.h>
int main(int argc,char**argv){if(argc!=2)return 2;FILE*f=fopen(argv[1],"rb");if(!f)return 3;cf_t x[570] __attribute__((aligned(64)));int k=0;puts("k,sync,rsrp,epre,residual,snr_db");while(fread(x,sizeof(cf_t),570,f)==570){float sync=srsran_vec_estimate_frequency(x,570);srsran_vec_apply_cfo(x,sync,x,570);cf_t corr=srsran_vec_acc_cc(x,570)/570.0f;float rsrp=crealf(corr)*crealf(corr)+cimagf(corr)*cimagf(corr);float epre=srsran_vec_avg_power_cf(x,570);printf("%d,%.9g,%.9g,%.9g,%.9g,%.9g\n",k++,sync,rsrp,epre,epre-rsrp,10*log10f(rsrp/(epre-rsrp)));}fclose(f);return k==400?0:4;}
