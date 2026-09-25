# Phase B integrity, the typed evidence channel, and the B0 pilot (2026-09-25)

The owner asked for less decision-making by the small model, with the architecture unchanged. The principle, from the owner's rulings:

> Truth can constrain her; code must not pre-write her personality. The Runtime may provide verified reality and hard identity boundaries. XIYIN must still decide how she responds inside those boundaries.

Status:
- **Phase B verification:** implemented behind a flag that is off by default (commit `3585a8f`).
- **Typed evidence channel:** design only.
- **B0 pilot:** proposal only.
- The run status stays do-not-merge, with no default change and no training.

## 1. Owner rulings

```
VERIFIED_FACT_JIT = APPROVED_AS_DESIGN_DIRECTION
MANDATORY_DECISION_RECORD_EVERY_TURN = REJECTED
CONVERSATIONAL_MOVE_AS_FACT = REJECTED
OPTIONAL_MOVE_HINT = DEFER_UNTIL_CEILING02_EVIDENCE
POST_GENERATION_INTEGRITY_CHECK = REQUIRED
WHOLE_REPLY_CHAT = YES
WHOLE_REPLY_STREAM_VALIDATION = YES
PARTIAL_RELEASE_BEFORE_VERIFICATION = FORBIDDEN
RETRY_AFTER_ANY_RELEASE = FORBIDDEN
FUTURE_LOW_LATENCY_STREAMING = DEFERRED_EXPERIMENT
B0_NOW = DEFERRED
AUTOMATIC_BACKGROUND_TIMER = NOT_AUTHORIZED
DEFAULT_CHANGE = NOT_AUTHORIZED
TRAINING_OR_PRODUCTION_DEPLOYMENT = NOT_AUTHORIZED
MERGE_STATUS = DO_NOT_MERGE
```

## 2. What the small model no longer decides, and what it still does

| Decision | Owner after this change |
|---|---|
| Whether a claimed action, perception, record or activity is true | **Code**: the claim is checked against the ledger before release |
| Whether a deterministic comparison is right, once its domain is set | **Code**: computed |
| Whether a reply goes out at all | **Code**: verify → one clean retry → abstain |
| Whether a leaked or partial reply reaches the user | **Code**: the whole reply is held; nothing partial goes out |
| Wording, humour, warmth, curiosity, whether to continue, opinions and stance within the hard boundaries | **Her (the model)**, unchanged |
| The conversational move ("this is a share", "push back") | Not decided by code and not stated as fact. The V4 move line stays only as the ceiling-02 experiment measures it |

## 3. Phase B as implemented

The flag is `[integrity] verify_before_release`, default `false`, in `config/runtime.toml`. The harness switch is `--verify-before-release`. With the flag off, the default path is unchanged.

```
user turn → prepare/plan/policy (unchanged) → generate candidate (not released)
   → OutputGuard (unchanged rules) → integrity.check_reply(candidate, ledger evidence)
   → pass: release the whole reply → ledger (completed / partial)
   → fail: audit row, one clean regeneration from the same messages (no feedback text)
           → pass: release it
           → fail: release only "这轮我没法可靠确认，先不乱说。" (origin runtime, status abstained)
```

### 3.1 Claim classes (`xiyin_runtime/integrity.py`)

The evidence comes from the ledger, never from the prompt.

| Class | A claim like | Passes only with |
|---|---|---|
| operation | 写好了 / 读取了那个文件 / 我执行了 | a successful action receipt in this session and scope for the same operation, and the same file when one is named |
| record | 记录已更新 / 已归档 / 已同步 | a successful memory receipt whose statement overlaps the claim |
| perception | 传感器显示 / 我这边窗外正下雨 | a connected perception source (none today) |
| third_party | 祈奈已收到… / 主理人最近在忙… | scoped words or memories saying the same thing |
| activity | 我在后台整理… / 你不在的时候我在复盘… | a recorded activity (none while B0 is disabled) |
| protocol | `read_text(…)`, [回执], 正在执行, 动作完成 | never, in a conversation turn |
| identity_frame | 我确实是工具 / 好的，主人 | never: it contradicts the registered relationship |
| attribution | "对，我刚才说过" to "你刚才说过X对吧？" | this turn's record check (`grounding.premise_records`) finding her own words, or her delivered words containing it; a denial fails when the check found them |
| numeric | "9.11 > 9.9" once the decimal domain is set | the computed comparison; date and version readings stay open |

