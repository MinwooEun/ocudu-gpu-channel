/* Exercise the candidate helper itself against known injected noise. */
#include "dmrs_sch.local-noise.c"
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
static uint32_t seed=20261030;
static float uni(void){seed^=seed<<13;seed^=seed>>17;seed^=seed<<5;return ((double)seed+1.0)/4294967297.0;}
static float normal(void){return sqrtf(-2.0f*logf(uni()))*cosf(6.28318530718f*uni());}
int main(int argc,char**argv){if(argc!=2)return 2;FILE*f=fopen(argv[1],"rb");if(!f)return 3;cf_t h[400][570];if(fread(h,sizeof(cf_t),400*570,f)!=400*570)return 4;fclose(f);int failed=0;puts("channel,snr_db,noise_truth,local_estimate,original_estimate,ratio_local,ratio_original");
 for(int shape=0;shape<2;shape++)for(int level=0;level<5;level++){
  float snr=level==0?INFINITY:(float)(level-1)*10.0f;double truth=0,local=0,original=0;int count=0;
  for(int k=0;k<400;k++)for(int trial=0;trial<10;trial++){
   cf_t x[570] __attribute__((aligned(64)));double signal=0;
   for(int i=0;i<570;i++){cf_t z=shape?h[k][i]:1.0f;signal+=crealf(z)*crealf(z)+cimagf(z)*cimagf(z);}signal/=570;
   float variance=level==0?0:signal/powf(10,snr/10);float sigma=sqrtf(variance/2);
   for(int i=0;i<570;i++)x[i]=(shape?h[k][i]:1.0f)+sigma*(normal()+I*normal());
   float sync=srsran_vec_estimate_frequency(x,570);srsran_vec_apply_cfo(x,sync,x,570);float est=dmrs_local_noise(x,570,1,6);cf_t c=srsran_vec_acc_cc(x,570)/570.0f;float p=srsran_vec_avg_power_cf(x,570);float old=p-crealf(c)*crealf(c)-cimagf(c)*cimagf(c);
   truth+=variance;local+=est;original+=old;count++;
  }
  double ratio=truth?local/truth:0;printf("%s,%g,%.12g,%.12g,%.12g,%.9g,%.9g\n",shape?"frozen_multipath":"flat",snr,truth/count,local/count,original/count,ratio,truth?original/truth:0);
  if(level>0 && (ratio<.90 || ratio>1.10))failed++;
 }
 return failed?5:0;
}
