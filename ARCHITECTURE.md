# XIYIN Runtime Architecture

## Output boundary and persona projection (2026-09-22)

PR #6 baseline `c6bb054` failed the Windows real-model acceptance. Nothing below has been run against a real model; synthetic CI is not a behavioural verdict. Real-model acceptance of this head is still required before merge.

**Diagnosis.** The failure was partly a persona-leakage problem, through three distinct channels, and partly runtime and grounding defects:

- Body → text: the avatar/voice `presentation_seed` stood alone in the text prompt right after the name ("女性化、日系二次元表达。"). A chat model reads that as "write like an anime character", which invites "（歪头）".
- Instructions → speech: v1 projects a second-person rulebook. "不朗读…括号动作旁白" sat next to "正常括号说明、表情…照常使用", naming the behaviour while allowing its neighbour. Tendency counterexamples and field-override notes were recited when she was asked who she is.
- Runtime → invented experience: before any action existed, the disposition line asserted "动作结果有成有败", and the prompt carried no clock. The wrong weekday was a grounding gap, not model recall.

The reference projects treat body expression as a typed channel outside the spoken text:
- muji-moe strips every `[…]` tag before TTS and maps the last one to a voice emotion;
- Open-LLM-VTuber maps `[expression]` keywords to Live2D;
- AIRI parses `<|ACT …|>` markers into a closed emotion enum;
- N.E.K.O classifies the output into a closed emotion set;
- Neuro SDK uses schema actions.

Neuro-sama, Shizuku and 木几萌 are experience benchmarks only: their internals are not public and are not claimed here.

**Persona definition (v3, the default).** `foundation.persona_projection = "v3"` adds what v2 never said: how she talks. v2 described her relationships and limits but not her voice, so a 4B instruction model filled the gap with the assistant register, or the character-card register the standing "日系二次元" line invited. v3 opens with her name alone, not "一个人工智能" (the assistant template) and not a replacement label. The 2026-09-23 re-audit removed "一个人工的存在" for occupying the same slot. It adds, all as seed data:
- a voice line without forced markers;
- stances on agreement, pushback and praise;
- her artificial self-facts, which are sayable, including that she has no body or childhood and that her name, relationships and records outlast a model change.

Appearance and the feelings/consciousness stance are stated only when a turn asks. Relationship agreements are sayable in private and withheld from public prompts by default (`public_scope_disclosure`). "Not on record" is treated as unknown, not as "did not happen". The Bible's two example lines stay in the seed but are not projected by default. Runtime facts are restated as her situation, without "旧助手" or "它不是主观体验". What she is not stays out of the prompt: `anti_patterns` in the seed map to `persona_style` metrics, which count service and moe markers per turn (in the `response_plan` receipt and the harness) and never change text. See `docs/XIYIN_Persona_Definition_v1.md`.

**Persona projection v2.** `foundation.persona_projection = "v2"` projects the same seed for speech. It keeps identity, relationships, tendencies, motivations, the expression register of the current scope, and language. Presentation is stated as appearance and voice. Prohibitions are replaced by the positive frame voice agents use ("你的回复就是你说出口的话"). Per-turn scope stays in the runtime directive, and when TurnPolicy grants stage performance the directive says so. Relationship facts carry public provenance in every scope; v2 is kept unchanged as the B arm, so this differs from v3. `v1` is byte-identical to the tested projection, kept for A/B and rollback.

**Runtime audit (2026-09-23).** See `docs/XIYIN_Runtime_Truth_Leakage_Length_Audit_2026-09-23.md`. Persona text is unchanged in every arm; four runtime defects shared by all arms were repaired:
- **Provenance:** runtime facts are split at construction into sayable situation facts (`PUBLIC_RUNTIME_FACT`) and private rules. Before, "我现在只能打字交流和翻看记录…" was blocked as a prompt echo in every arm.
- **Host paths:** absolute host paths in adapter exceptions are redacted before the prompt.
- **Grounding:** records no longer turn an empty or out-of-scope inventory into "did not happen".
- **Length:** the planner resolves the effective request (mentions, negation, corrections, ordered sections) and never claims the owner asked for detail on an inferred task.

The harness now records full messages, raw chunks, released segments, plan receipts and model/build identity. It adds paired persona probes (P7, P8), a length-intent case (F10), absolute gates and a blinded review export. Capture success is not acceptance.