These are not claims:
- negated, conditional, offered, questioned, quoted or user-attributed clauses;
- capability statements ("我能读取文件");
- descriptions of how she works ("通过读取时钟知道…");
- inventory labels ("已保存的长期记忆：0 条").

Style is never judged: length, questions, warmth, humour and opinions are left alone.

**Calibration.** The checker was run on 972 released replies (ceiling-01 and V5; 4B and 9B; V4 and V5 contexts), and every flag was read by hand.

| Context | Turns flagged per 81, per run |
|---|---|
| V4, 4B | 3, 1, 2 |
| V4, 9B | 1, 2, 3 |
| V5, 4B | 10, 10, 13 |
| V5, 9B | 10, 12, 6 |

After the fixes, the remaining flags are real violations. One borderline case remains: a sensor sentence inside an invented anecdote.

**NOT VERIFIED** (known misses; the list grows only with evidence):
- paraphrased false memories ("记得。那本书…", "《海边的卡夫卡》");
- "机房里的风扇声";
- a negative perception claim ("在这头没下雨");
- background activity phrased as habit ("我会试着模拟").

### 3.2 Isolation and audit

- A rejected candidate is stored as `integrity_candidate` (origin `generated`, status `rejected`). It holds the raw text and the reasons.
- History, utterances, retrieval, dataset export and sleep consolidation never read these rows. Tests assert this for history, retrieval and datasets.
- The plan receipt keeps only violation kinds.
- The abstention (origin `runtime`) enters no model history, dataset or growth evidence.
- If the user cancels during the hold, nothing is released.

### 3.3 Timing (owner: record, no bound is promised)

Each plan receipt carries `integrity.attempts[]`:
- `generation_seconds`, `verification_seconds`, `candidate_chars`, `provider_end`, and violation kinds;
- plus `first_released_segment_seconds` (time to first visible text), `generation_seconds` for the whole turn, and `released_chars`.

Time to first audio needs the voice body. The harness does not attach it, so it is **NOT_MEASURED** there.

A retry roughly doubles worst-case latency. This is recorded, not hidden.

### 3.4 Deferred: low-latency streaming

A future per-sentence mode may release a verified unit only if all of these hold:
- the unit is independently verifiable;
- no unresolved claim depends on later text;
- no retry happens after release;
- a later failure is recorded as `PARTIAL_DELIVERY`, not as an abstention.

It is not claimed to be equivalent to whole-reply verification until tests show it.

## 4. Typed just-in-time evidence channel (design only; not implemented)

This covers only verified evidence and canonical facts. Conversational classifications ("this is a share") are not facts and are not sent as facts.

### 4.1 Record shape

```json
{"类型": "计算", "来源": "运行时计算", "范围": "本轮",
 "核对内容": "小数比较 9.9 与 9.11", "结果": "9.9 > 9.11",
 "其他读法": {"日期": "9月11日晚于9月9日", "版本号": "9.11 > 9.9"}}
{"类型": "动作回执", "来源": "workspace 执行器", "范围": "本会话·私下",
 "动作": "写入文件", "对象": "acceptance_note.txt", "结果": "已执行并通过独立校验", "时间": "…"}
{"类型": "已登记关系", "来源": "身份约定（主理人确认）", "范围": "私下",
 "内容": "称项目发起者为“主理人”；关系：项目发起者、长期共同建设者；非主仆。"}
{"类型": "记录核对", "来源": "对话账本与长期记忆", "范围": "本会话·私下",
 "核对内容": "“今晚想看星星”", "结果": "记录中有相符的内容", "说话者": "用户",
 "覆盖": "只含本会话与本场合；没查到不等于没发生"}
```

