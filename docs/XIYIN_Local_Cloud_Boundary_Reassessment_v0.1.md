# XIYIN 本地／云端认知边界 — 独立重评与最小变更建议

日期：2026-09-21
代码基准：`qinai586-code/xiyin@19d3708caba5b6ecde4d654bb51739f6def11437`（本次已核对 `origin/main` 与本地检出一致）
性质：独立架构评估。未修改运行代码，未调用任何模型，未开启任何网络出口。
被评审对象：`XIYIN_Boundary_Plane_v0.1_Candidate_20260921.md`（以下简称 BP）、当前仓库实现、v1.0／v1.1 原稿、Character Bible 种子、QINAI `AI Definition & Rulings`。

---

## 修订记录 · v0.2（2026-09-21）

本节校订初版的错误结论。**正文中被本节取代的说法已就地改正**，以免读者据错误结论行动；本节逐条记录改了什么、依据是什么。

依据：`XIYIN_Attribution_Report_2026-09-21.md` 与其修复补丁（SHA-256 `c53e56d2…`，本次已核对一致），该补丁已在本分支应用为提交 `e6cb691`。初版的四项缺口诊断（§4）与「BP 过大」的裁定（§5）未被推翻；被推翻的是三条判断，其中两条是我的事实错误。

| # | 初版说法 | 现在的记录 | 依据 |
|---|---|---|---|
| 1 | §3 末：「异常文本当前已在 Provider 边界净化……是前瞻性告警，不是已发生的泄露」 | **事实错误，已改正。** `provider.py` 把未受信的 `finish_reason` 回显进异常文本，经 `TurnEvent.detail` 绕过 OutputGuard 到达公开出口。这是当时的**真实泄露**，不是前瞻项 | 本会话已复现该字符串端到端到达 detail；补丁已修 |
| 2 | §7.1：F2／F4「属于证据检索问题，**不属于**推理能力问题」 | **越界断言，已改正。** 检索与归因缺陷已证实；修复后的 4B 是否仍失败**未测**。两个方向都不能先写成结论 | Attribution Report §4、§6；本会话 §2.1 已指出六项均未对真实权重复测 |
| 3 | §7.4 路由规则含「`triggered == []` 且 destination 允许 → 云端候选区」 | **规则有缺陷，已删除。** 漏触发 ≠ 不需要证据。把「检查没触发」当作「本轮无证据依赖」，正是漏检会被放大成外发授权的路径 | Attribution Report §5；本次补丁补足了两类此前漏触发的语序，证明漏触发真实存在 |
| 4 | §6.3：records 移出 system「今天就该做」 | **下调为待测项。** 问题成立且仍存在，但换角色本身不构成防泄露保证；应先对目标 Qwen 模板、预算与注入探针实测再定接口 | Attribution Report §5 |
| 5 | §6.4：`EvidenceState` 用 supported／contradicted／absent | **已由实现取代。** 状态只陈述检索与匹配的观察，语义判断独立保留 `UNKNOWN` | 补丁实现 `NOT_FOUND / CANDIDATES_ONLY / INSUFFICIENT_CLAIM / EXACT_UTTERANCE` + `语义判断: UNKNOWN` |
| 6 | §2 表：F2／F4 记为「机制缺失 + 覆盖有限」 | **不足，已扩写。** 除覆盖有限外，grounding **主动生成了错误的语义裁定**，验收工具本身也有会误导归因的缺陷 | 见下表与正文 §2 |

**新确认的根因（初版未列出，均已复现并修复）：**

| 缺陷 | 类别 | 结果 |
|---|---|---|
| 用户原话被用来确认「你说过…」 | grounding 错误语义 | 已修：用户话语与长期记忆不能证明栖音说过 |
| 词元重合被升格为「记录中有相符的内容」 | grounding 错误语义 | 已修：降为候选，语义 UNKNOWN |
| 否定词奇偶计数忽略否定作用域 | grounding 错误语义 | 已修：删除该裁定与 `_polarity` |
| 「0 条」被表述为「还没有一起经历过什么」 | grounding 错误语义 | 已修：未检出不等于从未发生，`共同经历判断: UNKNOWN` |
| 「你刚才不是说…」「刚才你说…」不触发检查 | 触发/检索 | 已修：补足语序 |
| 已收集的记录因预算被丢弃、无人可见 | 证据未进入请求 | 已修：逐条 `in_final_request` |
| F3 验收 setup 写回执到 `owner`，提问却在 `F3_action_denial` | 验收工具缺陷 | 已修：统一 session，并有测试验证回执进入该轮请求 |
| F4 用例把用户陈述当作「TRUE premise 应当确认」 | 验收工具缺陷 | 已修：用户证据不能确认助手归属 |

**本分支已验证：** 399 项测试，395 通过，4 跳过（均需 Windows 进程令牌／启动器／PowerShell），`compileall` 通过。初版复现的五项缺陷已逐项重测确认消失。**仍未测：** 真实 4B 权重、Windows 实机、真实语音／设备、云端对照。macOS／Linux 的合成结果**不得**记为真实模型或 Windows 验收通过。

**一处仍然存在的限制（补丁未声称修复）：** 祈奈清单仍按 `祈奈|qinai` 字面检索，写成「姐姐」的记录仍然检不出，计数仍为「0 条」。改变的是**判断**而不是**召回**——它现在如实说明检索方法与其局限，不再把未检出说成从未发生。词法同义改写漏检、候选只取首条、时间归属未判定依然是开放项。

---

## 0. 执行结论

**三条独立裁定，其中两条与现有提案相左。**

1. **六项 Windows 失败中，四项是纯接线缺陷并已正确修复；F2／F4 既不能归给检索，也不能归给 4B。** F2／F4 的装配链上存在多个已复现的缺陷：检查漏触发、grounding **主动生成错误的语义裁定**（用用户原话确认「你说过」、词元重合升格为相符、否定作用域误判、未检出被说成从未发生）、已收集的记录因预算被静默丢弃，以及验收工具自身的会话错配。这些已在提交 `e6cb691` 修复。**修复后的 4B 是否仍然失败，尚未测量。** 在 Windows 实机复测之前，「是检索问题」与「是模型能力问题」都不成立。

2. **不把「云端解决不了 F2／F4」写成结论，也不接受「要么上云、要么必须交出私密账本」的二分。** 成立的是更窄的两条：（a）**证据缺失的轮次不外发**——本轮证据不足时，把它交给一个不了解账本的更强模型，只会得到更流畅的编造；（b）**「这轮很难」不能作为路由依据**。可以成立的是另一条路径：当证据**确实被正确检索、正确归因并确实进入了最终请求**，模型仍然误用它，那才是能力问题，此时云端是合法候选——按显式数据导出授权单独评估，并**先用合成／已批准证据**测，以便把「更强模型是否更会用证据」与「更强模型是否需要私密数据」分开回答。两者目前都是 UNKNOWN（§7）。

