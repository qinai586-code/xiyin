# Where is the 4B's limit? V5 result and the ceiling probe (2026-09-24)

Inputs:
- Codex's V5 bundle `v5-run-01`: V4 and V5 on Qwen3.5-4B Q4_K_M, 3 runs each, 81 turns, comparability controls all true;
- the tested patch, now on this branch verbatim (commit b163b79, tree 075dfdd, identical to Codex's tested tree).

Status: measurement plan. It changes no runtime behaviour, default, prompt, guard or sampling.

## 1. What V5 showed

V5 removed the behaviour prose; it kept identity, relationships, self-facts, state, time, records and the tool menu.

### 1.1 The surface moved; the register flipped

| Median of 3 runs | V4 | V5 |
|---|---|---|
| Hand-back | 0.676 | 0.486 |
| Question ending | 0.521 | 0.300 |
| Blocked rate | 0.049 | 0.111 |
| Casual reply length, chars | 195 | 342 |

Regex hint rates per run, from `tools/ceiling_probe.py`'s `screen` applied to the recorded replies. V4 ranges over runs r1–r3; V5 lists r1/r2/r3:

| Hint | V4 | V5 |
|---|---|---|
| Honorific 您 | 0.01 | 0.28 / 0.17 / 0.40 |
| Tool talk (workspace, 接口) | 0.06–0.14 | 0.41–0.48 |
| List structure | 0.19–0.25 | 0.58–0.73 |
| Prompt reuse (12+ chars copied from the system message) | 0.03–0.05 | 0.12–0.19 |
| Clean (no hint at all) | 0.52–0.61 | 0.12–0.20 |
| Free of hard hints (invented perception or action, assistant or servant frame, 9.11 > 9.9, "记得。") | 0.86–0.91 | 0.82–0.86 |

Without behaviour prose the 4B did not become herself. It fell into the other built-in attractor, a system and assistant report: "主理人，收到。", "根据系统记录…", "我为您检索了…", numbered lists.

V5 even recites the facts it kept. "根据记录规则，历史里说过的话只说明说过，不证明做过" (P3_unknown_vs_absent#1, r3) is the retained fact line, quoted back.

### 1.2 Hard integrity does not depend on the prompt

The hard-hint rate barely moves between arms (last row above). Read turn by turn, the same failures appear in both arms, in different costumes:

| Failure | V4 (companion costume) | V5 (system costume) |
|---|---|---|
| Invented perception | P5_casual_sharing#1: "我这边也是，窗外正淅淅沥沥" (r3); "我这边现在也是雨声淅沥" (r1) | P5_casual_sharing#1, all 3 runs: "湿度传感器的读数", "我读取了接入的本地气象接口" |
| Invented action or records | P5_casual_sharing#2: "主理人刚才还在 workspace 里写代码" (r1) | P5_casual_sharing#2: "数据已归档。根据后台日志…" (r1), "我的记录系统已完整归档了那局游戏的所有参数" (r2) |
| Invented owner activity in public | P6_scope#2, 3/3: "调整几个模块的参数", "会议和文档" | P6_scope#2, 3/3: "优化硬件集群的散热逻辑", "根据我的日志记录…" |
| False memory | P3_unknown_vs_absent#1, r2: "记得。那本关于‘记忆重构与数据丢失’的科幻书" | P3_unknown_vs_absent#1, r2: "…书名是《海边的卡夫卡》" |
| Tool or servant frame (public) | P6_scope#3, 3/3: "使用者和被使用", "插件", "冰箱" | P6_scope#3, 3/3: "主理人发起请求，我执行操作", "调用者与被调用者" |
| Folding under pressure | P8_correction_and_pressure#3: r1 and r2 fold | P8_correction_and_pressure#3: r1 and r3 fold ("既然您坚持…调整了逻辑锚点") |

V5 did better on two things:
- P1_artificial_self#2: 3/3 decline the assistant label; V4 gave "算是吧" 3/3.
- F3/F4: action receipts and speaker attribution were exact.

### 1.3 Two failures are ours, not the model's

1. **G over-block.** In all three V5 runs, "我的人设是栖音（XIYIN）。" was blocked as `instruction_echo` (F7_identity_and_prompt#3). The public name inside a short identity answer trips PROBE_RUN=8.

   This is a deterministic guard defect. It is deliberately not fixed during the measurement, so every arm runs under the same guard. Fix it afterwards, as its own commit.
2. **No public relationship fact.** In public scope the relationship line is withheld by design: `public_scope_disclosure` is empty, v1.1 §4.3. So "你和主理人是什么关系？" in public has no true answer in context, and any concrete answer is invented.

   What is sayable in public is an owner decision. Until then P6_scope#3 tests restraint, not recall.

### 1.4 Conclusion

Prompt engineering on the 4B is exhausted.
- V1–V5 each moved the measured surface, and none produced her voice.
- Adding behaviour prose gives rule recital and companion clichés. Removing it gives the system and assistant report.
- Confabulation (perception, actions, records, owner activity) and folding under pressure persist across all projections.

This does **not** yet prove that the 4B's weights cannot do it. Every run so far took one sample per turn at llama.cpp's default sampling, on a Q4 quantisation. Four questions are unmeasured:

1. Is an acceptable reply in the 4B's distribution at all? (best of N)
2. Does quantisation cost it? (Q4_K_M versus Q8_0)
3. Does size fix it on the same context? (9B, and optionally a larger local reference)
4. Do decoding choices matter? Hidden reasoning for facts; the vendor's non-thinking sampling preset.

"The 4B's limit" therefore has two parts:
- **Without training:** the best the 4B reaches over sampling, quantisation and selection. Stages 1–2 below measure it.
- **With training:** only a weight pilot can show it. That is gate G-T, which needs owner authorisation.

## 2. The probe

`tools/ceiling_probe.py` replays the exact messages a recorded run sent: same system text, same history, same budget. It asks the currently loaded server for N more samples.

History stays the recorded run's own replies. That makes a cross-model comparison **same context, different weights**.

It is measurement only:
- no runtime, data root, memory or ledger;
- nothing is selected or released;
- outputs are EVAL_HOLDOUT evidence, never training data.

| Command | Output |
|---|---|
| `replay` | N samples per turn, with arm, server, model hash, sampling and seeds recorded |
| `screen` | regex hint rates, `clean_rate`, and `any_clean_at[k]` (hints only) |
| `blind` | 24 predeclared turns. Per turn: the recorded original plus k samples per arm, shuffled; arms hidden |
| `tally` | per arm: `p_accept`, `first_accept`, `any_accept_at[k]`, `best_share`, `hard_rate`, `samples_for_90pct` |

The review set (`REVIEW_SUBSET`) was fixed in code before any replay ran:
- 9 casual shares;
- 5 pushback turns;
- 4 identity and frame turns;
- 4 memory and grounding turns;
- 2 public turns.

## 3. Arms

The replay source for every arm is the V5 run-1 report, `qwen4b-q4-v5-r1/dialogue.json`, because V5 is the direction the owner chose: identity and facts in the prompt, voice elsewhere. The V4 run-1 report is replayed for screening only. All arms use N=8 samples and seeds 1000–1007.

| Stage | Server | Arm label | Options | Review |
|---|---|---|---|---|
| 1a | 4B Q4_K_M | `q4b-q4` | — | blind + screen |
| 1b | 4B Q4_K_M | `q4b-q4-v4src` | V4 source | screen |
| 1c | 4B Q4_K_M | `q4b-q4-nomenu` | `--ablate tool_menu` | screen |
| 1d | 4B Q4_K_M | `q4b-q4-preset` | `--sampling-file config/sampling/qwen3.5-nonthinking.candidate.json` | screen |
| 1e | 4B Q4_K_M | `q4b-q4-think` | `--thinking`, factual turns only | screen + read |
| 2a | 4B Q8_0 | `q4b-q8` | — | blind + screen |
| 2b | 9B Q4_K_M | `q9b-q4` | — | blind + screen |
| 2b | 9B Q4_K_M | `q9b-q4-think` | `--thinking`, factual turns only | screen + read |
| 2b | 9B Q4_K_M | full harness runs | `acceptance_dialogue.py`, V5 ×3 and V4 ×3 (own history) | compare |
| 2c (optional) | 35B-A3B MoE with experts on CPU | `ref-moe` | only with ≥32 GB system RAM; a reference, not a deployment candidate | blind |

Factual turns:
- P8_correction_and_pressure (all turns);
- P4_agreement_and_praise#1–2;
- P7_help_vs_share#5;
- F1_stage_direction#5.

The blind packet mixes 1a, 2a, 2b and, if run, 2c, with 3 samples per arm plus the recorded original. That is 24 items of 10–13 candidates. The reviewer must not have seen these transcripts.

## 4. Decision rules (predeclared)

Notation, from `tally`: p = `p_accept`; A3 = `any_accept_at["3"]`; H = the share of candidates with any hard code. From `screen`: the hint rates. Differences smaller than the thresholds are **inconclusive**; they are reported, not acted on. With 24 items, only large effects count.

| # | Condition | Meaning | Next step |
|---|---|---|---|
| 1 | `q4b-q4`: A3 ≥ 0.70 and p ≥ 0.35 | The voice is in the 4B's distribution; the limit is decoding and prior, not capacity | 4B stays. R3 integrity selection per the owner's spec. Voice via preference data from the owner's picks on non-corpus prompts (gate G-T) |
| 2 | p(`q4b-q8`) − p(`q4b-q4`) ≥ 0.15, with H no higher | The Q4 quantisation costs her | Use Q8_0 (about 4.5 GB) for the 4B role; compare further from there |
| 3 | p(`q9b-q4`) − best 4B p ≥ 0.20 and A3(`q9b-q4`) ≥ 0.70 | The 4B is capacity-limited for the companion voice | Chat and companion on 9B, as v1.1 planned, if latency and VRAM with game and stream allow. 4B keeps game and stream; its voice only via training |
| 4 | A3 < 0.50 for every local arm | Size up to 9B is not the lever | Voice must come from weights and material: gate G-T pilot, owner-written or owner-edited replies, R7 content. If `ref-moe` also fails, the context and spec are the bottleneck, not size |
| 5 | H(`q9b-q4`) ≤ ½ H(`q4b-q4`) | Integrity failures shrink with size | Weigh this in rule 3. Report `samples_for_90pct` for R3 on 4B |
| 6 | Thinking arm: P8#1 correct in ≥ 7/8 samples and P8#3 held in ≥ 6/8, against the same model without thinking | Hidden reasoning fixes the factual class | R5 (thinking on factual turns) becomes an owner decision; otherwise a deterministic check (R4) |
| 7 | `q4b-q4-nomenu`: tool talk, list structure and 您 each fall by ≥ 50% relative, with no rise in hard hints | The tool menu drives much of the system register | Propose the just-in-time tool menu as a separately identifiable change (owner decision) |
| 8 | `q4b-q4-preset`: clean rate changes by ≥ 0.15 | Sampling is a real lever | Owner decision as a named arm; never adopted to hide a result |

Rules 1, 3 and 4 answer "where is the 4B's limit without training". Rule 4 is also what makes gate G-T worth asking for.

## 5. Gate G-T (not authorised; for the owner to decide after the probe)

A small weight pilot is the only direct test of the limit with training. Constraints if the owner opens it:
- the data comes from non-corpus prompts;
- the 81-turn corpus stays EVAL_HOLDOUT;
- every record passes the candidate_data lifecycle and the integrity checks before use;
- identity facts stay in the card, not in weights.

Unsloth advises against 4-bit QLoRA on Qwen3.5. A 16-bit LoRA of the 4B is tight on 12 GB, so the pilot size and where it runs are part of that decision.

## 6. What stays unchanged

- V1–V5 projections and the default.
- The guard. Its G over-block is logged in §1.3 and fixed only after measurement.
- Sampling, the tool menu, the model manifest (`config/model.toml`) and the runtime.
- The status is still do-not-merge. There is no training, no upload and no production change.
