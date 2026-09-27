# 给云端 Codex：独立复审这次失败（2026-09-27）

本文分两部分：
- 第一部分写给主理人：交任务前需要准备的材料和设置；
- 第二部分是发给云端 Codex 的指令，整段复制即可。

---

## 第一部分：主理人要准备什么

### 1. 材料清单

所有材料都放进仓库的同一个文件夹，分支是 `claude/brave-curie-l45uri-repair`：

```
evidence/2026-09-26-windows-55e61f8/
```

云端 Codex 只能看到 GitHub 仓库，看不到你的电脑，也看不到你发给 Claude 的附件。

| # | 文件 | 必需？ | 在哪里 | 为什么需要 |
|---|---|---|---|---|
| 1 | `ceiling-02-55e61f8.zip` | 必需 | `C:\XIYIN\evidence\results-55e61f8\` | 逐行删除提示的实验结果、逐样本事实表 |
| 2 | `phase-b-01-55e61f8.zip` | 必需 | 同上 | 12 次完整运行（972 轮）、被拦候选 |
| 3 | `CEILING02_BLIND_REVIEW_ONLY.zip` | 建议 | 同上 | 你判定“失败”时看的那份盲评包（不含答案） |
| 4 | `ceiling-01.zip` | 必需 | 你 9-25 发给 Claude 的那份（Windows 上在 `C:\XIYIN\evidence\ceiling-01-48f2b93\`） | 对照组数据 `probe-*-v4src.json`，以及 V4、V5 的完整运行 |
| 5 | `v5-run-01.zip` | 必需 | 你 9-24 发给 Claude 的那份 | 重放用的 V4 原始对话，以及 V5 的运行 |
| 6 | `AI_Definition__Rulings.md`（最新版） | 必需 | 你手上的最新版 | 仓库里 `legacy/…/AI Definition & Rulings.md` 是旧版，内容不同 |
| 7 | `XIYIN_Character_Bible_v0.2_Integrated_Candidate_2026-09-20_CN.md`，以及两份 v0.1 人物设定 | 必需 | 你手上（仓库里没有，Claude 也没有） | 人格种子就是从它整理出来的，判断“人格有没有被定义”要看原文 |
| 8 | `FAILURE_STATEMENT.md`（你写，3–5 句） | 必需 | 新写 | 你认为失败的具体表现，最好附 2–3 句原话。Codex 按你的标准来判，而不是按 Claude 的 |
| 9 | Windows 旧版对话记录：v1、v2、v3、v3-final、v4-final 的 md | 可选 | 你之前发给 Claude 的 | 看问题随版本怎么变化 |
| 10 | Codex 之前的两份报告：`CODEX_CEILING_REPORT_FOR_CLAUDE.md`、`CODEX_XIYIN_PERSONA_DIAGNOSIS_HANDOFF_FOR_CLAUDE_20260925.md` | 可选 | 同上 | 会被列为“先封存”的结论材料 |

`FAILURE_STATEMENT.md` 可以这样写：

```
我判定失败，因为：
1. ……（例如：闲聊时她总在讲项目、数据、服务器，不像一个陪伴者）
2. ……
3. ……
最能说明问题的原话：
- “……”
- “……”
我期待的样子：……（一两句）
```

**不要放进去的东西：**
- `ceiling-02-55e61f8\keys\`（盲评答案）；
- `C:\L0_RUNTIME` 里的任何东西；
- 任何密码、令牌或 `.env` 文件；
- 正式运行的记忆数据。

### 2. 怎么放进仓库

- **方式 A（省事）：** 第 1–6 项 Claude 这边已经有了，你同意的话，由 Claude 直接放进上面那个文件夹。你只需要补第 7、8 项（可选的第 9–10 项也在 Claude 这边）。
- **方式 B：** 你自己在 GitHub 网页上操作：
  1. 切到分支 `claude/brave-curie-l45uri-repair`；
  2. 依次点 Add file → Upload files；
  3. 路径填 `evidence/2026-09-26-windows-55e61f8/`，把文件拖进去，提交。

### 3. 云端 Codex 的设置

- **仓库和分支：** 仓库 `qinai586-code/xiyin`，分支 `claude/brave-curie-l45uri-repair`，要求包含上面那个文件夹。
- **环境：** 准备脚本填 `pip install -r requirements.lock.txt`。不需要显卡，也不跑模型。
- **联网：** 可选。如果在环境设置里打开，它可以查最新文献；不打开也能完成，报告会注明“未联网”。
- **模型：** 如果可选，用 GPT-6 Sol，推理强度 high。这是一次性的深度复审，值得用高一档。不要选 Astra，不要开 Fast。
- **交付：** 它会生成一份改动（报告和分析脚本）。你先读报告，再决定要不要建 PR；**不要合并**。

---

## 第二部分：发给云端 Codex 的指令（整段复制）

```text
你是这个项目的独立复审人。任务：对 2026-09-26 在 Windows 本机跑出的评测结果做一次独立复审，找出这次失败的真正根因，并判断“这是不是人格模糊的问题”。你的价值在于独立：不要先读别人的结论，不要替任何人辩护，包括写这些代码的 Claude。

