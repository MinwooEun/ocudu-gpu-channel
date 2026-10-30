"""Create a separate source patch; never edit the upstream checkout."""
import pathlib,difflib
original=pathlib.Path('/home/minwoo/ocudu-work/evidence/receiver-quality-20261030/dmrs_sch.original.c');s=original.read_text();needle='int srsran_dmrs_sch_estimate(srsran_dmrs_sch_t*'
helper='''// Estimate noise from local pilot residuals. A straight line through each
// pair of neighbouring pilots removes the local channel slope. For independent
// equal-variance pilot noise, the residual variance is (1 + a*a + b*b)*N0.
// Keep triples inside one PRB so allocation gaps never enter the estimate.
static float dmrs_local_noise(const cf_t* pilots, uint32_t per_symbol, uint32_t symbols, uint32_t per_prb)
{
  const float type2_positions[4] = {0.0f, 1.0f, 6.0f, 7.0f};
  float power = 0.0f;
  uint32_t count = 0;
  for (uint32_t symbol = 0; symbol < symbols; ++symbol) {
    const cf_t* p = pilots + symbol * per_symbol;
    for (uint32_t base = 0; base + per_prb <= per_symbol; base += per_prb) {
      for (uint32_t i = 1; i + 1 < per_prb; ++i) {
        float left = per_prb == 6 ? 2.0f : type2_positions[i] - type2_positions[i - 1];
        float right = per_prb == 6 ? 2.0f : type2_positions[i + 1] - type2_positions[i];
        float a = right / (left + right);
        float b = left / (left + right);
        cf_t residual = p[base + i] - a * p[base + i - 1] - b * p[base + i + 1];
        power += (__real__ residual * __real__ residual + __imag__ residual * __imag__ residual) / (1.0f + a*a + b*b);
        ++count;
      }
    }
  }
  return power / (float)count;
}

'''
assert s.count(needle)==1;s=s.replace(needle,helper+needle)
needle2='  rsrp = SRSRAN_MIN(rsrp, epre - epre * 1e-7);';assert s.count(needle2)==1
s=s.replace(needle2,'''  // Wideband coherent averaging counts frequency-selective channel variation
  // as noise. Estimate noise locally before smoothing/interpolation instead.
  const uint32_t pilots_per_prb = dmrs_cfg->type == srsran_dmrs_sch_type_1 ? 6 : 4;
  const float local_noise = dmrs_local_noise(q->pilot_estimates, nof_pilots_x_symbol, nof_symbols, pilots_per_prb);
  rsrp = SRSRAN_MIN(SRSRAN_MAX(epre - local_noise, 0.0f), epre - epre * 1e-7);''')
out=original.with_name('dmrs_sch.local-noise.c');out.write_text(s)
pathlib.Path(__file__).with_name('srsue-dmrs-local-noise.patch').write_text(''.join(difflib.unified_diff(original.read_text().splitlines(True),s.splitlines(True),fromfile='a/lib/src/phy/ch_estimation/dmrs_sch.c',tofile='b/lib/src/phy/ch_estimation/dmrs_sch.c')))