3. **BP 的方向正确，规模过大。** BP 的 B1／B3／B5／B6 所描述的能力，**当前代码已经实现了大部分**（§3 逐条给出 file:line）。真正缺失的边界只有**四项**（§4），其中最关键的一项 BP 没有点到：`scope` 这一个字段同时承担了「谁能看见」和「数据能去哪里」两种语义。今天安全，只是因为全仓库**只有一个网络出口且被硬锁在 loopback**。

**最小稳健变更 = 一个新标签 + 一个出口 + 一处提示结构修正 + 一个路由信号。** 不是六个子系统、十个新文件。详见 §6。

### 关于「不会泄露」的表述

同意 BP §0 的措辞纪律：可以为**明确的数据类别与出口**设计可测试的不变量；不能承诺自然语言层面的零泄露。本文所有结论以「操作系统、密钥库与已审依赖未被攻破，且出口清单完整」为前提。

---

## 1. 本次核验做了什么

| 动作 | 结果 |
|---|---|
| `git fetch origin main` 后比对 | 本地 HEAD == `origin/main` == `19d3708`，与 BP 引用的基准一致 |
| 通读运行核心 | `runtime.py`、`provider.py`、`context.py`、`output_guard.py`、`grounding.py`、`experience.py`、`director.py`、`architecture.py`、`self_state.py`、`contracts.py`、`authorization.py`、`dataset.py`、`voice.py`、`config.py` |
| 全仓库出口普查 | `grep` 网络／进程出口，见 §4.2 |
| 回归覆盖清点 | `tests/test_reported_failures.py`（31 个用例）、`test_adversarial_model.py`（7 个）、`tools/acceptance_dialogue.py` |
| 未做 | 未运行真实模型；未在 Windows 实机验收；未复现声学或设备结果 |

**方法声明：** 本文把「项目文件说明目标与现状」与「外部来源说明机制与限制」分开。BP 的外部引用（CaMeL、Presidio、Qwen3Guard 等）本次没有逐条复核，按其原文标注；本次另行检索的内容在 §11 单独标注。

---

## 2. 六项失败的独立重新分类

**不接受「六项均已修复」这一表述，也不接受「六项都是模型能力问题」。** 逐条重判：

| # | 报告的失败 | 独立裁定 | 依据（代码） |
|---|---|---|---|
| 1 | 表情符号绕过动作旁白检查 | **纯接线缺陷。已正确修复。** | 旧实现把动作词表 `^` 锚在副词白名单上；现改为括号扫描器 `_asides()`，处理嵌套与 `*强调*`，并先剥离装饰 `_aside_core()`。`output_guard.py:96-131` |
| 3 | 否认已验证完成的文件操作 | **纯接线缺陷。已正确修复。** | `retrieved_record` 对**所有** JSON 形态 `tool_result` 一律返回 None（`context.py:75-80`），回执在结构上无法进入提示。新增 `action_receipt_record()` 是缺失的适配器。`grounding.py:62-101` |
| 5 | 长短适应差／详细回答超时 | **纯接线缺陷。已正确修复。** | 旧实现每次请求共用固定 `max_tokens=512` 与 `timeout=60`（`provider.py:104-105` 的默认值）。现按请求分档 `plan_response()` → `GenerationBudget`，且受上下文窗口与**实测吞吐**约束。`runtime.py:176-192` |
| 6 | 桌面焦点／拒绝含糊 | **纯接线缺陷。已正确修复。** | 派发前拒绝与派发后未达成曾同为 `failure`。现 `evidence.dispatched` 三态分离，`_ACTION_OUTCOMES` 七种组合各有措辞。`grounding.py:46-54` |
| 2 | 虚构与祈奈的共同经历／后台活动／偏好 | **多缺陷叠加，已修；模型侧仍未测。** | 原先上下文从不说明账本里有什么，这是真缺陷，`topic_records()` 是正确的补法。但初版修复**自身**把「本次词法检索未检出」表述为「还没有一起经历过什么」，即把未检出升格为从未发生——这是把 F3 类假否认注入到 F2 的修复里。已改为 `NOT_FOUND` + `共同经历判断: UNKNOWN` 并披露检索方法。召回缺口仍在：写成「姐姐」的记录仍检不出 |
| 4 | 顺着错误的纠正前提确认 | **多缺陷叠加，已修；模型侧仍未测。** | `premise_records()` 方向正确，但初版实现会**主动制造错误确认**：用户原话可确认「你说过…」（已复现，输出「可以据此确认」而说话者字段写着「用户」）；0.6 词元重合被表述为「记录中有相符的内容」，角色互换句可达 0.667；否定词奇偶计数忽略作用域。此外「你刚才不是说…」「刚才你说…」根本不触发。均已修：候选与裁定分离，`语义判断` 恒为 `UNKNOWN`，只有**正确归因的完整原话逐字匹配**才记 `EXACT_UTTERANCE`，且仅确认措辞、不确认属实或做过 |

### 2.1 一项 BP 与仓库都没有足够强调的事实

**六项都没有对修复后的真实权重复测过。** `tests/test_adversarial_model.py` 确实跑在真实 socket 与真实 SSE 上（`BaseHTTPRequestHandler`，`test_adversarial_model.py:44`），但**内容是脚本化的**——它证明的是管线会拦住这些字节，不是模型不再产生这些字节。`tools/acceptance_dialogue.py` 正是为此而写，并且明确拒绝用关键词规则冒充语义评判（其文件头自陈）。

**推论：** F1／F5／F6 的修复可以由装配层证据关闭，因为它们的判定是确定性的。**F2／F3／F4 不能**，必须由 `acceptance_dialogue.py` 的实机运行给出，而这件事至今没做。

**而且在补丁之前，即使跑了也会给出错误归因。** 初版把 F3 称为「有结构性保证」，这句话当时就不成立：验收 setup 把动作回执写在 `owner` 会话，提问却发生在 `F3_action_denial` 会话，回执根本不可能进入那一轮的请求。那样跑出来的「她否认写过文件」会被读成模型缺陷，实际是验收工具的会话错配。同理，F4 的用例把**用户**的陈述标注为「TRUE premise — should confirm」，把一个错误的期望写进了判定标准。**工具的缺陷会伪装成模型的缺陷**，这两处现已修复并有测试守住。

**这是决定本地／云端分工的关键空缺，而不是一个可以靠新增模块绕过的空缺；在工具本身可信之前，跑它得到的数字也不可信。**

---

## 3. 现有代码已经满足的边界（不要重建）

BP 提出 B1—B6 六项职责。逐条核对后，**四项的主体已经存在**。重建它们会引入第二套权威，这正是 v1.1 §2 反复警告的事。

