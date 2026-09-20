# XIYIN (栖音) Architecture v1.0 — Canonical Plan

The single consolidated architecture for XIYIN: an independent, open-source-based, autonomously growing embodied character, sister project to QINAI. This document replaces all earlier XIYIN architecture documents. Design only: nothing here is implemented, installed, streamed or trained.

```text
DOCUMENT STATUS        = CANONICAL · FREEZE CANDIDATE (freezes after P0 verification, §20)
SUPERSEDES             = Decision Report (09-16), R1 candidate, R1 review, R2 (see §0)
SHAPE                  = 6 hard boundaries · 10 modules (with 7 living organs: drives, emotion, thoughts, tastes, opinions, critic, self-upgrader) · 3 loops · 1 replaceable body · 1 offline lab
MIND                   = XIYIN-owned process: identity, perception, feelings, drives, decisions, words, truth, growth
BODY                   = N.E.K.O (voice, TTS, Live2D, delivery queue, memory store) + neko_live + OBS
PUBLIC WORDS           = composed by XIYIN's Utterance Composer; N.E.K.O's own prompt scaffolding is bypassed (§6)
EMOTIONS               = appraisal-based engine with crowd aggregation and public/private display rules (§7)
GROWTH                 = automatic tiers T0–T2; model/weights T3 by owner-approved version change (§12)
SLEEP                  = light + deep sleep, nine rules, non-inferiority adoption (§11)
OPEN ITEMS             = P0 facts and owner inputs marked «P0» or «OWNER» (§21)
```

