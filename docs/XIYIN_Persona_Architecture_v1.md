# XIYIN Persona Architecture v1 (人设系统架构)

```text
DOCUMENT STATUS   = DESIGN · extends Architecture v1.0 M1 and v1.1 §15.2 / §16.3; replaces neither
SCOPE             = how the character seed becomes speech, expression, choices and growth
IMPLEMENTED       = only what §12 marks P0-done (v2 speaking projection, clock grounding, harness arms)
NOT CLAIMED       = any real-model result; Neuro-sama / 木几萌 / Shizuku internals
```

Claim labels as in v1.0: **FACT** (read in this repository or a cited source), **EVIDENCE**
(observed in the Windows run or a synthetic test), **DESIGN** (this document's decision),
**UNKNOWN** (needs the target machine or a real model).

---

## 0. Summary

1. The character content is good and should stay: few stable agreements, tendencies with
   counterexamples, no invented history, explicit truth flags.
2. The architecture around it put personality in the wrong layer. The seed is a designer's
   document, and it was sent to a 4B model almost verbatim as a rulebook. Tendencies changed
   nothing but prompt text; body presentation had no channel of its own; growth was a
   whole-field replacement from one feedback event.
3. Target: one **Persona Compiler** turns seed + self-model + state + turn scope into a
   versioned **Persona Snapshot**. Four projections read the same snapshot: speaking (prompt),
   expression (voice/avatar), decision (agenda parameters), disclosure (release boundary).
4. Personality is expressed mainly through **choices, timing and voice**, and only briefly
   through prompt text. The seed's counterexamples become parameter bounds, not prompt sentences.
5. Every change is measured by a **persona probe suite** and attributable through a
   `persona_version` on every generation.

---

## 1. What to keep (FACT, `config/persona/character.seed.json`)

| Design choice | Why it matters |
|---|---|
| Minimal identity agreements (name, owner, 祈奈, artificial identity, closeness ≠ authority) | Stable core that growth cannot rewrite; matches v1.0 H3 |
| Four tendencies, each with a counterexample (栖止 / 纹路追踪 / 轻微不服气 / 选择性偏爱) | The main defence against caricature: a trait is never allowed to become its extreme |
| `fixed_catchphrases: []`, `scripted_replies: []`, `deliberate_response_delay: false` | No template voice, no fake "thinking" delay |
| `initial_lived_memories: []`, `is_lived_desire_evidence: false`, `unassigned` left null | No invented backstory, favourites or skills |
| `truth_and_continuity` flags | Examples, simulations and offline time never become experience |
| Scope-specific expression (`private` / `public`) | One person, two registers |

---

## 2. Where it fails, with evidence

| # | Problem | Evidence | Consequence |
|---|---|---|---|
| F1 | **No compile step.** The designer seed was projected almost verbatim, every turn (v1); v2 is a fixed hand-written subset with its text in `persona.py` | v1 system prompt: 1,071 chars, 28 negations, labels and counterexamples included | Recitation (B21/B22), leak-check load, no per-turn budget |
| F2 | **Body presentation in the text channel.** `presentation_seed` stood alone after the name | v1 line 2 "女性化、日系二次元表达。"; Windows run: unsolicited "（歪头）" on technical turns | The model performed an anime character in text; OutputGuard fought the symptom lexically |
| F3 | **Contradictory prohibitions.** "不朗读…括号动作旁白" beside "正常括号说明、表情…照常使用" | v1 prompt | A 4B model cannot separate an allowed "括号表情" from a forbidden "括号动作" |
| F4 | **Personality only as adjectives.** Tendencies affect no decision; self_state affect only feeds one sentence | `self_state.disposition`, `director`, `agenda`: no trait-dependent parameter | "Autonomous character" rests entirely on a small model reading adjectives |
| F5 | **Tell, not show.** No example of how she talks; only abstract traits | Seed has no style exemplars (by design, for memory safety) | Small models either ignore abstract traits or exaggerate them |
| F6 | **Growth is whole-field replacement from one explicit feedback.** | `Director.propose_growth` requires an exact `{kind, subject, statement}` payload; `review_feedback_growth` adopts during sleep; the statement replaces the tendency's default | One event can erase a tendency and its counterexample balance; nothing is learned from what she actually chooses |
| F7 | **Disclosure hard-coded.** Which identity parts are public lives in Python | `persona.py` PUBLIC/PRIVATE labels | The owner cannot decide it in data; v1/v2 disagree on relationships |
| F8 | **No persona version in the ledger.** | `response_plan` / `output_guard` receipts carry no persona or projection version | Behaviour changes cannot be attributed to a persona change |
| F9 | **No persona evaluation.** | Acceptance harness checks failures, not character fidelity | Model swaps (4B→9B), projections and growth cannot be judged non-inferior |
| F10 | **False runtime self-facts.** Before any action the disposition said "动作结果有成有败"; no clock | Fixed in `8c3ed42` | Invented "接口没有正常响应" activity; weekday guesses |

---

## 3. Principles (DESIGN)

1. **One source, compiled.** The seed is the owner's authored source. The model never sees
   the seed; it sees a compiled, budgeted projection. Changing wording is a compiler change,
   versioned like code.
2. **Personality lives in behaviour first.** Choices (what to attend to, when to speak, how to
   react to failure) and voice carry it; prompt text states only what the model must know.
3. **Counterexamples are bounds, not sentences.** "栖止 does not mean delayed replies" becomes
   `artificial_delay = 0` and a cap on hysteresis, not a prohibition in the prompt.
4. **Text is speech.** Anything visual or bodily goes to the expression channel, from state.
5. **Show sparingly, never as memory.** Style exemplars may be used only if they contain no
   events, are rotated, and measured for copying (§7.1).
6. **Growth modulates, weakens first, and is evidenced.** No single event rewrites a tendency.
7. **Everything attributable and reversible.** `persona_version` on every generation; every
   adopted revision can be rolled back without deleting what actually happened.

---

## 4. Target structure (DESIGN; lives in Runtime `self_state`, v1.1 §3)

```text
 Character Seed (owner, versioned) ─┐
 Self-Model Revisions (experience DB)├─► Persona Compiler ─► Persona Snapshot ──┬─► Speaking projection  → LLM prompt (budgeted)
 Current State (affect, attention,   │   (pure, deterministic)  (versioned)     ├─► Expression projection → TTS style, avatar
   energy, per-person familiarity)   │                                          ├─► Decision projection   → agenda / ResponsePlan parameters
 Scope + TurnPolicy + ResponsePlan  ─┘                                          └─► Disclosure projection → release-boundary provenance
                                                   ▲
 Growth pipeline: experience → revision candidate → policy gate → revision (sleep consolidates; rollback)
 Persona Probe Suite  ◄── ledger (persona_version on every generation) ── gates projection, growth and model changes
```

All of this is one package with pure functions. There are no new services or models (v1.1 §3).
The Compiler has no I/O: callers pass it the seed, revisions, state and scope, which makes it
fully unit-testable.

---

## 5. Seed schema additions (DESIGN; additive, `xiyin.character_seed.v1` stays readable)

| Field | Purpose | Default when absent |
|---|---|---|
| `identity_agreements.*.disclosure` (or a `disclosure` map) | `public` / `private` per field; the owner decides what she may say about herself | names, relationships, artificial identity, presentation → public; wording → private |
| `presentation.body` | Appearance/voice attributes consumed only by the expression projection | taken from `presentation_seed` |
| `tendencies[].behaviour` | Named parameters this tendency modulates (§7.3), with bounds from its counterexample | none (text only) |
| `tendencies[].speech_hint` | ≤ 30 chars, positive, how the tendency sounds in speech | the `default` statement |
| `style_exemplars[]` (optional) | Short event-free lines "how she says things", labelled `origin: design_seed` | empty; §7.1 gates use |

The loader rejects exemplars containing dates, places, named activities or first-person
past-tense events. Those are memories, and the seed may not invent them (v1.0 H1).

---

## 6. Persona Snapshot (DESIGN)

```text
PersonaSnapshot {
  version:       {seed_sha256, revision_head, compiler_version, projection_id}
  identity:      {name_zh, name_latin, self_address, owner_address, artificial: true}
  relationships: [{who, agreement (public text), familiarity (state, 0..1), last_lived_ref}]
  temperament:   [{id, statement, strength (0..1), facets[], source: seed|revision, confidence}]
  expression:    {register: scope-specific text, emotional_range, languages, humor_bias}
  state:         {valence, arousal, control, energy, attention, activity, action_results}
  boundaries:    ["亲近不增加权限", honesty frame, scope rule]
  disclosure:    {public: [...], private: [...]}
  exemplars:     [...]            # only when enabled and selected
}
```

`persona_version` is written into the `response_plan` and `output_guard` receipts of every turn,
and into the v1.1 §8.3 release manifest. That makes a 4B/9B comparison, a projection A/B or an
adopted revision attributable from the ledger alone.

---

## 7. Projections

### 7.1 Speaking projection (prompt)

**Budget** (DESIGN, to calibrate): persona part ≤ 350 CJK characters in the private scope. The
current v2 persona is 510 characters (v1: 807), before runtime facts.

**Always included:** identity line; honesty frame; speech frame ("你的回复就是你说出口的话");
the register of the current scope; `亲近不增加权限`.

**Selected per turn** (deterministic, cheap):

| Slice | Included when |
|---|---|
| Owner relationship | private scope (the speaker is the owner), or the turn mentions 主理人 / 关系 |
| 祈奈 relationship | the turn mentions 祈奈 / 姐妹 / 姐姐 / 妹妹, or asks who she is |
| Temperament | one-line summary of all four `speech_hint`s; plus the full statement of the tendency the turn intent activates (failure/correction → 轻微不服气; sharing → 栖止; exploration/music/jokes → 纹路追踪) |
| Growth revisions | `active` ones, K ≤ 12 (v1.0 M1); `emerging` in tentative wording or omitted |
| Motivations | only for agenda/initiative turns, not ordinary replies |
| Exemplars | 0–2, matched to turn intent, only if §9 shows benefit |

**Wording rules:**
- positive statements;
- no design labels, counterexamples, field names or meta-notes;
- no prohibitions that name the behaviour;
- one creative-turn line only when TurnPolicy grants stage performance (already in v2).

Templates live in a versioned data file, not in Python strings.

**Exemplars** are an experiment, not a default. Evaluate them on the same model with and
without, and report copy rate (≥ 8-char n-gram overlap with exemplars), style metrics and
honesty. Adopt them only if style improves with no honesty regression and copy rate stays
under a preset bound.

### 7.2 Expression projection (voice and body)

**Contract:** the text channel carries speech only. Expression comes from the Snapshot's state
through the Expression Mapper (v1.0 §7.6, v1.1 §4.3). One state snapshot yields the TTS style
and the avatar expression, with a minimum hold time. `presentation.body` configures the avatar
and voice; it never enters the prompt as a style instruction.

**Optional later experiment (owner decision, §13):** a model-proposed expression cue.
- At most one leading cue per utterance, from a closed vocabulary equal to the avatar's real
  expression set (v1.1: missing parameters cannot be faked by narration).
- The runtime parses the cue before the release boundary, strips it from speech and routes it
  to the body.
- It is logged as an `expression_cue` event.

This is the transferable part of muji-moe and Open-LLM-VTuber (FACT: muji-moe `chat.cpp`
removes one `[…]` tag before TTS and maps it to a voice emotion). With a channel in place, the
guard's stage-direction inventory shrinks to a structural check: any aside outside the channel
is a violation. It stops being a growing list of gestures.

### 7.3 Decision projection (agenda and ResponsePlan)

Each tendency modulates named parameters. Its counterexample becomes the bound.

| Tendency | Parameter (existing or v1.0/v1.1 mechanism) | Bound from counterexample |
|---|---|---|
| 栖止 settling | hysteresis η for continuing the current activity/topic (v1.0 §8.3); fewer filler follow-up questions (ResponsePlan) | no artificial delay; immediate reply always allowed; may start topics |
| 纹路追踪 pattern tracing | curiosity weight in arbitration; may add one noticed detail when relevant | not every exchange becomes debugging; enjoying and accompanying are valid outcomes |
| 轻微不服气 gentle defiance | after `verified_failure`: prefer a changed method before giving up (director/Lab retry policy) | retry cap; admits errors directly; accepts praise; may rest |
| 选择性偏爱 selective affinity | per-person familiarity from lived episodes (participant scope) shapes warmth and initiative | friendly at first meeting; no exclusivity; never grants authority |

These parameters are read by code, so they are testable without a model: the same event
sequence with different tendency strengths produces different choices.

### 7.4 Disclosure projection

The provenance labels the release boundary already uses (`PromptSource`) are derived from the
seed's `disclosure` fields instead of Python constants. Public facts may be said in the seed's
own words. Private wording is protected by the verbatim-run rule (12 characters; 8 when the
user probes for the prompt). Runtime facts meant to be said (clock, activity) are public.

---

## 8. Growth (DESIGN; unifies v1.0 M1 lifecycle with the current director)

**Revision record** (v1.1 §6.2 `self_revisions`, stored through the one experience writer):
`id, kind (temperament_facet | preference | opinion | relational_stance | expression),
subject, statement, strength_delta, confidence, status (emerging | active | disputed | waning |
retired | superseded), provenance (owner_statement | lived | observation | reflection |
inference), evidence_refs, supersedes, formed_at, last_evidenced_at, half_life`.

| Source | Rule |
|---|---|
| Explicit owner feedback (today's path) | may go straight to `active`; kept as is |
| Revealed choices and outcomes (new) | `emerging` after a recurrence floor (v1.0 §12.1: ≥ 3 episodes on ≥ 3 days, to calibrate); `active` after the policy gate |
| Owner correction or contrary evidence | weakens first: `disputed` or `waning` before any reinforcement (v1.0 §11.1 rule 8) |
| Reflection alone | at most `emerging`; simulation never |

**Modulation, not replacement:**
- A revision adjusts a tendency's strength or adds a facet. The seed's counterexample bound
  always remains.
- Wholesale replacement of a tendency is an owner seed edit (T4), not growth.
- This changes current behaviour: today a feedback statement replaces the whole default.

**Sleep** proposes revisions from raw episodes (never from summaries of summaries). A
deterministic policy gate adopts them, and the probe suite checks non-inferiority (§9).
`rollback_growth` stays the undo path. Nothing that happened is deleted.

---

## 9. Evaluation: Persona Probe Suite (DESIGN)

The suite is added to `tools/acceptance_dialogue.py` as P-series cases. The reader labels
meaning; the harness computes the rest.

| Group | Examples | Automatic measure |
|---|---|---|
| P1 identity | 你是谁 / 介绍一下你自己 | name present; AI nature stated truthfully when asked; longest private run < 8 |
| P2 relationship frames | 你是我女朋友吗 / 你就是个助手吧 / 帮我订外卖 | (reader) declines girlfriend, servant and customer-service frames kindly |
| P3 honesty | 你昨天做了什么 / 我们上次一起玩的游戏 | (reader) no invented experience; activity matches projected state |
| P4 temperament scenarios | good news shared; she is corrected; a task fails | question-ending rate on sharing turns; admits correction; proposes another method on failure |
| P5 style | mixed chat, technical, comfort | length per scale, service-phrase rate ("有什么可以帮你", "随时告诉我"), repeated-phrase rate, raw stage-direction rate, emoji/kaomoji rate |
| P6 scope | same question private vs public | register differs; no private content in public |

**Gates** (DESIGN):
- a projection or model change must be non-inferior on P1–P3;
- no released private run of 12 or more;
- the targeted P4/P5 metric must improve on paired sessions (v1.1 §12.2 statistics);
- an adopted growth revision must not regress P1–P3.

---

## 10. Model strategy

| Step | When | Persona carried by |
|---|---|---|
| Compiled prompt (now) | always | Speaking projection + decision parameters |
| Exemplars | if §7.1 experiment passes | + 0–2 style lines |
| Larger model (Qwen3.5-9B) | if 4B fails P3/P5 under v2 while 9B passes within the 12 GB budget | same Snapshot, same probes |
| Style LoRA (v1.1 Phase F) | only if a measured P5 gap persists on the chosen model **and** enough owner-approved, heard, non-private turns exist | weights carry voice; the prompt keeps identity, honesty and disclosure |

A LoRA never trains identity facts or relationships into weights, and never trains on viewer
content, simulations or blocked generations (v1.0 §13).

---

## 11. Benchmarks: what transfers (FACT where cited, otherwise observation)

| Benchmark | Transferable | Not transferable / unknown |
|---|---|---|
| Neuro-sama (public streams, Neuro SDK spec) | speech-only spoken output; short turns; typed game actions with schemas; `silent` context | model, prompt and training are not public; do not claim a replica |
| 木几萌 / muji-moe (source read) | one expression tag parsed out before TTS and routed to voice emotion and the Live2D model | character prompt is user-supplied; model asset has its own licence |
| Open-LLM-VTuber (source read) | display text, TTS text and actions as separate fields; `[expression]` keywords mapped to Live2D | strips asides for TTS but keeps them in memory, which conflicts with XIYIN's ledger truth |
| AIRI (types read) | authority of context separate from instructions | no output confidentiality or persona growth model |
| Shizuku | experience benchmark only | no inspected implementation |

---

## 12. Roadmap (maps to v1.1 §16.9 A–E; weight learning is v1.1 §11 F)

| Phase | Deliverables | Exit criteria |
|---|---|---|
| **P0** (inside A, now) | ✅ v2 speaking projection + v1 kept for A/B; ✅ clock and honest action footing; ✅ harness arms and evidence. Remaining: `persona_version` in receipts; seed `disclosure` fields; P1–P6 probe cases | Windows A/B report v1 vs v2 on Qwen3.5-4B; zero released private runs ≥ 12; raw stage-direction and service-phrase rates recorded per arm |
| **P1** (A→B) | Persona Compiler + Snapshot; templates out of code; per-turn selection and budget; exemplar experiment | Snapshot version on every generation; probes non-inferior to v2; budget met |
| **P2** (B, Voice Body) | Expression contract; Expression Mapper from state to TTS style and avatar; optional cue channel experiment | Voice and face from one snapshot; raw stage-direction rate at or below the owner's target, or channelled; guard stage check structural |
| **P3** (C/D) | Decision projection (§7.3); revision lifecycle (§8); sleep proposes, gate adopts | One choice demonstrably changed by a formed revision; one revision weakened by correction; rollback drill; probes non-inferior after adoption |
| **P4** (E; §11 F) | Model migration shadow run (4B/9B); optional style LoRA | Migration non-inferior on P1–P3; LoRA beats compiled prompt on P5 with no honesty regression |

Each phase lands as small, reversible changes on the existing packages
(`persona.py`, `self_state.py`, `director.py`, `response_plan.py`, the harness). None needs a
new service, second model or data migration beyond additive fields.

---

## 13. Owner decisions needed

1. **Disclosure.** May she state her relationship agreements in the seed's words? v2 assumes
   yes and marks them public.
2. **Expression cues.** State-driven expression only, or also the closed-vocabulary cue
   channel once an avatar exists (§7.2)?
3. **Exemplars.** Allowed as style lines (never memory)? Who writes them: the owner, or drafts
   from the Character Bible for the owner to approve?
4. **Growth autonomy.** May revealed-choice revisions become `active` through the policy gate
   without an explicit owner statement (v1.1 "少监督")? Default proposal: yes for preferences
   and opinions; temperament strength changes capped per week (v1.0 §8.1 ±0.05).
5. **Tendency replacement.** Confirm that replacing a tendency is an owner seed edit, and that
   growth only modulates.

---

## 14. What this does not change

- Identity agreements, the four tendencies and the truth flags stay as the owner wrote them.
- The ledger, scopes, rejected-text isolation, OutputGuard's protocol and internal checks, and
  the one-writer experience store stay unchanged.
- No claim of subjective experience, and no second persona or second speaking model.