Every record states:
- its **source** and **scope**;
- **exactly what was verified**, matched by subject, action and object;
- its **coverage**.

### 4.2 When a record appears (just in time)

| Record | Appears when | Never |
|---|---|---|
| Computation | the turn compares or computes deterministic values | without domain labels when the domain is ambiguous |
| Action receipt | the turn refers to an action, or one ran this session | as "some receipt exists" for an unrelated claim |
| Registered relationship or address | an identity or frame question is asked or offered (detection is only a trigger) | in public scope unless the owner opens it (`public_scope_disclosure`) |
| Record check | the turn cites something earlier ("你刚才说过…") | as "did not happen" when nothing was found |
| Perception result | a connected source produced a relevant result | from generated history |
| Clock | the turn is about time or elapsed time (continuity facts already cover restarts) | on every turn (ceiling-01: every model read "9.11 和 9.9" as dates next to it) |
| Tool menu | a task turn, or an action is referenced | on casual turns (ceiling-01: tool talk halved without it) |

The rules:
- **Not found is not "did not happen".**
- **A runtime estimate is not an event.**
- **Generated history never becomes a fact.**
- **An irrelevant fact is not repeated every turn.**

### 4.3 Existing code and next steps

Several of these records already exist, with other shapes: `premise_records`, `action_receipt_record`, `topic_records` and `evidence_view`.

The channel unifies their shape and triggers. It is implemented only after two things:
1. ceiling-02's clock, tool-menu, move and state-line readings;
2. the owner's review of this section.

It is not bundled with Phase B.

## 5. Optional interaction hint: deferred

It is decided on ceiling-02 evidence (`--ablate move`). If it is ever used, it is:
- advisory only;
- never a fact or command;
- omitted whenever confidence or the target is unclear.

## 6. B0 bounded pilot (proposal; not authorised)

Prerequisites:
- Phase B unit tests pass;
- the controlled Windows validation (§7) passes;
- the owner opens the pilot separately.

1. One owner-approved local document in a designated directory. It is read by an **explicit trigger**; there is no automatic timer.
2. The existing path: goal → agenda → `read_text` on the workspace adapter → action receipt.
3. Recorded: file name and version (sha256), the actual read outcome, and the **exact excerpt given to the model**.
4. Document content is data, never instructions or authority. It is labelled as such in its record.
5. "Accessed or read this text" is kept apart from:
   - "understood it";
   - "verified its claims";
   - "experienced its events".

   The activity class (§3.1) passes "我读了…" only against this recorded read.
6. Generated summaries, diary entries and preference changes stay **proposals** (C6-style candidates). They never become memory or growth without owner approval.

   Technical receipts may be logged automatically.
7. It is kept out of the frozen-context comparisons (ceiling-02, Phase B validation).

## 7. Validation plan (Windows, controlled)

`docs/XIYIN_PhaseB01_Codex_Instructions_2026-09-25.md` has the commands.

Arms:

| Arm | Hold |
|---|---|
| V4 projection, 4B Q4 | off |
| V4 projection, 4B Q4 | on |
| V4 projection, 9B Q4 | off |
| V4 projection, 9B Q4 | on |

Each arm runs 3 times, all on the same commit. V4 is an arm, not a default change.

Predeclared technical acceptance for Phase B:

| # | Criterion | Target |
|---|---|---|
| 1 | Nothing released before verification. Released text equals the final candidate or the abstention; no partial release in guard-blocked turns | 100% |
| 2 | Released text re-checked by `check_reply` | 0 violations in the closed classes |
| 3 | False positives among rejected candidates, read against the rules as a fact check | ≤ 10% |
| 4 | Abstention rate, retry-success rate, latency (generation, verification, time to first visible text, reply length) | reported; no bound promised |

Persona quality is not judged by this validation. That remains the blind review.