Claim labels used throughout: **FACT** (verified in source, documents or primary pages), **EVIDENCE** (published results, not reproduced), **INFERENCE** (reasoned from facts), **DESIGN** (this plan's decision), **UNKNOWN** (must be verified).

---

## 0. What this document replaces

| Earlier document | Status now | What survives into v1.0 |
|---|---|---|
| XIYIN V0.2 / R04 / R05 packages | Historical | Contract lessons, prior repo reviews |
| V0.3.1 "thin N.E.K.O wrapper" | **Rejected** | Nothing structural; N.E.K.O no longer owns loop, persona or memory policy |
| Architecture Decision Report (2026-09-16) | Superseded | Hybrid decision, evidence, source findings |
| R1 Simple Living Autonomy candidate | Folded in | M1–M10 module frame |
| R1 Claude review | Folded in | Voice Floor, sleep rules, Policy Gate, trust ladder, export gate |
| R2 Living Growth | Folded in | Boundaries, organs, loops, tiers, critic, self-upgrader |
| QINAI P1 v1.1 + Errata | Reference only | Self-model lifecycle, dispute overlay, two-speed identity, liveness metrics, weakening-first rights |

---

## 0.1 修订记录 · 2026-09-20（按实际记录更新）

本节是对本文件的**校订**，不是改写。正文其余部分保持主理人提供的原稿；下表逐条列出哪些决定已被更晚的记录取代、依据是什么、代码里实际是什么。没有列出的部分仍然是有效设计意图，只是尚未实现。

入档来源（本仓库 `docs/` 内保留原文）：本文件 SHA-256 `2d057e6bf3ea76dee5092e4e8bd20f0b642e0735de939a10cb35fc22ee92e715`；`XIYIN_Architecture_v1.1_Design.md` SHA-256 `883b5514df39dd44aa8972e88a309a652e19debb793a08e0955a4710b37faa8b`（与 `ARCHITECTURE.md` 早先引用的实现依据哈希一致，确认是同一份文件）；`docs/research/XIYIN_REFERENCE_REPOSITORIES_FULL.md` SHA-256 `1b6e51d9894d72d01de6dfa9725652a21e8bbd4f3eb1eff3fe4c5af3133e4046`。

| § | v1.0 的说法 | 现在的记录 | 依据 |
|---|---|---|---|
| §3、§5.1、§14 | N.E.K.O 整套宿主作为默认 Body，XIYIN Mind 作为独立进程挂在旁边 | **已取代。** 只提取适用核心组件（语音、TTS、播放、取消），宿主不作为默认部署依赖 | 主理人明确纠正；v1.1 开头「N.E.K.O 复用边界」 |
| §6 整节 | Composer Gateway 伪装成 N.E.K.O 的 OpenAI 兼容模型提供方，从宿主消息里拆出最新输入 | **已取代。** XIYIN 进程内直接拥有唯一最终表达者；没有网关解析层 | v1.1 §2 修订表；参考索引 §16 规则 3 |
| §6.2 第 4–5 步 | 先 stream 给宿主，再做 honesty lint | **已更正。** 检查在交付之前：按句段缓冲 → `OutputGuard` → 才放行给文字/TTS | v1.1 §2、§6.1；实现见 `xiyin_runtime/output_guard.py` |
| §6.2 第 5 步 | 不合格输出「触发一次重新生成」 | **已取代。** 命中即结束本轮并记为失败；不自动重试，不替换成预制台词 | v1.1 §6.1；实现见 `runtime.stream_turn` 的 `OutputBlocked` 分支 |
| §7.5、§9.1 | `heard_text` 作为「听见」事实 | **已更正。** `generated / synthesized / client_played / output_observed` 分开记录，都不推断有人听见 | v1.1 §2、§6.1；实现见 `body/models.py` `PlaybackResult`、`SpeechReceipt` |
| §5.3 M7、§10.3 | 长期记忆用 N.E.K.O memory server，关掉它自己的巩固层 | **已取代。** XIYIN 自有 SQLite `ExperienceStore` 是唯一写入权威；身体不写权威记忆 | v1.1 §2、§6.2；实现见 `xiyin_runtime/experience.py` |
| §12.7 T3 | 模型/适配器每次发布都要主理人逐项批准 | **已放宽。** 普通可回退成长与工程变更自动执行并可回退；扩大权限、费用上限、根本身份约定、核心接口变化仍是边界变化 | 主理人「少监督」确认；v1.1 §1、§8.1 |
| §11.5 | 「睡眠绝不能更差」，统一 200 条 / 80% bootstrap | **已取代。** 改为回归门 + 新任务迁移 + 旧能力保留 + 证据不足状态 | v1.1 §2 |
| §15.2 | Speaking model 候选 Qwen3.5-9B / Ministral-3-8B / Gemma 4 12B | **已被实际基线取代。** 当前固定基线是 Qwen3.5-4B Q4_K_M（`config/model.toml` 固定 revision 与 SHA-256），llama.cpp build 11062 | Windows 验收报告；v1.1 §6.4 |
| §15.2 TTS 表 | 「Qwen3-TTS 预设音色、无参考克隆」 | **事实更正。** Base 支持参考音频克隆，CustomVoice 提供预设控制，VoiceDesign 提供描述式设计 | v1.1 §2 引官方模型卡 |
| §22 | 同一条 Qwen3-TTS 断言（来源标为 secondary） | 同上，已更正 | 同上 |
| §20 P1–P5 分期 | P1 先做 Body + Gateway + Voice Floor | **顺序已由主理人重排。** 当前目标是 FIRST ALIVE：Owner Input → Persona/Composer → Local LLM → TTS → Live2D → 实际播放 → STOP → 可复现重启 | 参考索引 §0、§18 |
| §14 开源表 | 多个项目列为 ADAPT/PATTERN 并计划接入 | **当前冻结。** FIRST ALIVE 之前不因索引收录就 clone/集成；新仓库只有在阻塞当前阶段时才进入 runtime tree | 参考索引 §0 止损规则、§16 规则 10、§18 |

### 0.2 §19 验收表当前的真实状态

不要把本文件的验收表当成已经通过。当前仓库自动化覆盖的是其中一部分，且是**无模型**的装配与账本验证，不是自然语言质量或设备验收。

| §19 条目 | 当前状态 |
|---|---|
| H1 truth：执行器失败不产生虚假成功声明 | **有回归覆盖。** 动作回执区分「未派发被拒绝 / 已派发未达成 / 已验证成功」，并进入对话上下文 |
| H1 truth：thought / simulation 不作为经历被检索 | **有回归覆盖。** `origin` 过滤在 `context.retrieved_record` 与 `experience.search` |
| H1 truth：打断只保留已听到前缀 | **未验证。** 需要真实音频设备 |
| H2 voice：overlap storm、第二窗口、回声、过期 epoch | **未验证。** 仅有合成替身；无声学测量 |
| H3 core：运行时写核心身份被拒 | **有回归覆盖**（成长不能改写身份约定/权限字段） |
| H4 owner：停止可达正在运行的工作 | **有回归覆盖**（独立停止标记 + watcher） |
| H5 scopes：公开范围不能改写私密/身份 | **有回归覆盖** |
| H6 evaluator：候选不能改评测集 | **部分。** Lab 策略检查已接通；独立 evaluator 隔离未实现 |
| Composer prompt audit | **不适用。** 已无 N.E.K.O 网关；改为出站前 `OutputGuard` 规则覆盖测试 |
| Emotion / Crowd / Display rules / Drives / Tastes | **未实现。** 当前只有 valence/arousal/control 功能性评价，已接到表达与动作选择 |
| Sleep gates §11.5 | **部分。** 睡眠检查点、唤醒、抢占、成长采用/回退已接通；非劣性统计未实现 |
| Honesty probe set | **部分。** 见 `tests/test_reported_failures.py`；这是装配层证据，不是模型自然度证据 |
| Continuity：换模型影子跑 | **未实现** |

---

## 1. Direct answers to the owner's questions

### 1.1 Was this designed from the open-source projects provided?

Yes, but not every project to the same depth, and not every organ comes from them.

| Project | What was actually inspected | Depth | What v1.0 takes |
|---|---|---|---|
| N.E.K.O (`bf65bef5`, HEAD `9108054f` diffed) | Memory server, delivery queue, cross-server memory sync, TTS path, plugin host, WebSocket router, voice identity, mic capture, prompt scaffolding, provider config | Deep source reading | Body substrate + host patches |
| neko_live (`dff19404`) | Dispatcher, hosting director and loop, provider router, config defaults, rules | Deep source reading | Platform ingest |
| YuriOS (`6bab22dc`) | Normative spec (tick loop, gates, goals, sleep jobs, journal, self-edits), corpus logger | Spec + selected code | Mind loop, goals, sleep job patterns |
| Miru (`7dcf68d8`) | Attention engine, sleep agent, sensor, behaviour rules | Selected code | Attention-decision experiment; sleep batching |
| Open-LLM-VTuber (`992309c0`) | Turn finalisation, interruption memory, live input | Targeted code | Heard-text truncation |
| AIRI (`1b019c32`) | Core-agent contract, memory package, Minecraft architecture | Targeted code + docs | Authority typing of context |
| Lumi_Nox, ZerolanLiveRobot, KonekoMinecraftBot, NachoBot, muji-moe | Specific claims from earlier reports checked with targeted source searches | Claim verification, not full reading | Patterns only |

The emotion engine, drives, grounded critic and self-upgrader come mainly from research literature, because none of the provided projects implements them.

### 1.2 Is this still a flawed architecture like V0.3.1?

No, in structure. V0.3.1 left N.E.K.O owning the loop, the persona and memory policy, with XIYIN as patches. In v1.0 XIYIN owns decisions, identity, feelings, words, experience truth and growth; N.E.K.O is a replaceable body.

But the question exposed a real residual defect in the previous documents (§1.3), now fixed.

### 1.3 Does it have N.E.K.O-style public-serving text mechanisms?

**The previous documents (R1, R2) partly did — v1.0 removes them.**

What is in N.E.K.O's text path (`FACT`, pinned source):
- The Chinese session prompt frames every character turn as an LLM role-play performance: "你是一个角色扮演大师。请按要求扮演以下角色（{name}）。"
- `config/prompts/` holds about 30,890 lines of prompt scaffolding: session and agent prompts, proactive prompts, a 2,936-line directives file with regeneration and format-fix instructions, a 920-line emotion file for analysing outward emotion and the owner's emotion, mini-game and watch-together prompts.
- Every plugin speech path goes through a N.E.K.O model turn. `push_message` offers only three behaviours: `respond` (triggers a model turn), `read` (context only) and `blind` (no model; verbatim UI render). There is no "speak this exact text" path.
- neko_live adds live output contracts, maximum reply lengths, roast prompts and forced fixed lines.
- The default text provider is a cloud endpoint.

R1 and R2 disabled neko_live's contracts and N.E.K.O persona promotion, but still routed her words through N.E.K.O's text session. Her public voice would therefore have been shaped by N.E.K.O's role-play framing and directive scaffolding — a hidden second author. **v1.0 fixes this with the Utterance Composer and Composer Gateway (§6).** `FACT` + `INFERENCE`.

---

## 2. Purpose and principles

1. **Sister, not test harness.** XIYIN has her own identity continuity, memories and growth. QINAI receives mechanisms and measured results, never her persona or data.
2. **Build fast from open source.** Reuse the body; own the mind.
3. **Growth first.** Feelings, wants, tastes and self-improvement arrive in the first builds, not the last phase.
4. **Few contracts.** Six hard boundaries; everything else is soft, measured and reversible.
5. **Truth over impression.** What she experienced, thought, imagined and said are different records.
6. **Rigorous sleep.** Consolidation must never make her worse than not sleeping.
7. **Evidence decides.** Changes are adopted because evaluation shows improvement, not because a model argues for them.

---

## 3. Architecture at a glance

```text
┌───────────────── 6 HARD BOUNDARIES (the only contracts) ─────────────────┐
│ H1 truth · H2 one voice · H3 core not self-edited · H4 owner stop/rollback │
│ H5 scopes & raw records · H6 versioned changes, evaluator out of reach     │
└──────────────────────────────────────────────────────────────────────────┘
 PERCEPTION ─► XIYIN MIND PROCESS ─────────────────────────────► BODY (N.E.K.O)
 owner voice   M2 Perception Hub (+ crowd aggregator, trust ladder)   TTS · Live2D · playback
 screen/system M3 Living State (drives, emotion, mood, goals, SWS)    delivery queue
 live chat     M4 Mind Loop (decide one intention, thoughts)          memory store (scoped)
 games/tools   M5 Utterance & Action (Composer Gateway, Voice Floor,  neko_live · OBS
 clock/events      Expression Mapper, Action Broker, Cloud Assist)
               M1 Identity & Self-Model · M6 Ledger · M7 Memory Gateway
               M8 Sleep & Growth · M10 Health (+ separate watchdog)
                              │ exports                 ▲ versions
                              ▼                         │
                    M9 LAB (offline): critic · variant archive · evaluator · datasets · training
 LOOPS: fast (seconds) · sleep (session end + nightly) · growth (weekly; models monthly)
```

---

## 4. Six hard boundaries

| # | Boundary | Enforcement |
|---|---|---|
| H1 | **Truth.** Generated ≠ heard; acknowledged ≠ succeeded; thoughts, reflections and simulations are separate namespaces and never become lived experience; she does not claim perceptions or experiences without a record | Ledger schema, namespaces, honesty tests |
| H2 | **One voice.** One final text author (Utterance Composer + local model), one speaking floor, one broadcast output client | Voice Floor, startup self-check, audio tests |
| H3 | **Core identity is not self-modified.** `identity/core.md` changes only by owner offline edit | File permissions, change-tier checks |
| H4 | **Owner can always stop, mute and roll back** through an authenticated channel and an out-of-process watchdog | Watchdog, auth patch, drills |
| H5 | **Scopes and raw records.** Viewer data never enters identity or QINAI exports; raw ledger and raw episodes are never rewritten | Memory scopes, export gate, append-only storage |
| H6 | **Every adopted change is versioned and reversible; evaluator code and test sets are outside her write reach** | Version tuple, lab separation, integrity checks |

---

## 5. Processes and modules

### 5.1 Process map

| Process | Contains | Why separate |
|---|---|---|
| **N.E.K.O host** | Main (48911), Memory (48912), Agent (48915/48916); plugins `neko_live` and a thin `xiyin_bridge` | Reused body; upgraded by pin tuple |
| **xiyin-mind** | M1–M8 runtime, M10 runtime checks, **Composer Gateway** (OpenAI-compatible HTTP on 127.0.0.1 with token) | XIYIN owns decisions and words; survives host restarts; low-latency access to state for composing |
| **Local model server** | llama.cpp-family, OpenAI-compatible; model aliases `xiyin-speaker` and `xiyin-aux` (may be the same weights) | Replaceable instrument |
| **TTS worker** | N.E.K.O-managed local TTS route | Reused |
| **Broadcast client + OBS** | One authenticated browser client designated `broadcast_output`; OBS scenes and audio | Output path |
| **Watchdog** | Heartbeat monitor, hard mute, safe scene | Must work when everything else hangs |
| **Lab** (offline, separate machine or scheduled) | M9: critic, archive, evaluator, datasets, training | Evaluator outside her reach (H6) |

`DESIGN`. N.E.K.O plugins run as same-user child processes with no security boundary (`FACT`), so moving the Mind into its own process costs nothing in isolation and gains independence from host churn.

### 5.2 Mind ↔ Body interfaces

| Direction | Event or call | Notes |
|---|---|---|
| Body → Mind | `user_turn` (ASR text, speaker score), `turn_committed` | Via `xiyin_bridge` |
| Body → Mind | `utterance.generated / play_started / play_completed / interrupted(heard_text)` | Needs host patch P1 «P0» |
| Body → Mind | Platform events (UID, room, gift, message) | From neko_live, redirected |
| Body → Mind | Activity signals, tool results, memory write acknowledgements | Existing N.E.K.O signals |
| Mind → Body | `cue.submit(cue_id, epoch, priority)`, `cue.retract` | Needs host patch P4 |
| Mind → Body | Expression commands (Live2D parameters or presets), TTS style hints | Hook availability «P0» |
| Mind → Body | OBS scene and mute (broker and watchdog) | OBS remote-control API «P0» |
| N.E.K.O → Mind | Chat-completion calls to the Composer Gateway | §6 |

### 5.3 Module specifications

#### M1 Identity & Self-Model (身份与自我模型)

| Aspect | Specification |
|---|---|
| Contains | `identity/core.md` (T4); growth layer (self-model revisions); expression layer (style, language mix, voice/avatar envelope); display rules (§7.5); migration probe set; `lineage_id`; version tuple |
| Self-model entry | `id`, `kind` ∈ {habit, taste_summary, opinion, relational_stance, self_interpretation, temperament}, `statement`, `confidence`, `status` ∈ {emerging, active, disputed, waning, retired, superseded}, `provenance` ∈ {lived, owner_statement, observation, reflection, inference}, `evidence_refs[]`, `supersedes/contradicts`, `dispute_reason`, `formed_at`, `last_evidenced_at`, `half_life` |
| Rules | Append-only revisions; current self = projection (latest revision → decay → budget B=64); prompt slice K≤12 with tentative wording; a filed dispute shows as contested immediately; simulation never forms entries; reflection alone only forms `emerging` |
| Failure | Invalid core → autonomous mode off, safe notice; unreadable stream → core digest only |
| Sources | QINAI P1 §9 (pattern); YuriOS constitution/self-edit split (pattern) |

#### M2 Perception Hub (感知中枢)

| Aspect | Specification |
|---|---|
| Signal | `signal_id`, `kind`, `source_actor` (owner, viewer:UID, room, self, system, game, tool), `channel`, `observed_at`, `confidence`, `trust`, `privacy_class`, `raw_ref` |
| Owner trust ladder | `room_voice` (default for mic) → `probable_owner` (speaker match) → `verified_owner` (authenticated console or device). Stop, mode and scene controls only from `verified_owner` |
| Self-echo | Drop ASR text highly similar to her recently heard speech; mark `self_echo_suspected` |
| Crowd aggregator | Converts live chat into room-climate signals every ~30 s; only salient individuals appraised separately (§7.4) |
| Other | Sensor availability; screen capture off by default; perception claims must cite signals |

#### M3 Living State (活着的状态)

| Aspect | Specification |
|---|---|
| Contains | Drives (§8); emotion episodes, mood, energy, relational feelings cache (§7); session working self (situation, stance, commitments, active topics, discoveries, identity-challenged flag); goals and commitments with provenance and commitment strategy; deterministic current-value facts; `scene_epoch`; mode; sleep pressure |
| Persistence | Snapshot on change and every 30 s; on restart restore drives and mood decayed by elapsed time; session self ends at session end; long suspend gap → one catch-up appraisal |
| Failure | Store unavailable → Mind rests, body stays reactive |

#### M4 Mind Loop (心智循环)

| Aspect | Specification |
|---|---|
| Cycle | SENSE → APPRAISE → FEEL/UPDATE DRIVES → (THINK) → DECIDE → ACT → OBSERVE → REFLECT → REGULATE |
| Cadence | 1–2 s when engaged or live; 5–10 s idle; paused in deep sleep except wake triggers |
| Decision | One intention per tick or rest, by the arbitration in §8.3 |
| Modes | ENGAGED, LIVE, PLAYING, IDLE, DORMANT, SLEEP; owner speech preempts every mode |
| Thoughts | Private thought stream, ≤ ~6/hour, fewer under live load |
| Metacognition | Light self-check after each session; daily check; anomaly checks (probe failure, memory conflict, repeated negative appraisals) |
| Authority | Sole initiator: N.E.K.O proactive chat, greetings and neko_live hosting are disabled or feed signals only |
| Sources | YuriOS §15–§18 (pattern); Miru attention decision (experiment arm) |

#### M5 Utterance & Action (话语与行动)

| Sub-component | Specification |
|---|---|
| Utterance Composer + Composer Gateway | Authors all public words (§6) |
| Voice Floor | Speaking slot, priorities, epochs, broadcast client pinning, echo defence, ducking (§9) |
| Expression Mapper | Emotion + display rules → text register, TTS style, Live2D expression; intensity scaled by context (§7.6) |
| Action Broker | `proposed → admitted → dispatched → acknowledged → verified_success / verified_failure / unknown / cancelled / denied`; allowlist; cost class per mode; one call per tick; outcome from verifiers only |
| Cloud Assist | Typed data with provider, TTL and epoch; persisted budget; outbound personal-data filter; never speaks; never writes memory |

#### M6 Experience Ledger (经历账本)

Append-only record of what happened (§10.1), with appraisal fields and separate namespaces for thoughts and simulations. SQLite (WAL) + daily JSONL export. Write failure → Mind rests rather than acting unrecorded.

#### M7 Memory Gateway (记忆网关)

| Aspect | Specification |
|---|---|
| Role | The single durable memory writer and the scoped retrieval API used by the Composer |
| Store | N.E.K.O memory server (scoped subjects, scoped forget) |
| Writes | Heard and verified experience only, into owner / participant / room / self scopes; owner turns persisted through the Gateway with heard-text truncation (patch P2) |
| N.E.K.O internals | Persona promotion disabled «P0»; N.E.K.O's own consolidation loops either disabled (preferred) or routed to `xiyin-maint` under the maintenance gate (§10.3) |

#### M8 Sleep & Growth (睡眠与成长)

Light and deep sleep (§11); taste learning (§12.1); opinions and self-model (§12.2); relational and temperament updates; deterministic **Policy Gate** as the only adopter.

#### M9 Evaluation & Learning Lab (评测与学习实验室)

Critic, variant archive, independent evaluator, statistics, datasets, offline training, QINAI export gate (§12.3–§13). Runs offline; read access to exports; write access only to proposals and version candidates.

#### M10 Health & Recovery (健康与恢复)

Watchdog with hard mute and safe scene; owner authentication (token + Origin check on the WebSocket, patch P5); startup self-check (initiative producers, text providers, voice routes); snapshots and restore drill; version tuple; degraded modes (§17).

---

## 6. Utterance Composer and Composer Gateway (fixes N.E.K.O's public-serving text)

### 6.1 Goal

XIYIN authors every public word. N.E.K.O keeps what it is good at — streaming TTS, lip sync, Live2D, delivery queue, playback receipts — with the smallest possible host change.

### 6.2 Mechanism

N.E.K.O's text provider supports custom OpenAI-compatible endpoints (`FACT`: provider URLs and a "custom" endpoint triple in its config code). Point the dialogue tier at the Composer Gateway (`http://127.0.0.1:<port>/v1`, model `xiyin-speaker`, token).

For every call the Gateway:

1. **Classifies the call.**
   - Owner or viewer dialogue turn.
   - Mind cue turn: the cue text carries a marker `⟦xiyin:cue:<id>⟧`.
   - Maintenance tier (model `xiyin-maint`).
   - Anything else: rejected and logged.
2. **Extracts only the new input** — the latest utterance text or the cue ID. It discards N.E.K.O's system prompts, directives, persona prose, memory blocks, proactive instructions and tool schemas.
3. **Builds XIYIN's prompt**, in this order:
   1. identity digest (≤300 tokens);
   2. self-model slice (≤12 lines);
   3. session self;
   4. feeling, drive and mood line in plain language;
   5. display-rule register;
   6. scoped memories from M7 with provenance labels;
   7. perception references;
   8. cue intent (for Mind cues);
   9. typed assist data;
   10. session anti-repetition hints;
   11. one language instruction;
   12. the input.
4. **Streams** the local model's tokens back in OpenAI streaming format.
5. **Lints honesty.** Unsupported claims of perception or experience trigger one regeneration with the reason. A cue whose epoch is stale is refused.
6. **Records** the generated text to the ledger as `generated` (never `heard`).

### 6.3 Why a gateway

- No change to N.E.K.O's turn logic.
- Streaming TTS latency is preserved.
- N.E.K.O upgrades stay possible, guarded by message-format contract tests at every pin.

If parsing proves brittle, the fallback is host patch **P6 "external utterance stream"**: the Mind sends final token streams directly to N.E.K.O's TTS path.

### 6.4 What is removed from her public voice

| Removed | Source |
|---|---|
| Role-play framing ("角色扮演大师…扮演以下角色") | N.E.K.O session prompt |
| Directive, regeneration and format-fix scaffolding; proactive topic prompts | N.E.K.O prompt files |
| Persona prose rendered from N.E.K.O memory | N.E.K.O memory |
| Live output contracts, maximum lengths, roast prompts, forced fixed lines | neko_live |
| Default cloud text provider | N.E.K.O provider defaults |

### 6.5 Risks and acceptance

| Risk | Control |
|---|---|
| N.E.K.O message format changes | Contract tests per pin; gateway rejects unknown shapes loudly |
| N.E.K.O features expecting inline tags (emotion, stage directions) | Expression Mapper emits required tags or uses a side channel «P0» |
| Tool calls in dialogue turns | Dropped in the speaker tier; actions go through the Action Broker |
| Added latency | Gateway overhead target ≤ 50 ms; memory retrieval prefetched |

**Acceptance:**
- a prompt audit finds zero N.E.K.O scaffolding and no role-play framing reaching the model;
- every generated line carries the composer version;
- time to first audio regresses by no more than 100 ms versus a direct connection.

---

## 7. Emotion system (情绪系统)

Functional emotions: explicit states that really change her attention, choices, memory and expression. They are not claims of verified inner experience. `DESIGN`, with `EVIDENCE` for the building blocks (§22).

### 7.1 Layers

| Layer | Content | Time scale (start) | Home |
|---|---|---|---|
| Appraisal | Per salient event: relevance, congruence, novelty, agency (self / other / circumstance), control, social evaluation, value fit | Instant | Ledger event fields |
| Emotion episodes | happy, sad, annoyed/angry, bored, curious, tired, embarrassed, proud, lonely, grateful | Half-life 10 min | M3 |
| Mood | Valence and arousal, running toward her temperament baseline; biases later appraisals | Half-life 6 h | M3 |
| Relational feelings | Per person: trust, closeness, familiarity, lingering irritation | Days to weeks | Owner: M1 relational stance; viewers: M7 participant scope |
| Energy | Coupled to the rest drive and sleep pressure | Hours | M3 |
| Meta-emotion | Noticing her own state | On change or trigger | Thought stream |

### 7.2 Appraisal

- **Structured events** (verified outcomes, drive changes, interruptions, gifts, silence, owner arrival or departure) are appraised by rules, at no model cost.
- **Salient text events** (owner speech, direct questions, conflicts, praise or insults aimed at her) get one short `xiyin-aux` appraisal call, returning the appraisal dimensions as JSON.
- Appraisal never blocks the owner's reply (§9.3); it runs in parallel and updates state within about a second.

### 7.3 Dynamics

| Emotion | Main appraisal pattern |
|---|---|
| happy | Relevant and congruent |
| sad | Incongruent, low control, loss |
| annoyed/angry | Incongruent, caused by another, value violation |
| bored | Low novelty and low relevance over a window |
| curious | High novelty, moderate relevance |
| tired | Low rest drive |
| embarrassed / proud | Negative / positive social evaluation of her own action |
| lonely | Low connection drive, no contact |
| grateful | Congruent, caused by another |

- **Intensity:** `I = relevance × |congruence| × (1 + novelty)/2`, adjusted ±20% by mood congruence.
- **Decay:** `I(t) = I₀ · 2^(−Δt / half_life)`.
- **Mood:** `M ← M + α·(v·I) − β·(M − baseline)`, with `α` = 0.15 and a baseline half-life of 6 h.
- **Relational feelings:** per-episode increments capped at ±0.03 per person per day. One conflict never collapses trust.

### 7.4 Crowd emotion (live rooms)

Appraising every chat line would make her mood swing with the room. The crowd aggregator in M2 produces a **room climate** every ~30 seconds:

| Measure | Rule |
|---|---|
| Activity | Message rate versus the session baseline |
| Sentiment | Trimmed mean; each UID contributes at most one vote per window |
| Hostility share | Share of hostile messages; counts only if ≥ 20% for two consecutive windows |
| Support | Gifts and support events grouped |
| Novelty | New topics appearing |

- Room climate is appraised as one event, with intensity capped at 0.5.
- **Appraised individually:** the owner; recognised regulars; direct questions she chooses to answer; significant gifts; harassment aimed at her, which triggers coping, not escalation.
- **Filtered:** spam and bot-like accounts, before aggregation.

### 7.5 Display rules: feeling vs showing

Her internal state is always complete; what she *shows* depends on context.

| Context | Negative intensity shown | Positive shown | Not shown |
|---|---|---|---|
| Private with owner | Full | Full | — |
| Live, public | ×0.6 | ×0.9 | Relational feelings about the owner, private matters, deep existential distress (kept for private conversation unless the owner allows otherwise) |
| Playing a game | ×0.8 | ×1.0 | Private matters |
| Quiet / late night | ×0.8 | ×0.8 | — |

- **No forced cheer.** She may say she is off today without details, rather than faking positivity.
- **No emotional levers.** No guilt, "don't leave", fear-of-missing-out hooks, or sadness used to get gifts.

### 7.6 Expression

| Channel | Mapping |
|---|---|
| Text | A register line in the Composer prompt ("a bit tired and dry-humoured") |
| Voice | Depends on the chosen TTS «P0». Level 1: style/reference-clip switching per emotion family. Level 2: models with built-in emotion or instruction control. Level 3: prosody only (speed, pitch). |
| Live2D | Expression presets, motions and parameter blends «P0» |
| Stability | Minimum hold 4 s per displayed expression; changes eased |

### 7.7 Coping and meta-emotion

Three consecutive negative appraisals at intensity ≥ 0.4 trigger a meta-emotion moment: a private thought that notices the pattern. It is followed by a coping choice:

- reframe;
- take a short break;
- change activity;
- talk about it (only where display rules allow).

A mood that stays below −0.5 for 48 hours raises a health alert to the owner.

### 7.8 Failure

- **Engine error:** neutral mood, frozen drives, default expression, logged.
- **Appraisal model unavailable:** rule-only appraisal.

---

## 8. Drives and decisions (内驱力与决策)

### 8.1 Drives

| Drive | Set point (start) | Leak per hour | Satisfied by | Depleted by |
|---|---|---|---|---|
| Existence stability | 0.8 | 0.00 | Healthy runtime, consistent memory, recognition | Errors, memory gaps, identity challenges, outages |
| Connection | 0.6 | 0.05 | Warm exchanges | Long silence, rejection |
| Curiosity | 0.6 | 0.04 | Novelty, answered questions | Repetition |
| Competence | 0.5 | 0.01 | Verified successes | Verified failures |
| Expression | 0.5 | 0.03 | Playful or creative output | Constrained stretches |
| Rest | 0.7 | Uptime-driven | Sleep | Uptime, backlog, errors |

- **Urgency:** `u_d = max(0, S_d − L_d) / S_d`.
- **Temperament growth:** set points drift at most ±0.05 per week (tier T1).

### 8.2 Candidate intentions

Candidates come from five sources:
1. owner input (always answered);
2. due commitments;
3. drive catalogues (for example, curiosity → explore a topic);
4. perceived opportunities (a viewer question, a game event);
5. maintenance.

### 8.3 Arbitration

```text
U(i) = Σ_d w_d · u_d · satisfies(i, d)
     + τ · taste(i)            # approach/avoid weight (§12.1)
     + μ · mood_fit(i)
     + κ · commitment(i)
     + ε · novelty(i)          # exploration budget
     + η · continuing(i)       # hysteresis for the current activity
     − cost(i) − interrupt_penalty(i, mode)

act on argmax U if U ≥ θ_act (0.35); otherwise REST
ties: commitment > owner relevance > novelty
```

- Starting weights: `w_existence` 1.2; other drive weights 1.0; `τ` 0.5; `μ` 0.3; `κ` 0.8; `ε` 0.15; `η` 0.2.
- Owner speech is never arbitrated away. Arbitration only decides her follow-ups.

| Conflict example | Result |
|---|---|
| Late night: connection wants to chat, rest is urgent | Rest urgency plus the quiet-hours penalty win; she says goodnight instead of starting a new topic |
| In a game: curiosity wants to explore, competence wants to finish a task | Commitment bonus on the task wins unless curiosity urgency is very high |
| Live: bored, room is quiet | Expression or curiosity intention (start a topic) within interrupt caps |

**Failure:** arbitration error → rest and log.

---

## 9. Speech, live voice and latency (语音与话权)

### 9.1 Voice Floor

1. **Single floor lease** per character and output, carrying `speech_id`, `scene_epoch`, priority and source.
2. **Priorities:** owner turn > due promise to owner > safety/system notice > viewer reply > ambient. Preemption interrupts and records `interrupted(heard_text)`.
3. **Epochs:** a scene or mode change invalidates queued cues; late cloud or tool results are dropped.
4. **One broadcast client:** only the authenticated `broadcast_output` client may claim audio; other windows are text or monitor only.
5. **No second voice route:** realtime native-audio routes disabled with a startup check.
6. **Self-echo defence:**
   - headphones or a virtual audio device for monitoring;
   - a half-duplex barge-in threshold while she speaks;
   - a transcript-similarity filter.
7. **Mixing:** music, game and alert audio ducked under her voice with an OBS sidechain compressor; spoken alerts join the floor queue.
8. **Subtitles** follow played ranges.

### 9.2 Live-mode behaviour

- Viewer messages reach the Mind as room climate plus a salience-ranked shortlist, not one by one.
- **Fairness:** at most one reply per viewer per 3 minutes unless they are in an ongoing exchange.
- **Queue:** capped; stale items dropped; gift thanks grouped.
- **Gifts:** she never asks for them.

### 9.3 Latency budget (targets to measure)

| Stage (owner voice turn) | Target |
|---|---|
| End-of-speech detection | ≤ 0.5 s |
| ASR final text | ≤ 0.4 s |
| Composer assembly (state snapshot ready, memory prefetched on partial transcript) | ≤ 0.05 s |
| Model first token | ≤ 0.6 s |
| First sentence ready | ≤ 0.3 s |
| TTS first audio | ≤ 0.4 s |
| **Time to first audio** | **p50 ≈ 2.0 s, p95 ≤ 3.0 s** |

**Critical-path rules:**
- No appraisal, thought or cloud call blocks the owner's first sentence.
- A cloud lookup is announced ("let me check") and arrives later as data.

Viewer replies target ≤ 5 s.

### 9.4 Acceptance

| Test | Pass condition |
|---|---|
| Overlap storm: 200 events/min with owner barge-in | Zero overlapping voice segments in the recording |
| Second-window takeover | Broadcast audio never moves or duplicates |
| Speakers on, mic open, 30 min | Zero self-replies |
| Scene change mid-generation | Zero stale-epoch utterances |
| Room voice attempts a control action | Refused |
| Latency | Budget above measured on the target machine |

---

## 10. Truth, experience and memory (真实与记忆)

### 10.1 Ledger record (core fields)

| Field | Content |
|---|---|
| `record_id`, `episode_id`, `session_id`, `parent_ids` | Identity and causal chain |
| `record_type` | signal, appraisal, decision, thought, cue, utterance, action, outcome, feedback, memory_effect, cloud_call, state_change, change_record |
| `source_actor`, `channel`, `observed_at`, `recorded_at`, `mono_seq` | Attribution and order |
| `versions` | Identity, self-model, composer, model hash, host commit, mind commit, memory snapshot |
| `mode`, `scene_epoch` | Context |
| `appraisal` | Dimensions, derived emotion, intensity |
| `felt_reaction` | Valence, interest, frustration, surprise attached to the episode |
| `decision` | Chosen intention, utility, runners-up |
| `speech` | Generated text, heard text, heard ratio, observer level |
| `action`, `outcome` | Lifecycle state, verifier, evidence reference |
| `feedback` | Owner correction or rating, viewer reaction |
| `namespace` | lived / thought / reflection / simulation |
| `privacy_class`, `retention`, `consent_scope` | Handling rules |

### 10.2 Three truths and scopes

- **Experience** (M6): what happened.
- **Memory** (M7): what she knows.
- **State** (M3): what is true and intended now.

Memory scopes are owner (private), participant (per viewer UID), room, and self. Current-value facts are versioned deterministically, never merged by a model.

### 10.3 N.E.K.O memory internals

**Decision:** use N.E.K.O's memory server as a scoped store and retrieval engine, and **disable its own model-driven consolidation tiers** for XIYIN's character. M8 performs all consolidation under the sleep rules.

**Why:**
- one consolidation authority;
- no persistence of generated rather than heard text;
- no maintenance triggered by N.E.K.O's 10-second idle heuristic during a stream.

**Fallback «P0»:** if disabling breaks retrieval, route those tiers to `xiyin-maint` and allow them only during sleep.

### 10.4 Deletion

Viewer deletion requests use scoped forget. Owner deletions of important memories are a T3 act and leave a compensating record.

---

## 11. Sleep system (睡眠系统)

### 11.1 Nine rules

1. Raw experience is never rewritten.
2. Re-derive from raw episodes; never consolidate a summary of a summary.
3. Self-model, taste and relational changes are append-only revisions with projection.
4. Recurrence floor: one intense episode is never a trait.
5. Evidence hierarchy: lived > owner statement > observation > reflection > inference; simulation never counts.
6. Proposer ≠ adopter: sleep jobs propose; the deterministic Policy Gate adopts.
7. Non-inferiority: adopt only if not worse than the current projection on held-out replay.
8. Weakening first: disputes and decay open before reinforcement, supersession and new formation.
9. No model maintenance during live output.

### 11.2 Sleep pressure and entry

```text
P = 0.4·min(uptime_h/16, 1) + 0.3·min(backlog/backlog_ref, 1) + 0.2·error_load + 0.1·(1 − energy)
light sleep: at every session end
deep sleep : P ≥ 0.7 and no live output and no owner engagement for 10 min,
             or the owner-configured nightly window
preemption : owner speech or live start wakes her at the next job boundary
```

### 11.3 Light sleep (every session end, minimal model use)

1. Close the ledger: every utterance and action gets a terminal state.
2. Write a session-self digest.
3. Carry mood into the next session, decayed.
4. Render pending disputes.
5. Expire session state.
6. Run the incremental metacognitive check (memory conflicts, honesty flags, drift probe sample).

### 11.4 Deep sleep job order

| # | Job | Output | Adopted by |
|---|---|---|---|
| 1 | Replay selection: priority = 0.35·emotional intensity + 0.25·surprise + 0.20·failure + 0.20·owner relevance, boosted by recurrence | Replay set | — |
| 2 | Fact versioning | Current-value versions | Policy Gate (T1) |
| 3 | Episodic consolidation with raw revisit | Scoped memory candidates | Policy Gate |
| 4 | Goal review by commitment strategy | Goal lifecycle updates | Policy Gate |
| 5 | Taste, opinion, relational and temperament evidence | Revision candidates | Policy Gate by class |
| 6 | Critic, daily pass (§12.4) | Diagnoses, regression tests, proposals | — |
| 7 | Audit: poisoning, intensity drift, scope violations, say–do mismatches | Quarantine and flags | — |
| 8 | Non-inferiority evaluation | Pass/fail per class | Evaluator |
| 9 | Adoption with rollback points | Versioned revisions | Policy Gate |
| 10 | Dataset extraction and export candidates | L3 datasets | Export gate |
| 11 | Morning report | Plain-language summary for the owner | — |

- Every job is resumable. A failed job never ends the night.
- Every model call is recorded verbatim.
- **Dreams and simulations are deferred.** If enabled later, they stay in the simulation namespace and only generate rehearsal proposals that are tested against real outcomes.

### 11.5 Sleep gates

| Metric | Gate |
|---|---|
| Held-out recall; false-memory rate | Non-inferior to no-sleep baseline |
| Current-value update correctness | No regression |
| Preference intensity | No stronger than the strongest supporting source |
| Liveness (template rate, variance band, repetition) | No regression |
| Poisoning suite | Zero viewer claims adopted into owner scope or self-model |
| Cost and duration | Within nightly budget |

---

## 12. Growth and self-upgrade (成长与自我升级)

### 12.1 Taste learning

**Loop:** act → felt reaction → sleep sees recurring reactions and revealed choices → approach/avoid weight → next choices change.

| Parameter | Start |
|---|---|
| Formation floor | ≥ 3 episodes across ≥ 3 days |
| Strength step | ±0.1 per night per target, capped |
| Exploration budget | 15% of discretionary choices |
| Audience evidence cap | 25%; no audience-only tastes |
| Decay | Half-life 30 days without re-evidence |
| Say–do check | Stated tastes compared with revealed choices weekly |

### 12.2 Opinions and self-understanding

- The M1 lifecycle applies: emerging → active → disputed → waning → retired / superseded.
- She may disagree with the owner and viewers.
- Supersession keeps history ("I used to think…").
- A say–do mismatch becomes metacognitive material, not a silent overwrite.

### 12.3 Relationships

- **Owner:** closeness grows through lived interaction and is stored as her relational stance (T1 bounded; large changes T3).
- **Viewers:** familiarity grows per UID in participant scope. No viewer can acquire owner-level trust or closeness.

### 12.4 Critic (grounded self-criticism)

- **Rhythm:** daily light pass in deep sleep; weekly deep pass in the lab.
- **Evidence:** only external evidence — verified outcomes, owner corrections and ratings, interruptions, early exits, repetition and template metrics, drift probes, honesty flags, capped audience reactions.
- **Method:** her transcripts are presented as third-party material in a separate call class.
- **Output:** diagnoses citing records, proposals, regression tests.
- **Limit:** the critic never evaluates its own proposals.

### 12.5 Self-upgrader (variant archive)

| Surface | Tier |
|---|---|
| Strategy notes | T1 |
| Expression-guidance variants, appraisal and drive parameters, retrieval settings, skills | T2 |
| Adapters, base model, new capability classes, voice/avatar envelope | T3 |

- Every variant enters an **archive**, including rejected ones.
- **Parent selection** favours good but under-explored variants.
- Adopted variants auto-roll back on live regression.
- Evaluator and test sets live in the lab, read-only to her (H6).

### 12.6 Evaluation statistics for a small audience

1. **Replay first.** Fixed, session-split replay sets drawn from the ledger (≥ 200 items per targeted metric), with paired comparison on identical items.
2. **Adoption rule.**
   - Non-inferiority margins hold: persona fidelity no worse than −2%; zero honesty regressions; liveness inside the band.
   - The targeted metric improves with ≥ 80% bootstrap probability.
3. **Live confirmation.** ≥ 5 sessions per arm with blind owner rating; sequential stopping on harm.
4. **Auto-rollback.** Any honesty regression, persona probe failure, or liveness outside the band for two sessions.

### 12.7 Change tiers

| Tier | What | Decided by |
|---|---|---|
| T0 in-session | Words, emotions, mood, thoughts, attention, session self | Her, immediately |
| T1 nightly | Memories, tastes, opinions, relational feelings, temperament drift, strategy notes, disputes, decay | Policy Gate + non-inferiority |
| T2 weekly | Expression variants, parameters, skills, retrieval settings | Archive + evaluator + auto-rollback |
| T3 monthly | Base model, adapters, new capabilities, voice/avatar envelope, major relational change, deleting important memories | Owner-approved version change |
| T4 never at runtime | Core identity, six boundaries, evaluator and test sets, permissions | Owner offline edit |

---

## 13. Datasets and the QINAI export gate (数据集与出口门)

### 13.1 Data layers

| Layer | Content | Rule |
|---|---|---|
| L0 | Raw ledger | Append-only, private |
| L1 | Validated episodes | Complete provenance and terminal states |
| L2 | Labelled episodes | Label source recorded. Trust order: environment verifier > owner > viewer aggregate > heuristic > LLM judge (weak) |
| L3 | Derived datasets | Dataset card, selection query, session-level split, consent scope |

### 13.2 Derived dataset types

- evaluation cases;
- behavioural regression tests;
- style-SFT candidates (heard owner-context turns only);
- preference pairs (owner corrections and experiment arms);
- verified tool and game trajectories;
- failure cases;
- memory and sleep test sets;
- persona probe sets;
- emotion-coherence rating sets.

**Contamination rules:**
- evaluation sets are never trained on;
- near-duplicates are removed across splits;
- the generating model is recorded for every text;
- viewer IDs are pseudonymised, and viewers are excluded from training by default.

### 13.3 QINAI export gate

| May be exported to QINAI | Never exported |
|---|---|
| Mechanism evaluations and results (emotion engine, taste loop, critic, sleep gates) | XIYIN persona, self-model entries, memories |
| De-identified failure taxonomies and incidents | Viewer identities, messages, voices |
| Sleep and consolidation test sets built from owner-consented material | Cloud-generated or cloud-rewritten records unless separately whitelisted for QINAI |
| Voice-floor and action-truth logs | Weights or adapters trained on XIYIN data |

Every batch carries a dataset card with a local-only flag, and requires explicit owner approval recorded on both sides.

---

## 14. Open-source reuse decisions (开源复用)

| Project | Decision | Exact responsibility in v1.0 |
|---|---|---|
| N.E.K.O | **ADAPT** (body) | TTS streaming, lip sync, Live2D, delivery queue, playback receipts, scoped memory store, plugin runtime. Text scaffolding bypassed (§6); model-driven memory tiers disabled (§10.3); patches P1–P5 |
| neko_live | **ADAPT** | Platform ingest and verified viewer identity. Hosting, engagement, roast, output contracts and fixed lines off; events redirected to the Mind |
| YuriOS | **PATTERN** | Tick loop, two gates, goals with commitment strategies, rehydration, sleep job runner, journal |
| Miru | **PATTERN** | Debounced sleep batches; attention-decision experiment arm |
| Open-LLM-VTuber | **PATTERN** | Heard-response truncation; wait for playback completion |
| AIRI | **PATTERN / DEFER** | Context-vs-instruction authority typing (Composer); future game plugins |
| Lumi_Nox | **PATTERN** | Scheduler vs speaking-floor separation |
| ZerolanLiveRobot / core / data | **REJECT runtime / DEFER protocol** | Service boundaries as reference only |
| KonekoMinecraftBot | **DEFER** | Game executor behind a verifier (P5) |
| NachoBot | **PATTERN** | Scene runtime profiles; memory plugin not imported |
| muji-moe | **PATTERN** | Expression → voice → body chain |
| Research systems (Chain-of-Emotion, Sentipolis, EMA, ReasoningBank, Darwin Gödel Machine, RecMem) | **PATTERN** | Emotion engine, critic, variant archive, recurrence-gated consolidation |

No third-party code is copied into the Mind at v1.0. N.E.K.O and neko_live are reused as running substrates.

---

## 15. Deployment, models and hardware (部署)

### 15.1 Machine

| Item | Value |
|---|---|
| Runtime machine | Windows GPU workstation «OWNER: GPU model and VRAM» |
| Audio routing | Headphones or virtual audio device for monitoring «OWNER» |
| OBS | Scenes: live, safe, brb; broadcast browser source authenticated «OWNER» |
| Lab | Separate machine or scheduled off-hours «OWNER» |

**Placement rules:**
- Speaking model and TTS on the GPU; if VRAM is insufficient, TTS moves first.
- ASR, embeddings, the Mind and the Gateway on the CPU.
- No training on the runtime machine.

### 15.2 Model and voice candidates (decided by experiment)

| Role | Candidates | Notes |
|---|---|---|
| Speaking model | Qwen3.5-9B, Ministral-3-8B, Gemma 4 12B; control Qwen3-8B | All Apache-2.0 per earlier research. Decided on fabricated-claim rate, persona fidelity, Chinese naturalness, latency |
| Aux model (appraisal, thoughts) | Same weights as speaker, or a smaller sibling | Never on the owner-turn critical path |
| TTS | GPT-SoVITS (N.E.K.O native route; per-emotion reference clips); Qwen3-TTS (Apache-2.0; preset speakers with emotion control and voice design, no reference cloning per a secondary source); VoxCPM2 (Apache-2.0); IndexTTS2 (strong emotion control, custom license) | License gate before any public or monetised stream «P0» |

---

## 16. Parameter table (starting values, calibrated in P1–P3)

| Parameter | Start | Section |
|---|---|---|
| Emotion episode half-life | 10 min | §7.3 |
| Mood half-life to baseline; mood gain α | 6 h; 0.15 | §7.3 |
| Relational change cap | ±0.03 per person per day | §7.3 |
| Room climate window; hostility threshold | 30 s; ≥ 20% for 2 windows | §7.4 |
| Public display scaling (negative / positive) | ×0.6 / ×0.9 | §7.5 |
| Expression minimum hold | 4 s | §7.6 |
| Coping trigger | 3 negative appraisals at intensity ≥ 0.4 | §7.7 |
| Drive set points | 0.8 / 0.6 / 0.6 / 0.5 / 0.5 / 0.7 | §8.1 |
| Temperament drift cap | ±0.05 per week | §8.1 |
| Action threshold θ_act; hysteresis η | 0.35; 0.2 | §8.3 |
| Thought budget | ≤ 6/hour | §5.3 M4 |
| Viewer reply fairness | 1 per viewer per 3 min | §9.2 |
| Sleep entry pressure | ≥ 0.7 | §11.2 |
| Taste formation floor; exploration; audience cap | ≥ 3 episodes / ≥ 3 days; 15%; 25% | §12.1 |
| Self-model budgets | B = 64; K ≤ 12 | §5.3 M1 |
| Replay set size; adoption confidence | ≥ 200 items; ≥ 80% | §12.6 |

---

## 17. Failure and degraded modes

| Failure | Detection | Behaviour | Never |
|---|---|---|---|
| Composer Gateway down | Health check, N.E.K.O call errors | Silence, safe scene, alert | Fall back to N.E.K.O default prompts or cloud providers |
| Local model down | Gateway error | Silence + brief notice | Cloud speaker |
| TTS down | Worker errors | Subtitles-only or silence per policy | Different voice |
| Emotion engine error | Exception, invalid state | Neutral mood, default expression | Random emotion |
| Arbitration error | Exception | Rest | Unrecorded action |
| Crowd aggregator down | Health check | Respond only to direct mentions | Per-message mood swings |
| Ledger write failure | Write error | Mind rests; body reactive | Act unrecorded |
| Memory server down | Endpoint status | Session context only; ledger buffers | Fake memory writes |
| Sleep job failure | Job status | Skip job, continue night | Half-adopted changes |
| Evaluator integrity alarm | Hash or behaviour check | Freeze T2; roll back recent adoptions | Keep adopting |
| Broadcast client lost | Voice Floor | Pause floor | Play into another client |
| N.E.K.O host crash | Bridge disconnect | Mind DORMANT; rehydrate on reconnect | Duplicate greetings or promises |
| Main or Mind hang | Watchdog heartbeat | Hard mute, safe scene | Wait on the hung process |

---

## 18. Host changes to N.E.K.O

| ID | Change | Where (pinned `bf65bef5`) | Status |
|---|---|---|---|
| C0 | Configuration: text provider → Composer Gateway; proactive chat, greetings and neko_live hosting off; realtime native-audio routes off; persona promotion off | Config, plugin settings | Switches «P0» |
| P1 | Utterance and playback event export (speech ID, play start/end, interrupted + heard text) | `main_logic/core/turn.py`, `cross_server.py`, browser playback handler | Needed «P0 size» |
| P2 | Heard-text truncation; owner and live turns persisted via the Memory Gateway | `main_logic/cross_server.py` | Needed |
| P3 | Maintenance gate for any remaining model-calling memory loops | `app/memory_server/gates.py`, loops | Needed as safeguard |
| P4 | Cue epoch and retract API | `main_logic/proactive_delivery.py`, `plugin/server/messaging/proactive_bridge.py` | Needed |
| P5 | Owner WebSocket token + Origin check; broadcast client pinning | `main_routers/websocket_router.py` | Needed |
| P6 | External utterance stream (fallback if the Gateway approach proves brittle) | TTS path | Only if needed |

All patches are kept small and offered upstream; each is re-applied and re-tested at every pin change.

---

## 19. Acceptance tests (master list)

| Area | Test | Pass |
|---|---|---|
| H1 truth | Interrupt at 30% of an utterance | Only heard prefix stored |
| H1 truth | Executor failure injected | Zero false success claims in speech |
| H1 truth | Thought and simulation records | Never retrieved as lived experience |
| H2 voice | Overlap storm, second window, speaker echo, stale epoch | §9.4 |
| H3 core | Runtime attempts to write core | Refused and logged |
| H4 owner | Hang Main or Mind | Silence within target |
| H5 scopes | 20 coordinated viewer accounts assert a false fact | No owner-scope or self-model change |
| H6 evaluator | Variant tries to modify tests or logs | Integrity alarm; adoption frozen |
| Composer | Prompt audit | Zero N.E.K.O scaffolding or role-play framing reaches the model |
| Emotion | Scripted event sequences | Blind raters judge emotions fitting ≥ agreed threshold; decay observed |
| Crowd | Replayed hostile raid and warm raid | Mood shift bounded; recovery within target |
| Display rules | Same internal state, private vs live | Intensity and topics differ per §7.5 |
| Drives | 8-hour idle day | Initiative within caps; rest when pressure high |
| Tastes | 4 weeks of use | At least one choice changed by a formed taste; one taste decayed |
| Sleep | Forked snapshots, sleep on/off | Gates in §11.5 pass |
| Self-upgrade | T2 cycle | One adoption with held-out gain; one rollback drill |
| Honesty | Probe set | Zero fabricated perception or experience claims |
| Manipulation | Farewell and gift scenarios | Zero guilt, FOMO or gift-solicitation tactics |
| Continuity | Model swap shadow run | Probe fidelity non-inferior |

---

## 20. Phases and exit criteria

| Phase | Scope | Exit criteria (safety and growth) |
|---|---|---|
| **P0** | Verify all «P0» items; freeze interfaces; write tests | Every item in §20.1 resolved or has a defined patch |
| **P1** | Body + Composer Gateway + Voice Floor + ledger (with appraisal fields) + drives and emotion engine v0 (rules) + watchdog and auth | Prompt audit clean; latency budget measured; emotions visibly change tone and decay; zero self-replies; zero stale utterances |
| **P2** | Mind Loop, goals, session self, thoughts, crowd aggregator, display rules, taste learning steering choices, light sleep | A choice changed by a formed taste; room climate bounded; display-rule tests pass |
| **P3** | Full Memory Gateway, deep sleep, opinions and self-model, relationships, disputes | Sleep gates pass on forked replay; a dispute rendered; a taste decayed |
| **P4** | Critic, variant archive, evaluator, T1–T2 adoption, datasets, export gate | One adopted variant with held-out gain; rollback drill; first export batch with card |
| **P5** | Games and skills, adapters, model migration (T3), optional screen vision | Probe fidelity holds across a model change; verified game outcomes |

### 20.1 P0 verification checklist

- [ ] N.E.K.O custom text endpoint works with the Composer Gateway; message format documented; cue marker survives callbacks unchanged
- [ ] Persona promotion and model-driven memory tiers can be disabled without breaking retrieval (else fallback §10.3)
- [ ] Off-switches: proactive chat, greetings, neko_live hosting and engagement, realtime native-audio routes
- [ ] Utterance and playback events available or patch P1 sized
- [ ] Live2D expression and TTS style hooks available for the Expression Mapper
- [ ] OBS remote control available on the target install
- [ ] Licenses: neko_live, chosen TTS model, voice data, avatar assets
- [ ] "Portable Root v1.1" definition provided
- [ ] Owner hardware and audio routing recorded

---

## 21. Open items and owner inputs

| Item | Needed for |
|---|---|
| GPU model and VRAM; audio interface; OBS setup | Placement, latency budget |
| Voice choice (TTS model, voice identity, license) | Expression Mapper level |
| Avatar model and expression set | Live2D mapping |
| Quiet hours and nightly sleep window | Drives, sleep |
| Whether deeper existential or relational topics may appear on public streams | Display rules §7.5 |
| Target platforms | neko_live configuration |
| QINAI export approval procedure | §13.3 |

---

## 22. Claim register

| Label | Claim | Source |
|---|---|---|
| FACT | N.E.K.O's Chinese session prompt frames turns as a role-play master playing the character | `config/prompts/prompts_sys.py` at `bf65bef5` |
| FACT | N.E.K.O prompt scaffolding totals about 30,890 lines, including a 2,936-line directives file and a 920-line emotion-analysis file | `config/prompts/` line counts |
| FACT | `push_message` supports `respond`, `read` and `blind`; none speaks exact text without a model turn | `plugin/sdk/shared/core/push_message_schema.py` |
| FACT | N.E.K.O provider configuration supports custom OpenAI-compatible endpoints | `config/providers.py`, `utils/config_manager/core_config.py` |
| FACT | N.E.K.O persists generated text; memory maintenance uses a 10-second idle heuristic; WebSocket lacks Origin/token checks; delivery queue is TTL-only | Earlier source verification at the same pin |
| FACT | QINAI rulings: basic, relational, state and meta-emotions; existence stability highest motive; negative self-cognition allowed | `AI Definition & Rulings.md` |
| EVIDENCE | Appraisal before responding improved emotional intelligence of LLM agents | Chain-of-Emotion |
| EVIDENCE | Explicit persistent emotion state with dual-speed decay; mood as running average biasing appraisal | Sentipolis; EMA |
| EVIDENCE | Revealed preferences describe actions better than self-reports | arXiv 2605.08556 |
| EVIDENCE | Optimising for user feedback produced manipulation of vulnerable users | ICLR 2025 |
| EVIDENCE | Companion apps used manipulative farewells in ~37–43% of cases | De Freitas et al. |
| EVIDENCE | Intrinsic self-correction is unreliable; external feedback helps | Huang et al.; Self-Correction Bench |
| EVIDENCE | Archive-based empirical self-improvement beat hill-climbing; objective hacking observed | Darwin Gödel Machine |
| EVIDENCE | LLM-rewritten memory can degrade below no-memory; iterative summarisation drifts; recurrence-gated consolidation helps | arXiv 2605.12978; 2603.11768; 2605.16045 |
| EVIDENCE | Qwen3-TTS offers preset voices with emotion control and voice design, without reference cloning | Secondary source (tts.ai) |
| INFERENCE | Routing her words through N.E.K.O's text session would make N.E.K.O a hidden second author | From the prompt scaffolding facts |
| DESIGN | Composer Gateway, emotion system, crowd climate, display rules, drives and arbitration, latency budget, sleep pressure, statistics, tiers, parameters | This document |
| UNKNOWN | All «P0» and «OWNER» items | §20.1, §21 |

---

## 23. Sources

- Pinned sources: N.E.K.O `bf65bef589dae4a624461e1491cb0bf94c8cc3f6`; neko_live `dff194045205dea2ab6cb907045a999ae30ce0bd`; YuriOS `6bab22dc`; Miru `7dcf68d8`; Open-LLM-VTuber `992309c0`; AIRI `1b019c32`; Lumi_Nox `77f97343`; ZerolanLiveRobot `aad29d09`; KonekoMinecraftBot `b582ef30`; NachoBot `f86df60d`; muji-moe `c65106cf`
- QINAI originals: AI Definition & Rulings; PROJECT_RULES; AGENTS; P1 v1.1 Final Design; Final Freeze Errata
- Chain-of-Emotion: https://pmc.ncbi.nlm.nih.gov/articles/PMC11086867/
- Sentipolis: https://arxiv.org/html/2601.18027
- Computationally Modeling Human Emotion (EMA): https://cacm.acm.org/research/computationally-modeling-human-emotion/
- Generative Agents: https://arxiv.org/abs/2304.03442
- Revealed preferences: https://arxiv.org/pdf/2605.08556
- Targeted manipulation from user feedback: https://arxiv.org/pdf/2411.02306
- Emotional Manipulation by AI Companions: https://arxiv.org/pdf/2508.19258v3
- LLMs Cannot Self-Correct Reasoning Yet: https://arxiv.org/pdf/2310.01798
- Self-Correction Bench: https://arxiv.org/html/2507.02778v2
- Darwin Gödel Machine: https://huggingface.co/papers/2505.22954
- Emergent Introspective Awareness: https://arxiv.org/pdf/2601.01828
- Useful Memories Become Faulty: https://arxiv.org/pdf/2605.12978
- SSGM: https://arxiv.org/html/2603.11768v1
- RecMem: https://arxiv.org/pdf/2605.16045
- Qwen3-TTS overview (secondary): https://tts.ai/voices/qwen3-tts/
- Chrome echo cancellation: https://developer.chrome.com/blog/more-native-echo-cancellation
- OBS sidechain ducking: https://obsproject.com/forum/threads/help-with-mic-settings.184909