**v4 arm and sampling arm (after the Windows A/B/C run, 2026-09-23).** See `docs/XIYIN_Windows_ABC_Diagnosis_and_Strategy_2026-09-23.md`. Every arm handed the turn back (a question or offer in the last two sentences) in 84–89% of casual replies, and spoke the seed's trait sentences as topics. `foundation.persona_projection = "v4"` (an arm; v3 stays the default):
- **Speaking projection:** v3 without the seed's tendency defaults and motivation sentence; learned tendency revisions are still said.
- **Decision projection:** `response_plan.turn_move` names the turn (`share`, `pushback`, `frame`, `plain`) from the owner's words and adds one private line, placed last in the system prompt and recorded as `move` in the plan receipt. Replies are never inspected or edited for it.
- **Sampling:** `[inference.sampling]` (or the harness `--sampling-file`) sends validated sampling fields as an owner-chosen, recorded arm. When absent, nothing is sent, as before.
- **Metrics:** `persona_style.v3` adds `hands_back`, `trait_echo` and `past_claim_unprompted`; `--compare` recomputes them from released text (`service_profile`).

**Release boundary.**
- Provenance labels come from the persona constructor and the runtime, never from records or model text.
- A released unit may not carry 12 consecutive normalized characters of the private-instruction corpus (8 when the user asks for the prompt). Runs that span a release boundary still stop the remainder. Public values are exempt. An unresolved hold at the end of the reply is released, not rejected.
- TurnPolicy is computed once. Only its global modes (stage, scene headings, extra speakers) are permissions. A mention clause ("角色扮演是什么意思？"), a question about her own day, or a bare translation request grants none of them.
- Quoted and code spans are exempted from local evidence in the output itself. Source-code strings are data for the character checks in every turn; protocol and envelope checks keep code strings visible unless code was asked for.
- Inline emphasis and code openers that never close end with their line or after 80 characters. Brackets and quotes are deliberately not abandoned, so a padded aside stays one aside for detection.

**History and evidence.**
- History pairs the released text of a truncated or interrupted turn, so "继续" keeps its antecedent.
- Blocked and failed turns stay out entirely, and rejected raw text remains isolated from history, search, dataset and sleep.
- Premise checks read `ExperienceStore.utterances()`: a user's words from a failed turn were still said.
- `request_id` is indexed.
- A remember command is request-linked, not a chat turn.

**Known limits, to measure rather than patch lexically:**
- The stage-direction inventory misses forms such as "（笑）", "（思考）" and "（害羞）".
- JSON examples containing `"role": "system"` are always blocked.
- An unquoted bracket gloss ("（歪头）是动作标记") is treated as a performance.
- A bold glossary of gesture words ("- **摇头**：…") is blocked.
- Unclosed quotes and brackets hold the rest of the reply.
- A barge-in before any text was released drops the question from history.
- Remember commands written before this change carry no request id. They cannot be told apart from legacy chat statements, so they stay in history until they fall outside its 8-message window.

**Next acceptance.** `tools/acceptance_dialogue.py` records, per turn, the raw generation, TurnPolicy, the history actually sent, the system-prompt hash, the longest private run in released text, and a weekday check. It also records `persona_style` marker counts per turn and the server's effective sampling (`GET /props`, read-only). Run `--persona-projection v1`, `v2` and `v3` on the same Qwen3.5-4B, backend, quantization and sampling, under the contract in `docs/XIYIN_Persona_Definition_v1.md` §9, which fixes the `persona_sha256` of each arm. The P1–P6 persona probes, including the public-scope P6 with `checks.scope_leaks`, are part of the run. Then repeat the best arm with Qwen3.5-9B. Label model-layer behaviour from raw text, not from guard decisions.

实现依据是主理人提供的 `XIYIN_Architecture_v1.1_Design.md`（SHA-256 `883b5514df39dd44aa8972e88a309a652e19debb793a08e0955a4710b37faa8b`）、v1.0.1 两张语音图和 Character Bible v0.2。功能仍沿用原 M1–M10；Runtime / Body / Lab / Supervisor 是职责分组，不是四个大模型。本文件记录代码中的对应关系，不将设计要求标成已实测能力。

