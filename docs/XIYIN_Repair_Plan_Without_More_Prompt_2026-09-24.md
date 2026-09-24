# XIYIN repair plan under the owner's constraints (2026-09-24)

Owner constraints for this plan:
- no fixes by adding prompt text;
- do not weaken her autonomy or self-stability;
- preserve her agency;
- avoid long, repetitive system prompts.

This supersedes the prompt-based parts of
`XIYIN_Persona_Failure_Taxonomy_and_Next_Architecture_2026-09-24.md`: the V4 per-turn lines and
example exchanges placed in the prompt. The taxonomy and evidence there still stand.

Status: proposal. Items marked **owner** need a decision before implementation.

## 1. Three new facts from the code

1. **The prompt is mostly rules, and she recites them.** A casual V4 turn sends about 1,100
   characters of system text. Just over half is behaviour rules. The honesty rule appears three
   times:
   - "只把有记录的事当作自己的经历…";
   - "历史里你说过的话只说明说过，不证明做过…";
   - the record notes' "说明" fields.

   Her "system-talk" register quotes them back ("查不到记录的事，我就说'没查到'，这是规矩").
   Research agrees:
   - small models' instruction-following degrades early as instruction count rises (IFScale);
   - persona and instructions drift within about eight turns as attention to the system prompt
     decays (Li et al.);
   - the guiding rule is "the smallest set of high-signal tokens" (Anthropic, context
     engineering).
2. **A tool menu is in every casual turn.** After F3 registers the workspace, every later turn
   in every session carries "已登记接口：workspace，可执行：read_text、write_text。做完要看回执。"
   (reproduced in code). An instruction-tuned model handed a tool menu offers tools: "随时丢进
   workspace 试试", "如果你需要工作，我可以在 workspace 里帮你读取或写入文件". This service
   prior is ours. The fix is *removing* text.
3. **The V4 lines are prompt additions too, and were followed about half the time** (taxonomy
   doc, §0). Under these constraints they should be retired, not multiplied.

## 2. Design rules derived from the constraints

1. **Subtract.** The system prompt holds only who she is and what is true now: identity,
   relationships, what she runs on, current state and time, relevant records. How to behave
   moves into code (integrity) and weights (voice).
2. **Protect integrity, not style.** The runtime enforces only what would break her own
   stability:
   - a false memory or activity;
   - a claimed action that never happened;
   - a role that contradicts her identity;
   - a wrong computed fact;
   - a private leak.

   It never polices how she talks: questions, length, jokes, opinions or tone.
3. **Agency means real choices with real consequences.** She chooses. Actions are real and
   recorded. What she did between conversations is real.
4. **Voice lives in the weights.** The service habit was trained in, and only data moves it.
   Example conversations become training data, not prompt text.

## 3. Repairs, mapped to the taxonomy

| # | Repair | Taxonomy | Prompt text | Agency effect |
|---|---|---|---|---|
| R1 | **Identity card + facts only** (V5 projection). About 250 chars of identity, relationships and self-facts, plus state, time and records as data. Remove the behaviour prose, the tripled honesty rule, the record "说明" rule text and the V4 move lines. Show the tool menu only on task turns (just-in-time) | A, B, G, H, L | **About half or less** | Neutral to positive: fewer scripted habits to recite |
| R2 | **Hold, then release** replies on risky turns (prompt probes, persona questions, public relationship questions), so a guard decision never cuts a sentence in half. **Asides become body events**: a spontaneous "（笑）" or "（停顿一下）" goes to the avatar and TTS style instead of blocking the reply | G, J | none | Positive: her expression is kept and routed, not punished |
| R3 | **Integrity check with selection among her own candidates.** Generate 2–3 candidates in parallel, check each against the five integrity items only, release the one with none. Never edit text; never judge style | M, D, F, C (facts), E | none | Protects self-stability; her voice is untouched |
| R4 | **Working self-state as data.** A compact per-session record: what she is doing now, positions she has stated (for example, 9.9 > 9.11), commitments, and who said what. Supplied as facts; used by R3 | C, E, H, I | a few short facts | Positive: a stable self across turns |
| R5 | **Thinking for facts.** Hidden reasoning (`enable_thinking`) only on factual, numeric or comparison turns; reasoning is never spoken | C, Q | none | Neutral |
| R6 | **History compaction.** Older assistant turns reach the model shortened; the ledger keeps everything. Reduces self-imitation and carried fabrications | H | less | Neutral |
| R7 | **Real material and autonomy.** Opinions and preferences in memory (owner-seeded, growing through review); a shelf she reads in the background with recorded episodes; an activity log; a gate for speaking first (the YuriOS, Miru and Neuro SDK `silent` pattern) | A, D, I, P, S | records only when relevant | **Strongly positive**: she has a life to talk about |
| R8 | **Voice in the weights** (**owner**). Every blind review becomes preference data (the owner picks the better reply) and owner-edited replies become SFT data. Add a small anti-sycophancy set (a user insisting on a wrong fact → she keeps the right one; Wei et al.). 16-bit LoRA or DPO on the 4B, which should fit 12 GB. Identity facts stay in the card, never in weights. A steering-vector arm is the no-training alternative (experimental) | B, K, T, Q | none | Positive: her voice becomes hers, not a prompt costume |
| R9 | **Evaluation that sees persona.** Positive measures (takes a side, grounded detail, warmth without service, humour); score partly released turns; about 30 casual shares; 3 repeats; automatic comparability; non-interview scenarios; blind review | N, O, P, S | — | — |
| R10 | **9B and sampling as measurements**, run on V5 (the decision from earlier today stands) | Q, R | none | — |

**Not in this plan, by constraint:** new behaviour rules, the V4 per-turn lines, example exchanges
in the prompt, and a style classifier that blocks replies.

## 4. Order

1. **Code (Claude, no model needed).**
   - Re-implement Codex's five local fixes.
   - R1 as the V5 projection; v1–v4 stay byte-identical.
   - R2, R3 (behind a flag), R4, R5 (behind a flag), R6 (as an arm) and R9.
   - Unit and synthetic tests.
2. **Windows run** (Codex or the owner): V4 versus V5 on the 4B, 3 repeats each; V5 on 9B as the
   capacity measurement; blind package. Decision rules as agreed earlier.
3. **Content (owner):** opinions, preferences and a shelf with a few items; then the R7 activity
   loop in code.
4. **Weights (owner-gated):** start collecting preference data from each blind review now; train
   when there is enough and the owner allows it.

## 5. Sources

- [IFScale: How many instructions can LLMs follow at once](https://arxiv.org/abs/2507.11538)
- [Instruction (in)stability / persona drift](https://arxiv.org/abs/2402.10962)
- [Anthropic: effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Simple synthetic data reduces sycophancy](https://arxiv.org/abs/2308.03958)
- [Persona-aware contrastive learning (DPO) for role-play](https://arxiv.org/html/2503.17662v1)
- [Grounded memory against hallucination (mem0)](https://mem0.ai/blog/reducing-hallucinations-llms-with-grounded-memory)
- [YuriOS](https://github.com/yuri-os/YuriOS); [Miru](https://github.com/kiyotakali/Miru)
- [Neuro SDK spec](https://github.com/VedalAI/neuro-sdk/blob/main/API/SPECIFICATION.md)
- Previous source list: the taxonomy doc §9.