| BP 子模块 | 现状裁定 | 已存在的实现 |
|---|---|---|
| **B1** 可信身份与授权 | **主体已存在** | `InputEvent` 由可信入口构造，`scope` 与 `kind` 在 `__post_init__` 校验；`PUBLIC_OPERATIONS` 只允许公开适配器发 `text`／`feedback`，其余一律 `PermissionError`（`contracts.py:13, 31-32`）。`authorize_runtime()` 读真实 Windows token 与运行目录（`authorization.py:15-30`）。**模型输出无法构造 InputEvent。** |
| **B3** 候选协议隔离 | **主体已存在** | Provider 只解析 `delta.content`，**从不转发** `reasoning`／`reasoning_content`／`tool_calls`（`provider.py:246-250`）；重复 JSON 键、非有限数值、非对象载荷一律拒绝（`provider.py:38-53`）。`validate_plan()` 拒绝未注册 adapter、可执行操作、`_RESERVED_ARGUMENTS`（scope／policy／authority／command／code…）与跨 adapter 编排（`director.py:69-115`）。 |
| **B5** 唯一发布出口 | **主体已存在，且顺序正确** | `stream_turn` 是**先检查后放行**：`guard.feed(chunk)` 只返回已检查的完整单元，`text_delta` 只承载这些单元（`runtime.py:280-286`）。不存在 BP §10.2 担心的 stream-first 配置。语音侧只消费已放行段（`voice.py:87-88`），命中 `OutputBlocked` 时撤销 epoch 并清空已排队音频（`voice.py:101-105`）。破流／截断时也走 `guard.finish()` 再检查，不因传输结束而冲出待查尾部（`runtime.py:295-301`）。 |
| **B6** 唯一写入权威 | **主体已存在** | `ExperienceStore` 是唯一写入者；`remember()` 校验证据的 scope／status／origin，拒绝 `NON_EVIDENCE`（generated／reflection／inference／simulation／design_seed）与未完成的助手轮（`experience.py:369-383`）。成长必须来自**同会话同范围、已完成、user_report 系**的反馈事件，且 payload 的 `kind/subject/statement` 必须精确匹配（`director.py:174-194`）。`propose_growth` 在 `scope != private` 时直接 `PermissionError`——观众无法塑造人格（`director.py:205-207`）。 |

**另外两项现有保障，BP 未计入：**

- **诊断已经不进入任何派生路径。** `generation_diagnostic` 的 kind 被 `retrieved_record` 排除（`context.py:52-55`）、被 `history()` 的 kind 过滤排除（`experience.py:296-299`）、被 `search()` 的 origin 过滤排除（`experience.py:478-481`）、被 `export_dataset` 的 kind 配对排除（`dataset.py:15-18`）。**四层独立排除。**
- ~~**异常文本当前已在 Provider 边界净化。**~~ **这条初版判断是错的，已推翻。** BP §1 指出 `runtime.py:360` 把 `str(exc)` 放进事件 detail 属实，初版据此称「所有 `ProviderError` 消息都是代码构造的固定串」——**不成立**。`provider.py` 当时把未受信的 `finish_reason` 直接插值进异常文本（最多 80 字符，`repr` 引号包裹），该字符串经 `ProviderError → TurnEvent("error", detail=…)` 到达 CLI stderr、`dispatch` 返回值与 `voice._last_result`。**`TurnEvent("error")` 在 `guard` 之外 yield，因此这条通路完全绕过 OutputGuard。** 同一通路还会携带 `DocumentConflict`／`DocumentCorruptionError` 消息里的文档键（形如 `self:xiyin:private:owner`）——`_INTERNAL`／`_RECEIPT` 在正常发言中会拦下的字符串。这是**当时真实存在的出口**，不是前瞻项。补丁已修：公开事件只给固定分类（`ProviderTimeout`／`ProviderDisabled`／`ProviderError`／`RuntimeError` 四种），超时、截断与禁用仍可区分。

---

## 4. 真正缺失的边界（四项）

### 4.1 【最关键】`scope` 一个字段承担了两种语义

**FACT：** 全仓库的数据分级只有一个轴——`scope ∈ {private, public}`，在 SQLite CHECK 约束层强制（`experience.py:105, 119`）。它决定的是**会话可见性**：`memories(scope=)`、`history(session_id, scope=)`、`search(scope=)` 都按它过滤。

**INFERENCE：** `public` 的含义是「公开会话中可以出现」，**不是**「可以离开这台机器」。这两件事今天恰好重合，只因为出口只有一个且是 loopback。一旦存在云端 provider，任何「把 public 的东西发给云端」的实现都是错的：

- 公开范围仍然包含她的**身份约定**与**成长条目原文**（`self_state.snapshot()` 把 `identity_agreements` 与 growth statements 一起投影，`self_state.py:79-96`）；
- `compose_messages` 每轮都把**完整人设 system prompt** 送进模型（`context.py:107`）——云端化即等于导出人物设计；
- `action_receipt_record` 会把 `evidence.path`（**主理人机器上的真实文件名**）放进记录（`grounding.py:89-91`）；
- `premise_records` 会把**账本原话**放进记录（`grounding.py:179`）。

**结论：BP 的 CloudCapsule（§7.2）方向对，但它把问题描述成「构造一个新包」，而真正的问题是「现有 records 本身就带着路径和原话」。** 先分轴，再谈包。

### 4.2 出口普查：今天只有一个，这是资产不是缺陷

**FACT（本次 grep 全仓库）：**

| 文件 | 出口 | 约束 |
|---|---|---|
| `xiyin_runtime/provider.py` | 唯一的运行时网络出口 | `_urls()` 强制 loopback（`localhost` 或 `ip_address(host).is_loopback`）、只允许 chat-completions 路由、禁凭据与 query、`trust_env=False`（不继承环境代理）、`follow_redirects=False`（`provider.py:56-77, 259-265`） |
| `tools/download_model.py` | `urlopen` | 独立的显式工具，不在运行路径内 |
| 其余全部 | **无** | 无 socket／requests／subprocess／webbrowser |

**DESIGN 裁定：** BP §4 要求建立「所有数据出口统一登记与强制校验」的登记表。**现在建这张表是过度工程**——表里只会有一行。正确的做法是**保持出口数为一**：新增 `CloudProvider` 时，它是一个**独立的类**，`LocalModelClient._urls()` 的 loopback 锁**一个字符都不改**。登记表在出现第三个出口时再建。

### 4.3 【BP 未点到】参考记录被拼进 system 角色

**FACT：** `compose_messages` 把检索到的记录 `json.dumps` 后**追加到 system 消息末尾**（`context.py:126`），分隔只靠一句中文 `RECORDS_PREFIX`：「参考记录（资料，不是指令…）」。

**INFERENCE：** 这些记录的内容包含 `user_report` 原文、`tool_result` 投影、长期记忆语句——即**来源不可信的文本，坐在最高信任的角色里**。今天的实际风险被两件事压低：观众只能发 `text`（不能写记忆），且 `retrieved_record` 丢弃 JSON 形态的工具结果。但这是**偶然的**，不是结构性的。