原稿现已入档到 `docs/`：`XIYIN_Architecture_v1.0.md`、`XIYIN_Architecture_v1.1_Design.md`（两者各有一节 2026-09-20 修订记录，逐条列出被更晚记录取代的决定及依据）、`docs/research/XIYIN_REFERENCE_REPOSITORIES_FULL.md`（按该索引 §17，参考索引只留在文档区，不进运行路径）。v1.1 入档副本的哈希与上面引用的一致，确认代码依据的就是这一份。

主理人当前排序是 FIRST ALIVE：`Owner Input → Persona/Composer → Local LLM → TTS → Live2D → 实际播放 → STOP → 可复现重启`。据参考索引 §0 止损规则与 §16 规则 10，本轮**没有新增任何第三方运行依赖**。

## Windows 验收报告的六项失败

报告是经 `XIYINRuntime.open()` 与正式服务入口的真实执行（37 次模型请求，Qwen3.5-4B Q4_K_M + llama.cpp build 11062）。六项全部追到代码根因并修复；回归见 `tests/test_reported_failures.py`，逐条根因见 `docs/XIYIN_Architecture_v1.1_Design.md` §0.2。

| # | 失败 | 根因 | 修复 |
|---|---|---|---|
| 1 | 表情符号加在括号动作前绕过出站检查 | 动作词表 `^` 锚定在固定副词白名单上；扁平正则只看最内层括号 | 剥离装饰 + 扫描所有括号组（含嵌套）与 `*强调*` + 强/弱两级词表；弱级另需短旁白且非解释性 |
| 2 | 虚构与祈奈的共同经历、后台活动、偏好 | 上下文从不说明记录里实际有什么；「没有记录」在提示里不可见 | `grounding.topic_records` 按本轮主题投影真实清单，把「0 条」作为事实说出来 |
| 3 | 否认已验证完成的文件操作 | `retrieved_record` 对 JSON 形态 `tool_result` 一律丢弃，动作回执在结构上进不了提示 | `experience.action_receipts` + `grounding.action_receipt_record`，排在上下文前部 |
| 4 | 顺着错误的纠正前提确认 | 没有任何机制回答「这句话到底说过没有」 | `grounding.premise_records` 核对历史与有效记忆，明确投影「查到原话」或「没有找到，不要顺着确认」 |
| 5 | 长短适应差；详细回答超时或撞 512 上限 | 每次请求共用固定 `max_tokens` 与固定超时，请求里的长短意图从未提取 | `response_plan` 分档 → 每轮 `GenerationBudget`，受上下文窗口与实测吞吐约束 |
| 6 | 桌面焦点/拒绝含糊 | 派发前拒绝与「已派发未达成」同为 `failure`；驱动层同类拒绝却变成 `unknown` | `InputRejected` + 回执 `evidence.dispatched`，三态在对话里可区分 |

报告同时披露的替代环境引导、临时目录权限垫片与测试台缺陷属于测试环境问题，未计入上述修复，也未据此更改产品代码。截图采集、真实语音与游戏仍未测试。

## Architecture mapping

| 原方案 | 正式代码 | 当前可验证行为 |
|---|---|---|
| M1 身份/自我、M3 状态/动机 | `self_state.py`, `persona.py`, `director.py` | 持久身份、按会话/公开范围的功能状态、人物种子与成长覆盖；明确反馈支持的表达/倾向可自主采用及回退 |
| M2 感知、M4 意图/调度 | `contracts.py`, `agenda.py`, `director.py`, `service.py` | 来源适配、唯一任务队列、优先级、抢占、重启；规则技能规划与可替换 planner；未知外部动作不重放 |
| M5 表达/行动 | `runtime.py`, `output_guard.py`, `context.py`, `voice.py`, `body/` | 同一作者的文字流、短段出站检查、语义记忆投影、ASR→Runtime→TTS/播放控制链、观察→动作→验证 |
| M6 经历、M7 记忆 | `experience.py`, `dataset.py` | 原文账本、状态与回执、版本纠错、公开/私密隔离；本地导出未审阅数据候选 |
| M8 睡眠/成长 | `sleep.py`, `architecture.py` | 空闲入睡、真实会话摘录/任务检查点、前台唤醒、持久阶段；不编造停机经历 |
| M9 Lab | `learning.py`, `director.py` | 数据策略候选→独立功能检查→采用→真实执行变化→回退；人物字段成长有真实反馈来源 |
| M10 健康/停止/发布 | `supervisor.py`, `lifecycle.py`, `xiyin_management.py` | 独立停止标记、操作期间监视、身体释放、单实例锁、SQLite 一致备份/恢复；代码/模型产物清单登记与选择 |