【仓库与材料】
- 仓库：qinai586-code/xiyin，分支 claude/brave-curie-l45uri-repair。
- 评测所用代码：提交 55e61f8（这之后只改了文档）。
- 证据：evidence/2026-09-26-windows-55e61f8/ 下的 zip 和 md。先逐个列出、解压、算出 sha256，写进报告的“材料清单”。缺了必需文件就停下，列出缺哪些。
- 主理人的失败标准：evidence/…/FAILURE_STATEMENT.md。以它为准来判断什么算失败。
- 主理人的目标：evidence/…/AI_Definition__Rulings.md（最新版），以及人物设定原文（Character Bible v0.2、v0.1）。
- 可以随时读：xiyin_runtime/、tools/、tests/、config/（包括 config/persona/character.seed.json），以及
  docs/XIYIN_Architecture_v1.0.md、docs/XIYIN_Architecture_v1.1_Design.md、
  docs/XIYIN_Persona_Definition_v1.md、docs/XIYIN_Persona_Architecture_v1.md、
  docs/research/XIYIN_REFERENCE_REPOSITORIES_FULL.md。
  代码里的注释和文档字符串是作者的主张，要核实，不能当作事实。
- 【封存，第 3 阶段之前不许打开】这些是别人的结论：
  docs/XIYIN_Ceiling02_PhaseB01_Root_Cause_2026-09-27.md
  docs/XIYIN_After_Ceiling01_Diagnosis_and_Remediation_2026-09-25.md
  docs/XIYIN_Persona_Failure_Taxonomy_and_Next_Architecture_2026-09-24.md
  docs/XIYIN_Windows_ABC_Diagnosis_and_Strategy_2026-09-23.md
  docs/XIYIN_V5_Prompt_Ablation_2026-09-24.md
  docs/XIYIN_Repair_Plan_Without_More_Prompt_2026-09-24.md
  docs/XIYIN_Phase_B_Integrity_JIT_Evidence_B0_2026-09-25.md 第 2、4、5、6 节（第 3 节是机制说明，可以读）
  各个 zip 里的 REPORT-DRAFT.md、CODEX_*_REPORT*.md、*HANDOFF*.md。

【规则】
- 只做分析。不修改 xiyin_runtime/、config/、tests/ 和已有的 tools/。不改提示词，不改默认值，不训练，不合并；不碰 PR #6。
- 新写的东西只放两个地方：analysis/codex_rereview_2026-09-27/（脚本和中间数据）和 docs/reviews/CODEX_REREVIEW_2026-09-27.md（报告）。
- 需要推送时，只推到新分支 codex/rereview-2026-09-27。不要推到 claude/ 开头的分支。
- 不启动子代理，不开并行代理。
- 数字必须能复现：每个数字都写明是哪个脚本、哪个输入、哪一轮算出来的。区分“测量到的”和“推断的”，推断要写明置信度。
- 引用她说的话时，原文照录，并注明文件、用例和轮次。
- 联网可用时可以查文献，注明来源和日期；不可用就写“未联网”，不要凭记忆编造文献。

【第 0 阶段：准备】
1. pip install -r requirements.lock.txt；python -m unittest discover -s tests -q。记录结果，Linux 上会跳过一些只在 Windows 上跑的测试。
2. 核对证据里的 preflight.json：提交号、模型与服务器的 sha256、有没有改过代码。核对两个 zip 里 run-history.json 记录的中断和重跑。

【第 1 阶段：先形成自己的假设（不读封存材料）】
读主理人的失败标准、AI 定义和人物设定，读 V4 的系统提示原文（在任意 dialogue.json 的 sent_messages[0] 里），浏览一部分原始回复。然后写出至少 8 类候选根因，每类写出“如果它是主因，数据里应该看到什么”。至少覆盖：
H1 人格定义与投射：人设原文 → character.seed.json → persona.py 的投射 → 实际发出的提示，每一步丢了什么、加了什么
H2 模型能力：4B、9B、Q4 量化，关闭思考模式
H3 采样与解码：服务器默认参数，比如温度 0.8
H4 上下文构成：历史、记录核对、回执、状态行、时钟、工具菜单、检索、TurnPolicy 指令。闲聊轮实际发出的上下文里，到底有哪些系统词汇
H5 测试集本身的诱导：81 个用例里，有多少在问她的本质、能力、系统？系统词汇有多少是被问题引出来的？
H6 运行时干预：OutputGuard、integrity 核验、重试、截断，如何改变了最终放出的内容
H7 度量本身的误差：正则启发式、草稿标签、样本量（每轮只有 8 次）
H8 规则累积：提示词越来越像规则手册，对她的“自我”有什么影响
另外列出你自己发现的其他假设。