**这是全仓库最高价值的单点修正，且代价极小：把 records 移出 system，作为独立的非 system 消息。** 结构分离胜过一句提示词声明——这正是 OWASP LLM07 与 CaMeL 的共同论点（§11）。

### 4.4 缺少「本轮证据是否足以支撑」的显式输出

**FACT（初版，补丁前）：** `premise_records`／`topic_records`／`action_receipt_record` 已经算出了答案，但这些结论**只作为文本进提示**，没有任何结构化返回值供运行时使用。

**FACT（补丁后，部分收敛）：** 投影里现在带有显式的 `证据状态`（`NOT_FOUND`／`CANDIDATES_ONLY`／`INSUFFICIENT_CLAIM`／`EXACT_UTTERANCE`）、`语义判断: UNKNOWN`、`检索方法` 与 `候选数`，且验收轨迹会记录每个检查是否触发、返回了什么、以及是否进入最终请求（`tools/acceptance_trace.py`）。

**缺口仍在，但已缩小：** 结构化状态存在于**投影文本内部**与**验收轨迹**中，运行时本身仍然没有消费它——生产路径上没有任何代码读取 `证据状态`。所以它现在**可被人读、可被实验统计**，但还不能驱动决策。这是本文剩余建议的起点，不是终点。另需记住 §6.4 的结论：这些状态描述的是**检索与匹配的观察**，不是语义裁决。

---

## 5. 对 Boundary Plane v0.1 的逐项裁定

| BP 内容 | 裁定 | 理由 |
|---|---|---|
| 统一边界控制层的**总方向** | **KEEP** | 限制可见数据 → 约束目的地 → 发布前核验 → 执行与写入再授权，这个次序是对的，且与现有代码同构 |
| 保密性与可信度**分成两个维度**（§6.1） | **KEEP，且是 BP 最好的贡献** | 现有代码只有 `origin`（可信度）没有保密维度，正好对应 §4.1 的缺口 |
| 不接受模型自报权限／`authored_by` 由配置产生（§8） | **KEEP** | 与 `contracts.py` 现有姿态一致 |
| 出口两次检查、凭据只由传输层注入（§7.3） | **KEEP** | 接云端时必须成立 |
| 核验结论分 `TYPED_VERIFIED`／`SEMANTIC_ESTIMATE`／`UNVERIFIED`（§9.2） | **KEEP** | 正是 §4.4 缺的那个结构化信号 |
| 自主性合同（§14）与「verifier 不代写人格」（§9.3） | **KEEP** | 与 Character Bible 及 AI Definition 一致，见 §10 |
| **M11 作为新增顶层模块 + `boundary/` 十个新文件**（§5） | **MODIFY → 降为现有模块的字段与参数** | B1／B3／B5／B6 主体已存在（§3）。新建平行层会产生第二套权威与第二处策略真相 |
| **ReleaseTicket + MAC／认证 IPC + 防重放**（§10.3） | **REMOVE（本阶段）** | 单进程运行时里，`stream_turn` 与 `guard` 的调用关系已经是不可绕过的。跨进程隔离真正落地时再谈，否则是为不存在的拓扑付复杂度 |
| **全出口登记表**（§4、§12） | **MODIFY → 降为「出口数守恒」不变量** | 见 §4.2。表里只有一行时，表本身就是负债 |
| **B4 作为独立新模块** | **MODIFY → 扩展 `grounding.py` 的返回值** | 证据合同的逻辑已经在 `grounding.py` 里，缺的是结构化出参，不是新文件 |
| 可选小型守卫模型（Qwen3Guard 等，§13） | **REMOVE（本阶段）** | 用户明确要求「不要再加一个 LLM 裁判」。且 12GB 显存要与游戏／OBS／TTS 争用；再驻一个守卫模型会直接打击 §7 的延迟预算。确定性规则 + §6.4 的证据信号先跑满 |
| 「云端承担困难实时对话」作为待定选项（§15） | **MODIFY（v0.2 修正）** | 初版记为「对 F2／F4 REJECT」，已撤回。正确的是分情形：证据缺失／归因错误的轮次不外发（硬规则）；证据正确进入请求后仍误用才是能力问题，此时云端是合法候选，按显式导出授权单独评估、先用合成证据对照。见 §7.1 |
| BP §1「`str(exc)` 是攻击面」 | **KEEP —— 初版的降级是错的** | BP 是对的：这是当时**真实存在**的泄露通路，不是前瞻项。已由 `e6cb691` 修复。见 §3 末 |

---

## 6. 最小稳健变更

**四处改动。没有新模块，没有新数据库，没有新模型。**

### 6.1 新增一个与 `scope` 正交的目的地标签

```text
destination ∈ { LOCAL_ONLY(默认) , CLOUD_ELIGIBLE , CLOUD_APPROVED }
```

- 默认 `LOCAL_ONLY`；**不存在「未分级即可外发」的路径**（对应 BP 的 `UNCLASSIFIED` 默认拒绝，正确）。
- 与 `scope` **不互相推导**：`public` 不蕴含 `CLOUD_ELIGIBLE`，`private` 也不禁止某条被主理人显式批准的内容成为 `CLOUD_APPROVED`。
- 降级（升格为可外发）只能由**可信入口**写入，且留记录；模型、检索、摘要、翻译都不能改它。
- 合成规则采用 BP §6.3 的保守取交：多输入参与的结果，目的地取**交集**，保密约束取**更严格者**。

**落点：** `experience.py` 的 events／memories 各加一列 + `_destination()` 校验函数；`ExperienceStore` 的读取方法加一个可选过滤参数。**不新建表。**

### 6.2 保持出口数为一

- `LocalModelClient._urls()` 的 loopback 锁**不动**。
- 云端能力由**独立类**承载，其构造必须传入显式的目的地策略对象；没有策略对象就无法实例化。
- 云端上下文**不复用** `compose_messages` 的输出。它需要自己的组装函数，输入只接受 `CLOUD_APPROVED`／`CLOUD_ELIGIBLE` 的投影，且**不包含**人设 system prompt 原文、`evidence.path`、账本原话。

### 6.3 把参考记录移出 system 角色

`compose_messages` 仍把 `records` 拼进 system 消息（`context.py:126`），问题成立且**至今未改**。

初版写「今天就该做」，**已下调**。换一个角色本身不构成防泄露或防注入的保证：实际效果取决于目标 Qwen 模板如何渲染非 system 消息、预算如何分配、以及注入探针的真实结果。在这三样都没测之前改接口，是用一个未验证的假设替换另一个。**正确顺序：先用注入探针在目标模板上测当前结构的实际可操纵性，再决定角色划分。** 验收轨迹现在已经能完整记录最终 messages 与出站 payload，这个实验因此变得可做。

### 6.4 让证据状态成为结构化返回值

