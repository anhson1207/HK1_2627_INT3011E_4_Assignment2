# Member 3 Phase M3.4 – RCM vs SA vs DRSA Controlled Evaluation

- **Git commit:** `326ec7c`
- **Preflight verified READY:** `54` (`{'total': 113, 'ready': 54, 'needs_verification': 58, 'invalid_data': 1}`)
- **Executed runs:** `395` (`100% validation passed`: `True`)
- **Stage C batch coverage:** `{'stage_c_planned': 216, 'stage_c_executed': 216, 'stage_c_skipped_batch_budget': 0, 'stage_c_instances_covered': 54, 'stage_c_max_batch_seconds': 360.0}`

## Summary by Stage & Configuration

| Stage | Config ID | Method | Variant | Runs | Mean BW | Mean Gap to Pub Best | Matched Pub Best | Improved Over Init | Mean Time (s) |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| Stage_B_Pilot | rcm_deterministic | RCM | BASELINE | 8 | 17.875 | 6.125 | 1 | 0 | 0.0036 |
| Stage_B_Pilot | sa_rcm_init | SA | BASELINE | 24 | 16.5833 | 4.8333 | 3 | 9 | 4.0113 |
| Stage_B_Pilot | sa_random_init | SA | BASELINE | 24 | 34.9167 | 23.1667 | 0 | 24 | 4.0438 |
| Stage_B_Pilot | drsa_paper_random | DRSA | PAPER_FAITHFUL | 24 | 93.625 | 81.875 | 0 | 24 | 4.0909 |
| Stage_B_Pilot | drsa_rcm_t1000 | DRSA | MODIFIED_VARIANT | 24 | 17.875 | 6.125 | 3 | 0 | 4.2903 |
| Stage_B_Pilot | drsa_modified_warm | DRSA | MODIFIED_VARIANT | 24 | 16.1667 | 4.4167 | 4 | 8 | 4.0287 |
| Ablation_Study | ablate_op_rex_only | DRSA | MODIFIED_VARIANT | 9 | 14.7778 | 3.1111 | 0 | 3 | 3.008 |
| Ablation_Study | ablate_op_nex_only | DRSA | MODIFIED_VARIANT | 9 | 15 | 3.3333 | 0 | 3 | 3.0025 |
| Ablation_Study | ablate_op_rot_only | DRSA | MODIFIED_VARIANT | 9 | 15.7778 | 4.1111 | 0 | 2 | 3.0094 |
| Ablation_Study | ablate_op_mixture_warm | DRSA | MODIFIED_VARIANT | 9 | 14.8889 | 3.2222 | 0 | 3 | 3.0072 |
| Ablation_Study | ablate_eval_bw_only | DRSA | MODIFIED_VARIANT | 9 | 15.2222 | 3.5556 | 0 | 3 | 3.0074 |
| Ablation_Study | ablate_speed_incremental | DRSA | PAPER_FAITHFUL | 3 | 101 | 85 | 0 | 3 | 0.6537 |
| Ablation_Study | ablate_speed_full | DRSA | PAPER_FAITHFUL | 3 | 101 | 85 | 0 | 3 | 3.5607 |
| Stage_C_54_READY | stage_c_rcm | RCM | BASELINE | 54 | 49.5556 | 21.0556 | 5 | 0 | 0.0395 |
| Stage_C_54_READY | stage_c_sa_rcm | SA | BASELINE | 54 | 49.4259 | 20.9259 | 5 | 2 | 1.5098 |
| Stage_C_54_READY | stage_c_drsa_paper_random | DRSA | PAPER_FAITHFUL | 54 | 446.2778 | 417.7778 | 0 | 52 | 1.5146 |
| Stage_C_54_READY | stage_c_drsa_warm | DRSA | MODIFIED_VARIANT | 54 | 49.3889 | 20.8889 | 5 | 3 | 1.5143 |

## Stage B Mean Bandwidth Across Seeds {17, 23, 42} (4.0s)

| Instance | n | m | Pub Best | RCM | SA (RCM) | SA (Rand) | DRSA Paper (Rand) | DRSA (RCM T0=1000) | DRSA Warm (RCM T0=2) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| bcspwr01 | 39 | 46 | 5 | 8 | 6.67 (6–7) | 7.67 (6–10) | 22.67 (21–26) | 8.00 (8–8) | 6.33 (5–8) |
| bcsstk01 | 48 | 176 | 16 | 27 | 20.33 (19–22) | 20.00 (18–22) | 37.33 (37–38) | 27.00 (27–27) | 19.00 (17–22) |
| bcspwr02 | 49 | 59 | 7 | 13 | 10.67 (10–11) | 9.00 (9–9) | 29.00 (28–30) | 13.00 (13–13) | 9.00 (9–9) |
| ash85 | 85 | 219 | 9 | 10 | 10.00 (10–10) | 20.67 (18–22) | 68.33 (68–69) | 10.00 (10–10) | 10.00 (10–10) |
| nos4 | 100 | 247 | 10 | 15 | 15.00 (15–15) | 23.67 (23–25) | 82.67 (82–84) | 15.00 (15–15) | 15.00 (15–15) |
| bcsstk22 | 138 | 279 | 10 | 14 | 14.00 (14–14) | 31.67 (30–34) | 112.00 (110–113) | 14.00 (14–14) | 14.00 (14–14) |
| dwt_209 | 209 | 767 | 23 | 42 | 42.00 (42–42) | 85.67 (83–89) | 187.33 (187–188) | 42.00 (42–42) | 42.00 (42–42) |
| saylr1 | 238 | 445 | 14 | 14 | 14.00 (14–14) | 81.00 (74–87) | 209.67 (208–211) | 14.00 (14–14) | 14.00 (14–14) |

## Warm-Start Verification (M3.4.9)

| Instance | DRSA Warm BW (Time s) | CP-SAT Status | CP-SAT BW (LB, Time s) | Inc SAT Status | SAT BW (LB, Time s) |
|---|---:|---|---:|---|---:|
| bcspwr01 | 6 (1.50202s) | OPTIMAL | 5 (5, 9.85726s) | TIMEOUT | 5 (4, 3.0097s) |
| bcspwr02 | 11 (1.501758s) | FEASIBLE | 7 (6, 10.014904s) | TIMEOUT | 11 (6, 3.024323s) |