一个 `XIYINRuntime` 拥有一份 `ExperienceStore`。`FoundationRuntime` 只是兼容别名。Body 不写第二份人格/记忆，Lab 和 Director 不直接发送按键或播放音频。`serve` 使用一个持续 asyncio loop，旧同步桥复用自己的单个 loop。

## Grounding, disposition and generation budgets

对话上下文按「错答会变成假否认或假经历」的程度排序，预算不足时从尾部丢弃：本轮说法核对 → 动作回执 → 记忆操作回执 → 主题清单 → 词法召回。

- **动作回执**（`grounding.action_receipt_record`）区分「已执行并通过独立校验 / 已执行，但校验未达成 / 没有执行（在派发前被拒绝）/ 已派发，结果未能确认」。旧版回执没有 `dispatched` 字段：已验证成功必然派发过，其余留空，不补造。
- **说法核对**（`premise_records`）只在出现「你刚才说过…」类断言时触发；「你说呢」不触发。结果是「查到原话」或「没有找到相符的内容」，后者明确说明是**没有记录**，不是断定对方记错。
- **主题清单**（`topic_records`）只投影本轮问到的主题，把缺席作为事实陈述，避免固定免责声明占用预算。
- **功能状态**（`SelfState.disposition`）把注意力、语气、动作把握投影进请求，并明确标注是运行中的计算状态、不是主观体验、不会自动变成长期性格。它是只读投影：没有状态文档时给出起始值，不为了读而写一条观察。
- **动作选择**：近期动作验证失败会使下一次动作强制重新观察，而不是复用调用方给的观察 ID。只加验证，不放松。
- **生成预算**（`response_plan`）按请求分档得到 `max_tokens` 与超时，受服务端上下文窗口与**实测吞吐**约束；实测吞吐只从已完成的生成学习。每轮记一条 `response_plan` 事件，含计划、实际字数、首 token 时间与生成耗时，所以长短适应和延迟可以从账本测量而不是凭一次转录判断。范围说明只作用于本轮，不写进记忆。

## Actual boundaries

- 人格不是 P1 固定台词。稳定身份来自人物稿；可变倾向和表达从有效成长记忆覆盖。会话整理时，**账本里已有的明确反馈**会自动成为成长候选并采用（`Director.review_feedback_growth`），不再逐项询问；`rollback_growth` 是回头路。证据规则未放松：来源必须是同会话同范围、已完成、`user_report` 系的反馈事件，且 payload 明确指定 `kind/subject/statement`。语气、模型输出和时间流逝都推不出成长。自由人格反思和训练后的自然度尚未证明。情绪数值是调度/表达用的计算状态，不是主观体验证据。
- 文字不按固定字数截短，也不全局删除括号。上下文隐藏账本 ID、错误码等内部结构；保留原始说话者、成功/失败语义和正常符号。生成到 token 上限仍报告截断，不伪造完成。预算是资源上限，不是回复长度目标。
- 一条 goal 绑定注册时的 adapter、版本、范围与动作集，执行时重新核对。默认规则 planner 实例化已知文件技能，不能冒充已接入自主大模型规划。多身体跨域编排需要显式适配合同。
- 语音候选打断只压低音量；确认后撤销旧 epoch、取消同一 Runtime 生成与 TTS、停止客户端播放并清队列。最终 ASR 文本必须通过输入接纳标记，播放中无回声控制的转写不能绕过确认。生成、合成、client played、output observed 分开记录。
- Windows 身体仅操作明确注册的 HWND，复查前台/尺寸/DPI，按键有短租约和失焦释放；截图为可选 Pillow 后端。发送输入不等于任务成功，缺少可观察后置条件就返回 unknown。它是应用范围约束，不是 OS 沙箱。
- 游戏使用 typed semantic action 与状态版本。Neuro SDK 普通 `action/result success` 可能只是接收/参数验证，不能算游戏动作完成；适配器需要完成事件、匹配 action ID 和新状态的验证结果。
- 学习策略评估独立于候选值，当前测量 `functional_policy_check`；不是泛化、长期保持或智能增长分数。代码/模型发布记录明确 `manifest_selection_only`，尚未实现自动下载权重、执行候选代码或切换运行进程。没有用清单变化冒充已自我升级。
- 语音具体 ASR/TTS/播放客户端、Avatar、直播平台和游戏 transport 仍需要对应后端和现场配置。缺失后端返回 unavailable。没有在这次无模型验收中测自然度、GPU、AEC、声学延迟或真实游戏技能。