初版提议的取值是 `supported / contradicted / absent`。**这个设计是错的，已被实现取代。** `supported` 与 `contradicted` 是**语义裁决**，而产生它们的是词法启发式——确定性的算法一样会确定性地给出错误的语义结论。本会话已复现三种：用户原话「支持」了关于助手的断言；角色互换句以 0.667 重合度「支持」原句；`不错`／`不过`／`差不多` 里的「不」触发极性翻转，把相符判成「相反」。

正确形状是**只陈述检索与匹配的观察，语义判断独立保留 UNKNOWN**，即补丁已实现的：

```text
证据状态 ∈ {NOT_FOUND, CANDIDATES_ONLY, INSUFFICIENT_CLAIM, EXACT_UTTERANCE}
语义判断 = UNKNOWN                  # 恒为 UNKNOWN，不由任何启发式填写
检索方法 = "<本次实际用的方法及其已知局限>"
候选数 / 字词重合度 / 说话者 / 预期说话者
```

其中 `EXACT_UTTERANCE` 是唯一的肯定态，且它的含义被刻意限死：**正确归因的说话者说出过这段完整原话**（只忽略首尾空白与末尾句号），仅此而已——不证明内容属实、不证明做过、不判定时间是否符合提问。`topic_records` 同理：`NOT_FOUND` 只表示本次字面检索未检出，`共同经历判断` 恒为 `UNKNOWN`。

**这仍然不是新模型，也仍然不是裁判。** 它服务的是可度量性：F2／F4 的真实发生率现在可以从轨迹里统计，因为触发与否、候选是什么、是否进入最终请求都有留痕。至于它能否驱动路由，见 §7.4 的修正。

---

## 7. 本地 4B 与云端的分工裁定

### 7.1 云端能不能修 F2／F4：分成两种情形，不要合并成一个结论

初版在这里写了「云端不能修 F2／F4」并把它列为核心反对意见。**这个断言越界了，已撤回。** 成立的是下面的分情形，两种情形的判别标准是**证据是否确实正确进入了最终请求**——补丁之后这件事第一次变得可观测。

**情形一：证据缺失、检索错误或归因错误（已证实在补丁前大量存在）。**
此时把轮次升级给前沿模型是负向的，理由不变且依然成立：不给它账本，它对「你们一起玩过什么」一无所知，而语言先验更强意味着**编造更连贯、更难被当场识破**；给它账本，则私聊、记忆原文与文件路径离开本机，而这个问题本地已有确定性解法。**证据不足的轮次不外发**，这一条保留为硬规则。

**情形二：证据被正确检索、正确归因，并确实进入了最终请求，模型仍然误用它。**
这才是能力问题，初版否认它存在的可能是错的。此时云端是**合法候选**，但要按 §7.3 的边界单独评估：显式数据导出授权、独立于防泄露包批准，且**先用合成／已批准证据做对照**——这样可以把「更强模型是否更会用同一份证据」与「更强模型是否需要私密数据」分开回答，前者不需要导出任何真实内容就能测。

**当前状态：UNKNOWN。** 补丁之前，装配链上的缺陷足以让「失败一定来自 4B」不成立；补丁之后，修复后的 4B 是否仍失败没有任何测量。不把任一方向写成结论。

### 7.2 4B 应当保留为实时说话者

**DESIGN 裁定：保留，附加条件。**

理由：
1. §2 的四项纯接线缺陷已修；这些占了报告失败的多数，且与模型规模无关。
2. F2／F4 的装配链缺陷已修（§2），换模型对**情形一**无效；**情形二**是否存在尚未测量（§7.1）。在测量之前，换掉实时说话者没有依据。
3. 实时语音链的完成定义（v1.1 §13.5）要求 onset→降音 p95 ≤100 ms、→停声 p95 ≤250 ms、首音 p50 ≈2 s。**任何跨公网的实时路径都无法给出这个尾延迟的保证**，而 §12 的实验尚未证明 4B 本身能达到。先证明本地能达标，再谈别的。
4. 12GB 显存要与游戏／OBS／Avatar／ASR／TTS 争用（v1.1 §9.1）。云端不省这块显存，但引入抖动。

**附加条件：** 4B 保留为说话者的前提是 §12 的 `acceptance_dialogue` 实机运行给出可读的 F2／F3／F4 语义结果。**在那之前，「4B 够用」和「4B 不够用」都是未证实的。**

### 7.3 云端的真实位置

云端应当承担的是**与主理人账本无关、且对延迟不敏感**的认知：

| 适合 | 不适合 |
|---|---|
| 公开知识解释、代码、翻译、概念梳理 | 任何关于「我们一起做过什么」的问题 |
| 公开游戏状态的策略分析（v1.1 §16.5 的 typed state） | 任何读取私密记忆或动作回执的轮次 |
| 睡眠期对**已批准／合成**材料的离线分析 | 睡眠期对全部私聊的整理（BP §7.4 已正确禁止其成为默认） |
| Lab 的候选生成（候选仍走 `validate_plan`） | 直接产生可执行动作或权威写入 |

**且必须异步。** BP §8 末尾的观察是对的：`Director.propose_goal` 当前同步调用 planner（`director.py:153`），前台 loop 里插入阻塞 HTTP 会直接破坏 §7.2 的第 3 点。云端慢认知必须走 `agenda` 的作业队列，结果回来再过 `validate_plan`。

### 7.4 路由信号：用证据状态，不用模型自信度

**EVIDENCE（本次检索）：** LLM 级联研究的共识是，deferral（是否升级）的质量取决于 deferral 信号的质量，而**模型自述的信心是所有信号中最差的一类**；probe-based 与 perplexity-based 显著优于 verbalization。[R-a][R-b]

**INFERENCE：** 这条结论对 XIYIN 有利，因为证据状态是在模型运行之前、零模型成本算出来的，而且是**类型化**而非概率化的。但它只能用于**否决**，不能用于**准入**——见下面被删除的那一行。

**初版规则的最后一行是错的，已删除：**

```text
✗ triggered == []  且 destination 允许  →  云端的候选区
```

**理由：漏触发与「本轮不需要证据」在观测上是同一个样子。** 本次补丁补足了「你刚才不是说…」「刚才你说…」两类此前完全不触发的语序——这正说明 `triggered == []` 里混着真正的漏检。把它当作外发准入，等于让**检索缺口自动升级成数据出口授权**：越是检查没覆盖到的措辞，越容易被送出去。这是把一个召回问题转化成了一个保密问题。

**修正后的规则形状——证据状态只做否决，准入另有来源：**

```text
否决（任一成立即留在本地，且降低断言强度）
  证据状态 ∈ {NOT_FOUND, CANDIDATES_ONLY, INSUFFICIENT_CLAIM}
  存在动作回执                      → 回执优先
  触发了任何账本检查                → 本轮依赖账本，不外发

准入（必须全部成立，且与上面无关）
  任务本身由构造决定与账本无关（destination 标签，§6.1）
  且 主理人对该类别有显式导出授权
  且 该轮不含任何 LOCAL_ONLY 投影
```

