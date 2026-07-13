## CORE (dev14, n=7 bank_statement list docs/cell, kv_form excluded)

| cell | recall | cost/doc $ | mean conf | wall_s | fails |
|---|---:|---:|---:|---:|---:|
| bda-adv-sep | 0.857 | 1.574 | 0.937 | 301 | 0 |
| bda-simple-sep | 1.000 | 0.699 | 0.950 | 339 | 0 |
| llm-simple-sep | 0.728 | 0.454 | 0.910 | 125 | 0 |
| tl-adv-sep | 1.000 | 1.671 | 0.953 | 245 | 0 |
| tl-simple-sep | 1.000 | 0.582 | 0.995 | 305 | 0 |
| tt-adv-int | 1.000 | 2.217 | 0.958 | 501 | 0 |
| tt-adv-sep | 0.857 | 1.990 | 0.938 | 309 | 0 |
| tt-simple-int | 0.207 | 0.412 | 0.933 | 65 | 0 |
| tt-simple-off | 1.000 | 0.627 | 0.000 | 195 | 0 |
| tt-simple-sep | 1.000 | 0.706 | 0.973 | 317 | 0 |

## SCALING (dev14, simple vs advanced, Textract TABLES)

| rows | simple recall | adv recall | simple $ | adv $ | adv wall_s |
|---:|:---:|:---:|---:|---:|---:|
| 25 | 1.0 | 1.0 | 0.1278 | 0.421 | 115 |
| 100 | 1.0 | 1.0 | 0.2564 | 0.6039 | 150 |
| 400 | 1.0 | 1.0 | 0.7979 | 3.5273 | 506 |
| 800 | 1.0 | 1.0 | 1.5564 | 4.4703 | 418 |
| 1200 | 0.1175 | 1.0 | 1.3213 | 5.8483 | 428 |
| 1600 | 0.0269 | 1.0 | 1.5364 | 8.8052 | 491 |
| 3200 | 0.0037 | 1.0 | 2.697 | 24.9922 | 1172 |

## REFERENCE (real labeled sets, weighted_accuracy)



## REFERENCE (real labeled sets, weighted_accuracy vs stack eval baseline)

- **realkie**: 0.802 (15/15 docs, 0 parse failures)
- **ocr**: 0.872 (15/15 docs, 0 parse failures)

## COST VARIANCE (n=5 repeats, single fixed doc = med_narrow 400 rows) — statistically sound
| config (OCR/mode/assess) | cost mean ± stdev | CV | interpretation |
|---|---|---:|---|
| Textract / simple / separate | $0.777 ± $0.003 | 0.4% | deterministic |
| Textract LAYOUT / advanced / separate | $1.762 ± $0.075 | 4% | stable |
| Textract TABLES / advanced / integrated | $1.920 ± $0.657 | 34% | high variance |
| BDA / advanced / separate | $2.035 ± $0.583 | 29% | high variance |
| Textract TABLES / advanced / separate | $2.217 ± $0.912 | 41% | high variance |

Finding: simple mode is ~2.3–2.9x cheaper AND far more predictable (CV 0.4% vs 29–41%) than agentic
advanced mode. Advanced cost is inherently high-variance run-to-run (agent turn count varies) — which is
why single-sample cost comparisons mislead and repeats (n>=5) are required. LAYOUT/advanced is the
cheapest + most stable advanced option.
