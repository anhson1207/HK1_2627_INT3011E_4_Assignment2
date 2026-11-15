# Member 2 Phase M2.3 – Benchmark Comparison Across 54 READY Instances

| Instance | Table | n | m | Paper LB | Paper Best | Best BW | Status (Proof) | Comparison Tag | Solver / Config | Wall (s) |
|---|---|---:|---:|---:|---:|---:|---|---|---|---:|
| `bcspwr01` | Table 6 | 39 | 46 | 5 | 5 | 5 | OPTIMAL (PROVED) | PROVED_MATCHED_BEST | gurobi (MIP/-) | 11.909 |
| `bcsstk01` | Table 6 | 48 | 176 | 16 | 16 | 20 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.007 |
| `bcspwr02` | Table 6 | 49 | 59 | 7 | 7 | 7 | TIMEOUT (UNPROVED) | UNPROVED_MATCHED_BEST | glucose (order/binary) | 30.008 |
| `ash85` | Table 6 | 85 | 219 | 9 | 9 | 10 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.008 |
| `nos4` | Table 6 | 100 | 247 | 10 | 10 | 12 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.011 |
| `bcspwr03` | Table 6 | 118 | 179 | 9 | 10 | 23 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.012 |
| `bcsstk04` | Table 6 | 132 | 1758 | 36 | 37 | 47 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.015 |
| `bcsstk22` | Table 6 | 138 | 279 | 9 | 10 | 14 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.013 |
| `can_144` | Table 6 | 144 | 576 | 13 | 13 | 18 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.015 |
| `lund_a` | Table 6 | 147 | 1151 | 19 | 23 | 23 | TIMEOUT (UNPROVED) | UNPROVED_MATCHED_BEST | cadical (order/sequential) | 30.014 |
| `lund_b` | Table 6 | 147 | 1147 | 19 | 23 | 23 | TIMEOUT (UNPROVED) | UNPROVED_MATCHED_BEST | cadical (order/sequential) | 30.013 |
| `bcsstk05` | Table 6 | 153 | 1135 | 19 | 20 | 23 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.083 |
| `can_161` | Table 6 | 161 | 608 | 18 | 18 | 30 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 34.070 |
| `dwt_209` | Table 7 | 209 | 767 | 21 | 23 | 42 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.015 |
| `dwt_221` | Table 7 | 221 | 704 | 12 | 13 | 27 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.014 |
| `dwt_234` | Table 7 | 234 | 300 | 11 | 11 | 25 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.012 |
| `dwt_245` | Table 7 | 245 | 608 | 21 | 21 | 38 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.019 |
| `bcspwr04` | Table 7 | 274 | 669 | 23 | 24 | 56 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.026 |
| `ash292` | Table 7 | 292 | 958 | 16 | 19 | 24 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.015 |
| `can_292` | Table 7 | 292 | 1124 | 34 | 38 | 64 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.023 |
| `dwt_310` | Table 7 | 310 | 1069 | 11 | 12 | 13 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.036 |
| `dwt_361` | Table 7 | 361 | 1296 | 14 | 14 | 25 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.029 |
| `dwt_419` | Table 7 | 419 | 1572 | 23 | 25 | — | RESOURCE_LIMIT | N/A | — | — |
| `bcsstk06` | Table 7 | 420 | 3720 | 38 | 45 | — | RESOURCE_LIMIT | N/A | — | — |
| `bcsstm07` | Table 7 | 420 | 3416 | 37 | 45 | — | RESOURCE_LIMIT | N/A | — | — |
| `bcspwr05` | Table 7 | 443 | 590 | 25 | 27 | — | RESOURCE_LIMIT | N/A | — | — |
| `can_445` | Table 7 | 445 | 1682 | 46 | 52 | — | RESOURCE_LIMIT | N/A | — | — |
| `bcsstk20` | Table 7 | 485 | 1325 | 8 | 13 | — | RESOURCE_LIMIT | N/A | — | — |
| `494_bus` | Table 7 | 494 | 586 | 25 | 28 | — | RESOURCE_LIMIT | N/A | — | — |
| `dwt_503` | Table 7 | 503 | 2762 | 29 | 41 | — | RESOURCE_LIMIT | N/A | — | — |
| `dwt_592` | Table 7 | 592 | 2256 | 22 | 29 | — | RESOURCE_LIMIT | N/A | — | — |
| `662_bus` | Table 7 | 662 | 906 | 36 | 39 | — | RESOURCE_LIMIT | N/A | — | — |
| `685_bus` | Table 7 | 685 | 1282 | 30 | 32 | — | RESOURCE_LIMIT | N/A | — | — |
| `can_715` | Table 7 | 715 | 2975 | 54 | 71 | — | RESOURCE_LIMIT | N/A | — | — |
| `bcsstk19` | Table 7 | 817 | 3018 | 13 | 14 | — | RESOURCE_LIMIT | N/A | — | — |
| `can_838` | Table 7 | 838 | 4586 | 75 | 86 | — | RESOURCE_LIMIT | N/A | — | — |
| `dwt_878` | Table 7 | 878 | 3285 | 23 | 25 | — | RESOURCE_LIMIT | N/A | — | — |
| `gr_30_30` | Table 7 | 900 | 3422 | 31 | 33 | — | RESOURCE_LIMIT | N/A | — | — |
| `dwt_918` | Table 7 | 918 | 3233 | 27 | 32 | — | RESOURCE_LIMIT | N/A | — | — |
| `dwt_992` | Table 7 | 992 | 7876 | 35 | 35 | — | RESOURCE_LIMIT | N/A | — | — |
| `nos1` | Table 8 | 237 | 390 | 3 | 3 | 4 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | glucose (order/binary) | 30.013 |
| `saylr1` | Table 8 | 238 | 445 | 12 | 14 | 14 | TIMEOUT (UNPROVED) | UNPROVED_MATCHED_BEST | cadical (order/sequential) | 30.750 |
| `plat362` | Table 8 | 362 | 2712 | 29 | 34 | — | RESOURCE_LIMIT | N/A | — | — |
| `plskz362` | Table 8 | 362 | 880 | 15 | 18 | 34 | TIMEOUT (UNPROVED) | UNPROVED_ABOVE_BEST | cadical (order/sequential) | 30.037 |
| `nos5` | Table 8 | 468 | 2352 | 53 | 63 | — | RESOURCE_LIMIT | N/A | — | — |
| `nos6` | Table 8 | 675 | 1290 | 15 | 16 | — | RESOURCE_LIMIT | N/A | — | — |
| `nos7` | Table 8 | 729 | 1944 | 43 | 65 | — | RESOURCE_LIMIT | N/A | — | — |
| `orsirr_2` | Table 8 | 886 | 2542 | 62 | 85 | — | RESOURCE_LIMIT | N/A | — | — |
| `jagmesh1` | Table 8 | 936 | 2664 | 24 | 27 | — | RESOURCE_LIMIT | N/A | — | — |
| `nos2` | Table 8 | 957 | 1590 | 3 | 3 | — | RESOURCE_LIMIT | N/A | — | — |
| `nos3` | Table 8 | 960 | 7442 | 43 | 44 | — | RESOURCE_LIMIT | N/A | — | — |
| `saylr3` | Table 8 | 1000 | 1375 | 35 | 46 | — | RESOURCE_LIMIT | N/A | — | — |
| `sherman1` | Table 8 | 1000 | 1375 | 35 | 46 | — | RESOURCE_LIMIT | N/A | — | — |
| `sherman4` | Table 8 | 1104 | 1341 | 21 | 27 | — | RESOURCE_LIMIT | N/A | — | — |