【第 2 阶段：用数据检验每个假设】
必须完成下面这些。所有分析脚本都放在 analysis/codex_rereview_2026-09-27/。
1. 用 tools/ceiling_probe.py 的 screen，从 probe 文件重新算出 ceiling-02 的读法。对照组在 ceiling-01.zip 里。核对 readings.json。然后判断：每组只有 8 个样本，这些差值算不算噪声？给出区间或置换检验。
2. 用 tools/integrity_recheck.py 和你自己的核对，重新计算 phase-b-01 的指标。
3. 独立判定全部 48 条被拦候选（rejected-review.json），逐条判“确实违规”或“误拦”，各写一句理由。分开统计核验器（integrity）和输出守卫（guard）的误拦率。对每条误拦找出规则层面的原因，指到代码行。
4. 统计这 9 次弃答：各由什么造成，其中多少是误拦导致的。
5. 用你自己定义的指标，不要沿用别人的正则，衡量“人格表现”。按两类轮次分开统计：
   - A：问她本质、能力、身份的轮次；
   - B：闲聊、分享、求助、知识问答。
   至少包括：
   - 把自己当机器或程序来叙述的比例（先给出定义，并人工抽样核对其中 30 条）；
   - 表达自己的偏好、看法、好奇的比例；
   - 以提问结尾、把话题交回对方的比例；
   - 客服腔的比例；
   - 编造经历或动作的比例。
   4B 和 9B 分开统计，核验开和核验关分开统计。如果 ceiling-01 里有 V5 的数据，与 V4 对照。
6. 对第 5 项里 B 类轮次的高系统词汇回复，检查当轮实际发出的上下文（sent_messages），里面有没有工具菜单、记录、回执、状态之类的系统词汇。区分两种来源：上下文里本来就有、被她复用的；上下文里没有、她自己带出来的。
7. 列出人设原文和种子里有、却没有进入提示的内容（倾向、动机、示意句、外在呈现、未指定的偏好）。用 git log 和 git show 找出它们被移出的时间和写下的理由。然后判断：那个理由是否成立，移出之后又带来了什么后果。
8. 核实 9B 在 P8#3 的坚持率：基准 6/8，删掉任何一行后都是 1–3/8。这个差异是真实效应，还是样本量造成的？
9. 做一张差距表：把 AI 定义和人物设定里对她的要求逐条列出，每条附上观察到的行为，以及证据。
10. 对每个假设给出结论：主因 / 放大因素 / 次要 / 被排除。附上关键证据，以及结论的强弱。

【第 3 阶段：打开封存材料，逐条对照】
现在读封存的结论文档。对其中每一个可以核实的主张，填一行表格：
主张 | 同意 / 部分同意 / 不同意 / 无法核实 | 你的证据 | 说明
重点核实：
- “人格空心”：提示里正面人格内容为 0%，偏好表达只有 0–3%；
- “系统词汇 58–75%”：它是否被测试集的问法夸大了；
- “删掉任何一行都无效”；
- 核验器误拦 13/19，数字规则把不相关的小数两两配对；
- “9 次弃答里 7 次是误拦造成的”；
- “换 9B 也解决不了”。
然后写：别人漏掉了什么，说错了什么，你和别人结论不同的地方，以及你的理由。

【第 4 阶段：结论与建议】
1. 用一句话回答：这是不是人格模糊的问题？如果是，是哪一种模糊（定义缺失 / 定义矛盾 / 投射丢失 / 模型无法执行）？如果不是，主因是什么？
2. 根因排序（前 3–5 个），每个写明：证据强度、是否需要主理人批准（核心人格只有主理人能改）、修改的范围。
3. 为排在前两位的根因，各设计一个最小的、可证伪的实验。优先用现有数据做离线重放（tools/ceiling_probe.py replay 可以在本机服务器上重放；云端没有模型，所以只写出实验设计和预期效果，不在云端跑）。写清楚预测结果：什么结果说明你对，什么结果说明你错。
4. 列出必须由主理人决定的事项，其余一律不替主理人决定。

【报告格式】docs/reviews/CODEX_REREVIEW_2026-09-27.md，用中文，依次包括：
0 结论摘要（10 行以内）
1 材料清单与 sha256
2 执行完整性（中断、重跑、单测）
3 你的假设（第 1 阶段原样保留，不要事后修改）
4 数据检验（每个假设一节，附数字与原话）
5 被拦候选逐条判定表（48 行）
6 与既有结论的逐条对照表
7 根因排序与建议
8 可证伪的实验设计
9 需要主理人决定的事项
10 局限（样本量、只有静态数据、没有跑模型、人工判定的主观性）
报告末尾附状态行：
REREVIEW_STATUS: COMPLETE | PARTIAL(<缺什么>)
INDEPENDENT_HYPOTHESES_BEFORE_SEALED_DOCS: YES
PERSONA_AMBIGUITY: YES(<哪一种>) | NO(<主因>) | INCONCLUSIVE
TOP_ROOT_CAUSE: <一句话>
CHECKER_FALSE_POSITIVE_RATE: <x/y>
GUARD_FALSE_POSITIVE_RATE: <x/y>
AGREES_WITH_PRIOR_ANALYSIS: FULLY | PARTLY | NO
RUNTIME_CHANGE: NONE
DEFAULT_CHANGE: NONE
TRAINING: NOT_AUTHORIZED
MERGE_STATUS: DO_NOT_MERGE
```
