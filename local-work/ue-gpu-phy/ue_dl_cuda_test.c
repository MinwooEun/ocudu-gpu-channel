/**
 * Local S2 parity test: PDSCH over OFDM through the real srsran_ue_dl_nr_t object, CPU path vs GPU path
 * (SRSRAN_UE_DL_CUDA). Transmit with srsRAN (PDSCH encode + DMRS + OFDM TX), apply a flat channel + AWGN, then
 * decode the same subframe twice: once with the GPU disabled, once enabled. Compares the resource grids after the
 * FFT and the decoded transport blocks, and times both paths.
 *
 *   ue_dl_cuda_test [-p carrier_prb] [-n alloc_prb] [-b start_prb] [-m mcs] [-S snr_db] [-r reps] [-a add_pos]
 */
#include "srsran/srsran.h"
#include "srsran/phy/ue/ue_dl_cuda.h"
#include <getopt.h>
#include <stdlib.h>
#include <time.h>

static double now_us(void)
{
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1e6 + ts.tv_nsec / 1e3;
}

int main(int argc, char** argv)
{
  uint32_t carrier_prb = 106, alloc_prb = 0, start_prb = 0, mcs = 10, reps = 20, add_pos = 2, cdm = 2;
  float    snr_db = 20.0f;
  int      opt;
  while ((opt = getopt(argc, argv, "p:n:b:m:S:r:a:c:")) != -1) {
    switch (opt) {
      case 'p': carrier_prb = (uint32_t)atoi(optarg); break;
      case 'n': alloc_prb = (uint32_t)atoi(optarg); break;
      case 'b': start_prb = (uint32_t)atoi(optarg); break;
      case 'm': mcs = (uint32_t)atoi(optarg); break;
      case 'S': snr_db = (float)atof(optarg); break;
      case 'r': reps = (uint32_t)atoi(optarg); break;
      case 'a': add_pos = (uint32_t)atoi(optarg); break;
      case 'c': cdm = (uint32_t)atoi(optarg); break;
      default: return 1;
    }
  }
  if (alloc_prb == 0) {
    alloc_prb = carrier_prb - start_prb;
  }
  setenv("SRSRAN_LDPC_DECODER", "cuda", 0);
  setenv("SRSRAN_UE_DL_CUDA", "all", 0);

  srsran_carrier_nr_t carrier = {};
  carrier.pci                 = 500;
  carrier.dl_center_frequency_hz = 3.5e9;
  carrier.scs                 = srsran_subcarrier_spacing_15kHz;
  carrier.nof_prb             = carrier_prb;
  carrier.max_mimo_layers     = 1;

  uint32_t symbol_sz = srsran_min_symbol_sz_rb(carrier_prb);
  uint32_t sf_len    = symbol_sz * 15;
  cf_t*    rx_buf    = srsran_vec_cf_malloc(sf_len);
  cf_t*    input[SRSRAN_MAX_PORTS] = {rx_buf};

  srsran_ue_dl_nr_args_t ue_args = {};
  ue_args.nof_rx_antennas        = 1;
  ue_args.nof_max_prb            = carrier_prb;
  ue_args.pdsch.sch.max_nof_iter = 10;
  srsran_ue_dl_nr_t ue_dl        = {};
  if (srsran_ue_dl_nr_init(&ue_dl, input, &ue_args) < SRSRAN_SUCCESS || srsran_ue_dl_nr_set_carrier(&ue_dl, &carrier) < SRSRAN_SUCCESS) {
    printf("ue_dl init failed\n");
    return 1;
  }
  if (ue_dl.cuda == NULL) {
    printf("GPU context not created\n");
    return 1;
  }

  // Transmitter
  srsran_pdsch_nr_t      pdsch_tx = {};
  srsran_pdsch_nr_args_t pargs    = {};
  if (srsran_pdsch_nr_init_enb(&pdsch_tx, &pargs) < SRSRAN_SUCCESS || srsran_pdsch_nr_set_carrier(&pdsch_tx, &carrier) < SRSRAN_SUCCESS) {
    printf("pdsch tx init failed\n");
    return 1;
  }
  srsran_dmrs_sch_t dmrs_tx = {};
  if (srsran_dmrs_sch_init(&dmrs_tx, false) < SRSRAN_SUCCESS || srsran_dmrs_sch_set_carrier(&dmrs_tx, &carrier) < SRSRAN_SUCCESS) {
    printf("dmrs tx init failed\n");
    return 1;
  }
  cf_t*             grid_tx  = srsran_vec_cf_malloc(SRSRAN_SLOT_LEN_RE_NR(carrier_prb));
  cf_t*             grid_cpu = srsran_vec_cf_malloc(SRSRAN_SLOT_LEN_RE_NR(carrier_prb));
  srsran_ofdm_t     ofdm_tx  = {};
  srsran_ofdm_cfg_t ocfg     = {};
  ocfg.nof_prb               = carrier_prb;
  ocfg.symbol_sz             = symbol_sz;
  ocfg.cp                    = SRSRAN_CP_NORM;
  ocfg.keep_dc               = true;
  ocfg.in_buffer             = grid_tx;
  ocfg.out_buffer            = rx_buf;
  ocfg.phase_compensation_hz = carrier.dl_center_frequency_hz;
  if (srsran_ofdm_tx_init_cfg(&ofdm_tx, &ocfg) < SRSRAN_SUCCESS) {
    printf("ofdm tx init failed\n");
    return 1;
  }

  // PDSCH configuration (DCI 1_0 style C-RNTI grant, type A, DMRS type 1)
  srsran_sch_cfg_nr_t cfg   = {};
  cfg.sch_cfg.mcs_table     = srsran_mcs_table_64qam;
  cfg.dmrs.type             = srsran_dmrs_sch_type_1;
  cfg.dmrs.typeA_pos        = srsran_dmrs_sch_typeA_pos_2;
  cfg.dmrs.additional_pos   = (srsran_dmrs_sch_add_pos_t)add_pos;
  cfg.dmrs.length           = srsran_dmrs_sch_len_1;
  if (srsran_ra_dl_nr_time_default_A(0, cfg.dmrs.typeA_pos, &cfg.grant) < SRSRAN_SUCCESS) {
    printf("time ra failed\n");
    return 1;
  }
  cfg.grant.nof_dmrs_cdm_groups_without_data = cdm;
  cfg.grant.beta_dmrs                        = srsran_convert_dB_to_amplitude(cdm == 2 ? 3.0f : 0.0f);
  cfg.grant.nof_layers                       = 1;
  cfg.grant.dci_format                       = srsran_dci_format_nr_1_0;
  cfg.grant.rnti                             = 0x4601;
  cfg.grant.rnti_type                        = srsran_rnti_type_c;
  cfg.grant.nof_prb                          = alloc_prb;
  for (uint32_t i = 0; i < SRSRAN_MAX_PRB_NR; i++) {
    cfg.grant.prb_idx[i] = (i >= start_prb && i < start_prb + alloc_prb);
  }
  if (srsran_ra_nr_fill_tb(&cfg, &cfg.grant, mcs, &cfg.grant.tb[0]) < SRSRAN_SUCCESS) {
    printf("fill tb failed\n");
    return 1;
  }
  srsran_softbuffer_tx_t sb_tx = {};
  srsran_softbuffer_rx_t sb_rx = {};
  srsran_softbuffer_tx_init_guru(&sb_tx, SRSRAN_SCH_NR_MAX_NOF_CB_LDPC, SRSRAN_LDPC_MAX_LEN_ENCODED_CB);
  srsran_softbuffer_rx_init_guru(&sb_rx, SRSRAN_SCH_NR_MAX_NOF_CB_LDPC, SRSRAN_LDPC_MAX_LEN_ENCODED_CB);
  cfg.grant.tb[0].softbuffer.tx = &sb_tx;
  uint32_t tbs                  = cfg.grant.tb[0].tbs;
  uint8_t* data_tx[SRSRAN_MAX_TB] = {srsran_vec_u8_malloc(tbs / 8 + 8)};
  uint8_t* data_cpu             = srsran_vec_u8_malloc(tbs / 8 + 8);
  uint8_t* data_gpu             = srsran_vec_u8_malloc(tbs / 8 + 8);
  srsran_random_t rnd           = srsran_random_init(7);
  srsran_slot_cfg_t slot        = {.idx = 3};

  printf("cdm=%u carrier %u PRB (N=%u), alloc %u@%u, S=%u L=%u, mcs %u -> mod %s tbs %u nof_re %u nof_bits %u, snr %.1f dB, %u reps\n",
         cdm, carrier_prb, symbol_sz, alloc_prb, start_prb, cfg.grant.S, cfg.grant.L, mcs, srsran_mod_string(cfg.grant.tb[0].mod), tbs,
         cfg.grant.tb[0].nof_re, cfg.grant.tb[0].nof_bits, snr_db, reps);

  float  n0       = powf(10.0f, -snr_db / 10.0f);
  float  sigma    = sqrtf(n0 / 2.0f);
  uint32_t ok_cpu = 0, ok_gpu = 0, match_gpu = 0, gpu_taken = 0;
  double t_cpu_fft = 0, t_cpu_dec = 0, t_gpu_fft = 0, t_gpu_dec = 0;
  float  grid_err_max = 0.0f, grid_ref_max = 0.0f;
  for (uint32_t r = 0; r < reps; r++) {
    for (uint32_t i = 0; i < tbs / 8; i++) {
      data_tx[0][i] = (uint8_t)srsran_random_uniform_int_dist(rnd, 0, 255);
    }
    srsran_vec_cf_zero(grid_tx, SRSRAN_SLOT_LEN_RE_NR(carrier_prb));
    cfg.grant.tb[0].softbuffer.tx = &sb_tx;
    if (srsran_pdsch_nr_encode(&pdsch_tx, &cfg, &cfg.grant, data_tx, &grid_tx) < SRSRAN_SUCCESS) {
      printf("encode failed\n");
      return 1;
    }
    if (srsran_dmrs_sch_put_sf(&dmrs_tx, &slot, &cfg, &cfg.grant, grid_tx) < SRSRAN_SUCCESS) {
      printf("dmrs put failed\n");
      return 1;
    }
    // flat channel: unit gain, random phase; AWGN
    float ph = srsran_random_uniform_real_dist(rnd, 0.0f, 2.0f * (float)M_PI);
    cf_t  h  = cexpf(I * ph);
    for (uint32_t i = 0; i < SRSRAN_SLOT_LEN_RE_NR(carrier_prb); i++) {
      grid_tx[i] = grid_tx[i] * h + sigma * (srsran_random_gauss_dist(rnd, 1.0f) + I * srsran_random_gauss_dist(rnd, 1.0f));
    }
    srsran_ofdm_tx_sf(&ofdm_tx);

    // CPU
    srsran_ue_dl_nr_set_cuda_mode(&ue_dl, 0);
    double t0 = now_us();
    srsran_ue_dl_nr_estimate_fft(&ue_dl, &slot);
    double t1 = now_us();
    memcpy(grid_cpu, ue_dl.sf_symbols[0], sizeof(cf_t) * SRSRAN_SLOT_LEN_RE_NR(carrier_prb));
    srsran_softbuffer_rx_reset(&sb_rx);
    cfg.grant.tb[0].softbuffer.rx = &sb_rx;
    srsran_pdsch_res_nr_t res     = {};
    res.tb[0].payload             = data_cpu;
    double t2 = now_us();
    if (srsran_ue_dl_nr_decode_pdsch(&ue_dl, &slot, &cfg, &res) < SRSRAN_SUCCESS) {
      printf("cpu decode failed\n");
      return 1;
    }
    double t3 = now_us();
    bool cpu_ok = res.tb[0].crc && memcmp(data_cpu, data_tx[0], tbs / 8) == 0;
    ok_cpu += cpu_ok;
    t_cpu_fft += t1 - t0;
    t_cpu_dec += t3 - t2;
    float snr_cpu = ue_dl.chest.snr_db;

    // GPU
    srsran_ue_dl_nr_set_cuda_mode(&ue_dl, SRSRAN_UE_DL_CUDA_FFT | SRSRAN_UE_DL_CUDA_PDSCH);
    uint32_t before = ue_dl.cuda_pdsch_count;
    t0 = now_us();
    srsran_ue_dl_nr_estimate_fft(&ue_dl, &slot);
    t1 = now_us();
    for (uint32_t i = 0; i < SRSRAN_SLOT_LEN_RE_NR(carrier_prb); i++) {
      float e = cabsf(ue_dl.sf_symbols[0][i] - grid_cpu[i]);
      float a = cabsf(grid_cpu[i]);
      grid_err_max = SRSRAN_MAX(grid_err_max, e);
      grid_ref_max = SRSRAN_MAX(grid_ref_max, a);
    }
    srsran_softbuffer_rx_reset(&sb_rx);
    srsran_pdsch_res_nr_t res_g = {};
    res_g.tb[0].payload         = data_gpu;
    t2 = now_us();
    if (srsran_ue_dl_nr_decode_pdsch(&ue_dl, &slot, &cfg, &res_g) < SRSRAN_SUCCESS) {
      printf("gpu decode failed\n");
      return 1;
    }
    t3 = now_us();
    bool gpu_ok = res_g.tb[0].crc && memcmp(data_gpu, data_tx[0], tbs / 8) == 0;
    ok_gpu += gpu_ok;
    match_gpu += (gpu_ok == cpu_ok);
    gpu_taken += (ue_dl.cuda_pdsch_count != before);
    t_gpu_fft += t1 - t0;
    t_gpu_dec += t3 - t2;
    if (r < 3 || !gpu_ok) {
      printf("  rep %u: cpu crc=%d (snr %.1f dB, iter %.1f)  gpu crc=%d taken=%d (snr %.1f dB, iter %.1f)  fft cpu %.0f gpu %.0f us  dec cpu %.0f gpu %.0f us\n",
             r, cpu_ok, snr_cpu, res.tb[0].avg_iter, gpu_ok, ue_dl.cuda_pdsch_count != before, ue_dl.chest.snr_db, res_g.tb[0].avg_iter,
             t_cpu_fft / (r + 1), t1 - t0, t_cpu_dec / (r + 1), t3 - t2);
    }
  }
  printf("RESULT snr=%.1f prb=%u alloc=%u mcs=%u tbs=%u reps=%u | cpu ok %u | gpu ok %u taken %u same %u | grid max err %.3e (ref max %.3e) | fft cpu %.0f gpu %.0f us | pdsch cpu %.0f gpu %.0f us\n",
         snr_db, carrier_prb, alloc_prb, mcs, tbs, reps, ok_cpu, ok_gpu, gpu_taken, match_gpu, grid_err_max, grid_ref_max, t_cpu_fft / reps,
         t_gpu_fft / reps, t_cpu_dec / reps, t_gpu_dec / reps);
  srsran_ue_dl_nr_free(&ue_dl);
  return 0;
}