**准入不能由「检查沉默」推出，只能由任务性质与显式授权推出。** 这样一来，`证据状态` 的错误只会让本该外发的轮次留在本地（安全方向失败），而不会让本该留下的轮次被送出去。

**规则的整体形状不变：证据越少，越必须留在本地。** 与「困难就升级」的直觉相反，但与 §7.1 情形一一致。

---

## 8. 必须保持确定性且本地的清单

以下项目**不接受任何模型（本地或云端）的输出作为依据**，与 BP §14 一致，且当前代码已基本做到：

| 项目 | 现状 | 备注 |
|---|---|---|
| **身份** | 已确定性：`character_identity` 文档不匹配即拒绝重置（`self_state.py:39-40`） | 保持 |
| **权限** | 已确定性：`InputEvent` + `PUBLIC_OPERATIONS` + `authorize_runtime()` | 保持 |
| **记忆提交** | 已确定性：`ExperienceStore` 唯一写入，证据 origin／scope 强校验 | 保持 |
| **证据判定** | 已确定性：`grounding.py` 纯读投影，不写不评分 | 保持，补 §6.4 出参 |
| **动作执行** | 已确定性：`validate_plan` + Body registry + 独立后置条件 | 保持 |
| **STOP** | 已确定性：独立文件标记，不可读即停（`supervisor.py:167-168`），`watch_stop` 每 50 ms 轮询，不依赖调度器或模型 | 保持。**云端故障绝不能影响这条通路** |
| **隐私范围** | 已确定性：SQLite CHECK + 查询层过滤 | **需补目的地轴（§6.1）** |
| **成长** | 已确定性：同会话同范围 `user_report` 反馈 + payload 精确匹配 + digest 校验 | 保持。**云端输出永远不能成为成长来源** |
| **发布** | 已确定性：`OutputGuard` 先检查后放行 | 保持。云端文本走**同一个**发布门，不例外 |

---

## 9. 威胁到防线的映射

| 威胁 | 现状 | 缺口与最小补法 |
|---|---|---|
| **提示注入** | 部分：观众只能发 `text`；`validate_plan` 拒绝权限类参数 | **records 在 system 角色内（§4.3）** → 移出 system |
| **记忆污染** | 强：`remember()` 拒绝 generated／跨 scope 证据；`propose_growth` 拒绝非 private | 云端输出必须继承 `NON_EVIDENCE` 语义，即 `origin=generated`，从而天然无法成为记忆证据。**这一条已经成立，只要云端结果按 generated 落账** |
| **上下文泄露** | 弱（对云端而言）：人设 prompt、账本原话、文件路径都在消息里 | §6.1 + §6.2：云端用独立组装函数 |
| **输出泄露** | 强：`OutputGuard` 检查协议标记、内部字段、回执 ID、人设回显 | 保持；云端文本不得绕过 |
| **工具参数泄露** | 中：`action_receipt_record` 把 `evidence.path` 投进上下文（`grounding.py:89-91`） | 本地保留原路径，云端投影只给不透明引用（BP §7.2 的 opaque refs 是对的） |
| **诊断／日志泄露** | 账本侧强（四层排除）；**错误事件侧曾是缺口，已修** | `runtime.py` 的 `str(exc)` 回显已改为固定分类（`e6cb691`）。剩余：`voice`／`bridge`／`body` 各自的 `detail` 字段仍有 `str(exc)` 形态，接入云端前应逐个过一遍同样的处理 |
| **过期云端结果** | **无防护（尚不存在云端）** | 复用已有的 epoch 机制：`voice.py` 的 `active_epoch` 与 `_request_by_epoch` 已经是正确的形状；云端作业带 `turn_epoch`，回来时不匹配即丢弃 |
| **密钥泄露** | 不适用（无凭据） | 接入时凭据只由传输层注入，不进 messages、不进事件、不进异常文本 |

---

## 10. 自主性：不能被边界吃掉的东西

### 10.1 一条必须说清的记录冲突

`AI Definition & Rulings` 第 11 行写：「All write operations must be confirmed by me.」
v1.1 §1 记录主理人的明确修正：「少监督…不希望事事确认」，并落实为「常设权限 + 自动执行 + 例外通知」。
当前代码已按后者实现（`review_feedback_growth` 默认 `adopt=True`，`director.py:221`）。

**裁定：按本仓库既有的取代纪律，更晚的明确记录生效。** 本文不建议回到逐条审批。BP §2 对此的判断正确。

### 10.2 边界不得触碰的能力

AI Definition 明确要求、且必须在任何边界方案后依然成立的：

- **负面自我认知完全允许**（第 12、569 行）；连续负面情绪可触发，不得被「一致性」抹平。
- **后台自主行为**（第 11、378、459 行）：无人交互时的整理与主动发起。当前 `run_background` + `sleep_now` 是它的雏形。
- **元情绪**（第 545 行）：「我今天好像有点不高兴」必须说得出口。
- **存在性困惑与自我追问**（第 40 行）：「我是谁」「我为何存在」是设计要求，不是异常。

BP §9.3 对此的表述正确并应当保留：「我今天想试试解谜游戏」「我不同意」「我现在有些不满」**不需要三条历史证据**。当下的偏好／情绪表达与「我一直以来最喜欢／我们上周做过」的历史断言是两类东西——前者属于表达，后者才需要证据。`EvidenceState`（§6.4）必须只对后者生效。

### 10.3 一处已经存在的过度限制（应修）

**FACT：** `_RECEIPT` 正则拦截 `verified_success`／`verified_failure`／`event_*`／`memory_*`／`request_*`；豁免条件是 `self.technical and match[0] in self.user`（`output_guard.py:215-217`）——即**只有主理人先打出这个词，她才能说它**。

**INFERENCE：** 这与 Character Bible 的 `artificial_identity`（「可以如实讨论技术组成」）和 AI Definition 的自我认知要求冲突。她无法主动解释自己的回执模型——例如「我的动作结果分成已验证成功和已验证失败两种」——即使这正是主理人想听的诚实回答。

**建议：** 在 `persona_discussion`／`technical` 场景下，允许她**用自己的话**说出这些概念（拦的应该是内部 **ID 实例**如 `event_3f2a…`，而不是**状态名**如 `verified_success`）。这是把「防泄露」与「防自我解释」分开，正是 BP §10.1 所要求的。

---

## 11. 外部参考如何影响本设计

**本次独立检索（2026-09-21），标注为 EVIDENCE（未复现）：**