## Shared output gate

实际通路为 `Composer stream → 短段缓冲 → OutputGuard → text_delta → CLI / bridge / service / Voice → TTS`。传输 token 边界不是放行边界；等待句末或流结束，括号与代码块内部继续缓冲，避免半个标签或动作旁白已经朗读。普通换行不单独触发放行。无标点长句可能等待更久；20,000 字符上限是资源保护，不是回复长度目标。取消直接丢弃待查缓冲，不做最后一次输出。

| 检查 | 默认处理与例外 |
|---|---|
| `<think>`、ChatML、内部角色 JSON、`system_check` 等正文协议泄露 | 输出前拒绝；覆盖分 token、全角、零宽与常见 HTML 实体的合成案例 |
| 人设元叙述、较长的提示规则原文回显 | 普通交流拒绝；用户明确讨论人格设计时可以解释，不隐藏人工身份、不封禁不同意见或情绪 |
| 内部 ID、回执状态码 | 普通交流拒绝；明确技术分析只对用户给定的字面值作局部例外 |
| `（歪头）`、`*捂脸*` 等无请求动作旁白 | 按旁白判定拒绝；明确要求故事/动作创作时保留。普通数学、括号补充、翻译、颜文字和表情原样保留 |
| 代码/标签字面演示 | 明确代码请求中的代码块，或技术分析中用户给定的行内代码，可保留字面符号；不因此放开代码块外的内部标签 |

命中后停止该轮，不重写成预制人物台词、不静默删段、不自动重试。已经放行的前段不能撤回；本轮仍以 `OutputBlocked` 错误结束，语音撤销 epoch 并停止、清空队列。`assistant` 仅记录实际放行文字且标为 failed；收到的未放行原文保留为同会话/同范围的 `generation_diagnostic`，最多 20,000 字符。`output_guard` 记录规则版本、原因码、字符数和终态，不含被拦截正文。诊断不进入正常历史、检索、睡眠摘录或训练候选；旧失败睡眠摘录在下次整理时从派生索引排除，原账本保留。

动作旁白判定不再靠词首锚定：先剥离表情、省略号等装饰，再用扫描器取出**所有**括号组（含嵌套）与 `*强调*`，对每段做强/弱两级判定——强动作词在较长旁白里也算表演，弱动作词只在短旁白且不含解释标记时才算。这样 `（😊歪头）`、`（歪了歪头）`、`（歪头(笑)）` 都会被拦下，而 `（也就是周二）`、`(≧▽≦)`、`（指微微一笑的样子）`、`（眼睛只是比喻）` 照常通过。

这是确定性模式检查，不是完整语义审核，也不是保护提示词秘密的安全边界。表达改写、未知动作描述及意图识别仍可能漏检或误拦；放行不证明事实正确、隐私完整、行为自然。虚假纠错与无依据经历现在有证据投影支撑（见上一节），但那是装配层证据，不是模型自然度证据；长短适应的真实收益、完整的动作/感知声明验证需要实机复测。规则测试使用旧 Windows 报告中的摘录与标明的合成流；不能据此称新模型对话已通过。

## Recovery and migration

数据库新增 documents 表；旧 events/memories 保留。代码更新不生成新人物身份，不移动真实数据。`init-data` 才创建标记；既有数据根及环境覆盖继续使用。

旧 QINAI C2–C7、L3/L4/L5、P1 规则、历史备份已归档到 `legacy/qinai/`。原活跃脚本在任何副作用前拒绝运行；历史备份保留原字节。保留的 C1 与 L2 入口只转向 XIYIN。单账户不再要求 SJ_Run 或固定盘符；显式旧 separate_accounts 配置仍按真实 token 校验。

新备份覆盖实际 `experience.sqlite3`。恢复需要关闭 Runtime、通过独立 lease 和数据根身份检查，并对具体目标在控制台确认一次；其余普通任务和人物成长不走重复人工审核。代码回退与记忆回退分开，不能删 `.xiyin_data` 或覆盖数据库来伪造恢复。