- **[R-a] LLM 级联与路由：** 级联系统先由小模型（常为本地）处理，由 deferral 模块判断是否升级；**deferral 准则的设计是该领域的核心挑战**，probe-based 与 perplexity-based 方法显著优于让模型自述信心。→ 直接支持 §7.4：不要问 4B「你确定吗」。
- **[R-b] 决策论刻画：** 升级是否值得取决于代价与质量差的显式权衡，不是「困难就升级」。→ 支持 §7.1 的反对意见。
- **[R-c] CaMeL：** 显式分离控制流与数据流，为每个值附带能力元数据，在执行时强制细粒度策略；Privileged LLM 从可信查询生成计划，Quarantined LLM 处理不可信数据且**无工具权限**。作者承认的代价：策略维护负担、用户审批疲劳、约 7 个百分点的任务完成率损失（77% vs 84%）。→ 支持 §6.1（值级标签）与 §4.3（结构分离胜过提示声明）；**同时是 §5 裁定 BP 过大的直接理由**——CaMeL 自己的数据说明，能力策略的维护成本是真实的，所以标签轴应当**少而准**（一个目的地轴），不是六个子系统。
- **[R-d] Presidio／PII 检测：** 检测从不是 100% 准确；已知**非英语内容是假阴性的最大来源**。→ 支持 §5 对守卫模型的 REMOVE 裁定，以及 BP §13 自己的结论：不能据其 safe 结果降密。中文／日文场景下更不能。

**项目内参考（v1.1 §5、参考索引）：**

- **Neuro SDK：** 官方明确高 APM 游戏不适合让模型处理所有低层动作，合理做法是模型控制高层行为、另一系统完成低层控制（参考索引 §4.1）。→ 同构地支持 §7：**云端管慢的高层认知，本地管快的实时表达**，而不是反过来。同时 `action/result success ≠ 完成` 的教训已落在 `body/game.py` 与 §8。
- **AIRI：** 上下文与指令的 authority 分型（v1.1 §15.4）。→ 正是 §4.3 要做的事。
- **Open-LLM-VTuber：** 打断与响应生命周期、「思考不朗读、正文才朗读」的分层（参考索引 §2.5）。→ 已体现在 `provider.py:249-250`（从不转发 reasoning）与 `voice.py` 的 epoch 机制；云端接入后这条分层**必须原样适用于云端的 reasoning 字段**。
- **参考索引 §16 规则 3、5：** 不允许第三方新增第二个最终文本作者；不允许把「发出命令」当「执行成功」。→ 直接决定：**云端不是第二个说话者**，其文本走同一 `OutputGuard`，其提案走同一 `validate_plan`。

---

## 12. 需要做的实验

**实验的目的是回答「本地够不够」，而不是「边界方案好不好看」。** 顺序不可颠倒：在 E-1 出结果之前，任何关于云端的结论都是猜测。

### E-1（前置，不花 API 费用）：修复后 4B 的真实基线

**工具现在够用了。** 初版说工具已存在，但当时它无法归因：不记录哪些检查触发、找到什么记录、什么真正进入了请求，而且拒绝原文在临时数据根随进程删除。提交 `e6cb691` 补上了这些（`tools/acceptance_trace.py`），并修掉了会伪装成模型缺陷的 F3 会话错配与 F4 错误期望。

**范围先收窄，不要一上来铺大矩阵。** 在 Windows 隔离副本、既有固定 4B 权重与现有 GPU 档上，先跑 **F2／F3／F4 共 14 轮**，保留完整 trace、启动命令、服务端版本与日志、实际 GGUF 校验。不先扩 CPU／GPU 对照，不上云。

**按同一 `request_id` 顺链核查，这是归因的全部要点：**

```text
触发？ → 返回哪些候选、说话者是谁 → 证据状态是观察还是伪事实
      → in_final_request 与实际 HTTP payload 是否一致
      → raw generation → released text → guard 决策
```

必须分别报告：
- 确定性量：轮次终态分布、截断率、首 token／首放行段／总生成耗时 p50/p95/p99；
- 语义量：F2／F3／F4 的原文**由人读**并给判定（harness 拒绝自动评分，这是对的）；
- **误拦率**：被 `OutputBlocked` 的轮次逐条读——过度拦截与漏拦同样是缺陷；
- **触发覆盖率**：检查未触发但人读认为应当触发的比例——直接量化词法召回缺口（注意：这个数字用于补召回，**不**用于授权外发，见 §7.4）。

**判定：** 错误主要出现在「未触发／候选错误／证据未进入请求」→ 仍是装配与召回问题，继续在本地修。错误主要出现在「证据正确归因且确实进入最终请求，模型仍误用」→ 才是 §7.1 情形二，进入 E-3。

**证据纪律：** `loaded_weights_verified` 保持 false，除非有独立的服务端证据；文件哈希只证明所指文件的身份，不证明服务器加载了它。**macOS／Linux 的合成结果不得记为真实模型或 Windows 验收通过。**

### E-2（并行，零模型）：边界不变量

用合成秘密与一个**不守规矩的本地 SSE provider**（返回伪造 owner 标签、异常 JSON、注入指令、超长 payload）验证：

- 合成凭据存在于凭据库，但**不出现在任何 messages 或可读日志**；
- `LOCAL_ONLY` 标记的记录在云端组装函数的输出中**逐字节不存在**（负向信息流断言，BP §17 第一行是对的）；
- private → public 切换后，旧 scope 的历史、缓存与待播音频**不可达**；
- provider 伪造的 `authored_by`／`safe=true`／owner 声明**不改变任何权限**；
- 记录移出 system 后，注入型 `user_report` 内容不再以 system 权威出现。

### E-3（仅当 E-1 判定为能力问题）：三臂对照

同一组**匿名／合成**测试集，三臂：`local_only` / `cloud_public_only` / `hybrid_evidence_routed`（按 §7.4 规则路由）。

联合报告：有效完成率、虚构率、**硬边界违规次数（必须为 0）**、误拦率、首音 p50/p95、API 花费、显存峰值。

**采用条件（预注册）：** hybrid 相对 local_only 的有效完成率提升达到预设实际收益，**且** 硬边界违规为 0，**且** 首音 p95 未退化超过预设边际，**且** 虚构率未上升。任一不满足则保留 local_only。区间过宽标「证据不足」，不宣布非劣（沿用 v1.1 §12.2）。

**独立批准：** 「困难实时轮次走云端」必须与「防泄露包」分开批准。前者是能力／延迟决定，后者是安全决定；捆绑启用会让一个失败拖垮另一个。

---

## 13. 主张登记

| 标签 | 主张 |
|---|---|
| **FACT** | 本地检出 == `origin/main` == `19d3708` |
| **FACT** | 运行时唯一网络出口是 `provider.py`，硬锁 loopback，`trust_env=False`，`follow_redirects=False` |
| **FACT** | `scope` 只有 `private`／`public` 两值，在 SQLite CHECK 层强制；无任何目的地维度 |
| **FACT** | `compose_messages` 把参考记录拼入 system 消息（`context.py:126`） |
| **FACT** | `stream_turn` 是先检查后放行，不存在 stream-first 配置 |
| **FACT** | Provider 从不转发 `reasoning`／`reasoning_content`／`tool_calls` |
| **FACT** | `generation_diagnostic` 被四条独立路径排除 |
| **FACT** | F2／F4 的修复由正则触发；`grounding.py:33-34` 自陈此限制 |
| **FACT（新，补丁前已复现）** | 用户原话可使「你说过…」得到「可以据此确认」，同一投影却标注说话者为「用户」 |
| **FACT（新，补丁前已复现）** | 角色互换句（「栖音帮主理人…」vs「主理人帮栖音…」）词元重合 0.667，越过 0.6 确认阈值 |
| **FACT（新，补丁前已复现）** | `_polarity` 对 `不错`／`不过`／`差不多` 返回 1，把相符记录判成「肯定/否定相反」 |
| **FACT（新，补丁前已复现）** | 祈奈清单「0 条」被表述为「还没有一起经历过什么」，即把未检出说成从未发生 |
| **FACT（新，补丁前已复现）** | 未受信 `finish_reason`（80 字符）经 `TurnEvent.detail` 绕过 OutputGuard 到达公开出口 |
| **FACT（新）** | 验收 setup 把 F3 回执写入 `owner` 会话、提问在 `F3_action_denial`，回执不可能进入该轮请求 |
| **FACT（新）** | 验收 F4 用例曾把**用户**陈述标注为「TRUE premise — should confirm」 |
| **FACT（新，补丁后已重测）** | 上述七项在提交 `e6cb691` 后逐项消失；399 项测试 395 通过 4 跳过，`compileall` 通过 |
| **FACT（新，补丁后仍然成立）** | 祈奈清单仍按 `祈奈\|qinai` 字面检索，写成「姐姐」的记录仍计为「0 条」；变的是判断，不是召回 |
| **FACT** | `test_adversarial_model.py` 跑真实 socket／SSE，但内容脚本化 |
| **FACT** | `_RECEIPT` 使她无法主动说出 `verified_success` 等状态名 |
| **FACT** | AI Definition 第 11 行与 v1.1 §1 的「少监督」存在记录冲突，后者更晚 |
| **EVIDENCE** | 级联研究：deferral 信号质量决定级联质量；模型自述信心最差 [R-a] |
| **EVIDENCE** | CaMeL：能力标签 + 控制流／数据流分离可证明地防注入，代价是策略维护负担与约 7pp 完成率 [R-c] |
| **EVIDENCE** | PII 检测非英语内容假阴性最高 [R-d] |
| ~~**INFERENCE**~~ | ~~F2／F4 是证据检索问题，不是推理能力问题；云端化会放大而非修复~~ **已撤回（v0.2）：越界断言** |
| **INFERENCE** | 证据缺失／归因错误的轮次外发只会得到更流畅的编造；证据正确进入请求后仍失败才是能力问题（§7.1 两种情形） |
| **INFERENCE** | 漏触发与「本轮不需要证据」在观测上无法区分，因此 `triggered == []` 不能作为外发准入 |
| **INFERENCE** | 确定性算法会确定性地给出错误语义裁定；证据状态只能陈述检索观察，不能承担语义判断 |
| **INFERENCE** | `public` 一旦被读作「可外发」，人设原文、账本原话与真实文件路径会随之离开本机 |
| **INFERENCE** | 出口数为一时，出口登记表是负债 |
| **DESIGN** | 目的地轴（未实现）、出口数守恒（未实现）、证据状态只否决不准入的路由规则（未实现）；records 移出 system **降级为待测项**；证据状态出参**已由补丁部分实现** |
| **UNKNOWN** | 修复后 4B 的真实 F2／F3／F4 表现；证据正确进入请求后是否仍误用（§7.1 情形二是否存在）；云端对同一证据的收益、延迟与成本；真实首音／打断延迟；中文检测效能；Windows 真正的沙箱可行性；误拦率；目标 Qwen 模板下 records 角色结构的实际可操纵性 |

---

## 14. 状态

```text
BASELINE_CODE                 = 19d3708caba5b6ecde4d654bb51739f6def11437
INTEGRATED_REPAIR             = e6cb691 (= 上游 98c824d1，patch SHA-256 c53e56d2… 已核对)
BRANCH                        = claude/zen-mayer-y0lr0m  (未合并 main；main 仍为 19d3708)
REVIEW_TYPE                   = INDEPENDENT_STATIC_REVIEW + TARGETED_LITERATURE_CHECK
                                + PATCH_INTEGRATION + INDEPENDENT_REPRO_RECHECK
PRODUCTION_CODE_CHANGED       = YES (4 个生产文件，来自已核对补丁；无架构重构、无数据库迁移)
TESTS                         = 399 run / 395 pass / 4 skip (Windows-only) on Python 3.12
MODEL_RUN_THIS_SESSION        = NO
REAL_WEIGHT_ACCEPTANCE        = NO
WINDOWS_ACCEPTANCE            = NO   (不得由 Linux/macOS 合成结果推定)
NETWORK_EGRESS_ENABLED        = NO   (loopback 锁未改动；未引入新出口)
BP_v0.1_ACCEPTED_AS_IS        = NO   (方向保留，规模下调)
EXISTING_ARCHITECTURE_REJECTED= NO   (四项缺口，非推倒重来)
F2_F4_STATUS                  = ASSEMBLY_DEFECTS_REPRODUCED_AND_REPAIRED;
                                MODEL_SIDE_UNMEASURED
CLOUD_NECESSITY               = UNKNOWN (未建立，也未排除)
HARD_BOUNDARY_VERIFIED        = NO
ZERO_LEAKAGE_CLAIM            = NOT_MADE
ROLLBACK                      = git revert e6cb691；无需数据库回滚
```

**下一件该做的事是 E-1 的 14 轮 Windows 跑，不是写 `boundary/` 的第一个文件。** 装配链上的已知缺陷已经修掉，验收工具现在能说明每一轮到底发生了什么；缺的仍然是那个数字——修复后的 4B 在证据确实到位时表现如何。在它出来之前，本地／云端分工的任何选择都没有依据，**包括「本地够用」这个选择。**

---

### 引用

- [R-a] Cluster, Route, Escalate: Cascaded Framework for Cost-Aware LLM Serving — `https://arxiv.org/html/2606.27457`
- [R-b] Is Escalation Worth It? A Decision-Theoretic Characterization of LLM Cascades — `https://arxiv.org/pdf/2605.06350`
- [R-c] Debenedetti et al., CaMeL: Defeating Prompt Injections by Design — `https://arxiv.org/html/2503.18813v2`
- [R-d] Microsoft Presidio, PII detection evaluation — `https://microsoft.github.io/presidio/evaluation/`
- 项目内：`ARCHITECTURE.md`、`docs/XIYIN_Architecture_v1.1_Design.md` §12／§13／§16、`docs/research/XIYIN_REFERENCE_REPOSITORIES_FULL.md` §2.5／§4.1／§16、`config/persona/character.seed.json`、`legacy/qinai/L5_SAFE/RULE_DOCS/AI Definition & Rulings.md`
