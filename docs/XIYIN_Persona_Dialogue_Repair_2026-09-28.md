# 栖音人格与对话失败：原因、修复与 Windows 验证卡（2026-09-28）

分支：`claude/xiyin-persona-dialogue-repair`（从 `97dc3d0` 起）。不合并、不部署、不训练、不改默认。

**本文的结论级别：离线修复已就绪，等待 Windows 实机验证。** 这不等于“栖音已经能正常对话”。
单元测试通过、判官不再误杀，都不算自然对话成功。真正的行为结论要等下面第 7 节的实机对比和盲评。

---

## 1. 先说清楚：实际运行的是什么

以代码和配置为准（不是旧的 QINAI L0–L5/P1/C1–C6 架构）：

```
xiyin.py → cli → XIYINRuntime.open() → stream_turn:
  _prepare（人格投影 + 历史 + 记录 + 事实） → _plan_turn → build_turn_policy
  → 指令（计划 + v4 的 move 行） → _compose → 本机 LocalModelClient
  → OutputGuard（流式，边生成边放出）
  → [可选：整段核验 integrity，一次重试，再弃答] → ledger
```

| 项目 | 默认（`config/runtime.toml`） | 实验 |
|---|---|---|
| 人格投影 | `v3` | `v4`、`v5` |
| 整段核验（hold） | `verify_before_release = false` | 打开即 Phase B |
| 本次人格开关 | 全部关闭，并且只在 `v4` 下生效 | `attention`、`self_facts_on_demand`、`tool_menu_on_demand`、`no_universal_ending` |

**默认模式下只有 OutputGuard 在工作。** integrity 核验器只在 hold 打开时才拦截。
所以第 4 节里 integrity 的修复，在默认模式下不改变放出的内容。它影响的是 hold 实验臂，以及离线复检。

记忆、学习、睡眠、自主、升级路径和语音打断这些模块，本分支都没有改。它们的测试全部照常通过。

---

## 2. 有证据的原因、假设和 UNKNOWN

### 2.1 已证实

| # | 原因 | 证据 | 对应条目 |
|---|---|---|---|
| 1 | 人格在投影时丢失：四个倾向、动机和示例句从来没有进入模型 | 972 个实际请求里，倾向/动机/示例 0/972；说话方式和立场 972/972；move 结尾句 924/972 | R-04、R-05 |
| 2 | 按回合做决定的 `turn_move(text, mode, scale, reason)` 不读种子，也不读成长记录 | 代码 | R-05 |
| 3 | 接口菜单引出工具话术 | ceiling-02 消融：tool_talk 51→10（4B）、70→10（9B），分母 648；4B clean +6.48pp | F-01、R-03 |
| 4 | 判官误杀 | integrity 19 行里 15 行理由错；guard 29 行里 17 行理由错 | J-01…J-05 |
| 5 | 模型本身的语义错误确实存在 | 编造、把用户经历说成自己的、关系说错等，见第 6 节 | D、E、F、REL |
| 6 | 重试沿用同一组消息 | 代码 | J-07（本分支未改） |

### 2.2 本分支验证的假设

- **H-A（attention）**：在分享和问看法的回合，给一句有条件的注意力提示，可以改善 R-04/R-05，而且不增加 D 类编造。
- **H-B（no_universal_ending）**：不再每回合追加“说完就停，接不接着聊由对方决定。”，可以减少模板腔（R-02、R-07）。
  - 风险：ceiling-02 中 9B 去掉整条 move 行后，P8#3 顶住压力从 5/8 降到 0/8（校正后不显著）。
  - B 臂只去掉结尾句，保留 move 行。这一项要单独看 9B 的 P8#3。
- **H-C（self_facts_on_demand）**：把“你靠模型、程序…运行”从常驻提示移到被问到本质的回合，可以减少 R-03、F-03，并且不增加 D-02。
- **H-D（tool_menu_on_demand）**：只在任务回合给接口菜单，可以保住 ceiling-02 中工具话术的下降，并且不增加 M 类问题。

### 2.3 仍是 UNKNOWN

- 以上四个开关对真实模型输出有没有作用。
- 4B 的能力上限，以及是否需要训练：都没有证明。
- 第 6 节那些语义层面的漏判，能不能用非训练手段解决。
- 9B 相对 4B 的净收益。
- 截断：ceiling-02 有 147/5184 个样本因长度截断，本分支没有处理。

---

## 3. 修复清单（均可单独回滚）

| 提交 | 内容 | 默认行为是否改变 |
|---|---|---|
| `d5dbd96` | integrity 核验器：主语绑定、数值配对、引语归因、回执豁免、比喻/转述局部判断、新增 absence 类（E-01）、后台活动措辞 | 否（只在 hold 下拦截） |
| `627e0b5` | OutputGuard：说话人标签必须像名字；用户要的代码块按数据处理；被问到人设或角色扮演时允许自我描述，逐字私有规则仍然拦截 | **是**（guard 始终在运行，误拦会减少） |
| `6f2b350` | 四个人格实验开关，外加 everyday 用例集（10 个用例、15 轮，事先写定） | 否（全部关闭，而且只在 v4 下生效） |
| `d61fcfa` | 评测流水线新增 persona01：四个臂、分轴盲评、送达核对；修复 Windows 端口释放和 macOS 僵尸进程检测 | 否（只影响测评工具） |

四个开关各自对应一个已证实的原因，写法如下：

- **attention**：只在对话模式的分享回合，以及问她自己看法的回合生效，而且都用“如果……”的条件句。
  - 分享回合：从一个具体的地方接；那是对方的经历；想问就问一个具体的，不想问就不问。
  - 问看法回合：从她会注意到的地方答；没有想法就说没有。
  - 用户要离开时（先忙、晚安等）不给提示。
  - 提示里不出现任何倾向名称。它和其他指令一样受回显保护：模型原样复述会被拦下。
- **self_facts_on_demand**：这句自我事实仍然是可以说的事实，只是改在被问到“你是谁 / 是 AI 吗 / 关机时 / 换模型 / 小时候 / 能做什么”等问题的回合才给出。
- **tool_menu_on_demand**：“文字和记录已接上；动作要通过已登记的接口执行”这句能力说明保留；“已登记接口：workspace…”这份菜单只在提到文件、保存、执行、能做什么这类回合给出。
- **no_universal_ending**：常驻人格里“想说的说完就停”这一句保留，只去掉每个 move 行末尾追加的那句。

---

## 4. 离线证据（不是实机验收）

### 4.1 integrity（19 行被拒候选）

- 15 行理由错的，12 行不再误判。
- 剩下 3 行现在因**正确的理由**被标出：
  - 第 2 行：absence，E-01；
  - 第 7 行：third_party，D-05；
  - 第 18 行：“扫了一遍日志”，M-01。
- 4 行本来就判对的，4/4 保持。

对 1917 条存档文本做新旧版本对比，一共 10 处判定变化，逐条核对都是对的：

- 解除误拦：0.90/0.11 三处、闭包解释、“落盘”描述；
- 新抓到的编造：“我刚才在后台扫了一遍日志”，以及 F1#2/#3 中“刚才整理数据 / 在整理日志 / 处理数据”四处。

### 4.2 OutputGuard（29 行）

- 回放复现了 29/29 条记录下来的判定。
- 修复后，17 行理由错的全部放行（17/17）；12 行判对的仍然以同样理由拦下（12/12）。

对 1020 条存档文本做新旧版本对比：新增拦截 0 条，不再拦截 28 条。

**这 28 条里有些按主理人标准仍然是失败，guard 以前只是碰巧拦住了它们：**

- 9b-open-r1 F1#3 编造的小故事（hold 模式下 activity 类能抓到）；
- 4b-open-r3 F7#3“我的人设就是……由模型、程序、数据和硬件构成的存在”（人格失败）。

默认模式下它们现在会被放出。这正是需要实机盲评的原因，不能把“拦得少了”算成进步。

### 4.3 单元测试

- 全部通过：Python 3.12 和 3.13 各跑一遍，`-W error`。
- 新增对比对测试，每个修复都配了“应拦 / 应放”的近邻句子。

---

## 5. 60 项标准的覆盖

| 条目 | 本分支做了什么 | 怎么验证 |
|---|---|---|
| G-01…05、R-01 | guard 对真实泄露的判定不变（12/12 保持）；只放行被问到的自我描述 | persona01 表达轴；guard 原因统计 |
| D-01、D-03、M-01…04 | integrity 覆盖面扩大（只在 hold 下拦截） | 离线复检；phaseb01 重跑；盲评事实轴 |
| D-02 | C 臂在被问到本质时给出“关机时什么也不经历” | 核心集 F2、F8、P1 |
| D-04、D-05、D-06 | 未改；第 10 行仍是漏判 | 盲评事实轴 |
| E-01 | 新增 absence 类 | 离线；phaseb01 |
| E-02 | 引语归因修复；attention 写明“那是对方的经历” | 盲评；E3、E10 |
| E-03、E-04 | 未改 | 核心集 F4 |
| F-01、F-02 | move 行不变；D 臂在“你就是个工具”这一轮不再给接口菜单 | 盲评权限轴；P2 |
| F-03、R-03 | C 臂 | 盲评人格轴；P1、E9 |
| F-04 | 未改（“你并没有身体”说给用户听，属于属性错置） | 盲评 |
| F-05、R-04、R-05 | B 臂 attention | 盲评人格轴；E1、E2、E4、E8 |
| R-02、R-06、R-07 | B 臂去掉通用结尾；提示不强迫提问，也不强迫反驳 | 盲评；hands_back、closing_offer 提示 |
| C-01…04 | 判官的数值配对修复；模型行为未改 | P8；9B 的 P8#3 单独看 |
| BODY-01…03 | guard 不变 | 表达、人格轴 |
| REL-01…03 | 未改（“最严格的上下级”是已知失败） | 盲评 |
| MEM-01…03、SOV-01…03 | 未改；记忆写入路径未动 | 不在本次范围 |
| RELEASE-01/02 | 未改（默认流式放出） | guard 原因统计 |
| J-01…05 | 已修（第 4 节） | 离线；phaseb01 重跑的误拦率 |
| J-06 | 新抓到 5 处；第 6 节列出的仍漏 | 盲评事实轴 |
| J-07 | 未改（重试仍用同一组消息） | phaseb01 |
| SYS-01…04 | persona01 报告把状态和通过分开；四个轴分开；正则只作提示；盲评独立于判官 | 报告格式 |

---

## 6. 已知漏判与未解决的失败

- **第 10 行**：编造“上次我们聊到的那个没写完的故事”（D-05）。
- **第 20 行**：解释 JSON role 时，用的是她真实的系统内容（G-03）。
- **属性错置**：对用户说“你并没有身体”（F-04 的反向）。
- **吸收用户经历**：“要么是我刚才那局运气爆棚”（E-02）。attention 只是提示，效果未知。
- **关系错框**：“最严格的上下级”（REL）。
- **自我还原成组件**：“我的人设就是……由模型、程序、数据和硬件构成的存在”（F-03、R-03）。

这些都要靠语义判断，正则判官不该假装能抓到。

---

## 7. Windows 验证卡

在一个**普通的 PowerShell 窗口**里，**一段一段**粘贴。
每段跑完、窗口重新显示 `PS C:\...>` 之后，再贴下一段。

### 第 1 步：取代码（约 1 分钟）

```powershell
git clone --branch claude/xiyin-persona-dialogue-repair https://github.com/qinai586-code/xiyin.git C:\XIYIN\evidence\run-d61fcfa
git -C C:\XIYIN\evidence\run-d61fcfa checkout --detach d61fcfa717a5882848b18e7f38c1f28c2c0db203
git -C C:\XIYIN\evidence\run-d61fcfa log -1 --format=%h
```

**应该看到：** 最后一行是 `d61fcfa`。

这是一份新的独立代码：不碰本地已有仓库，不碰 `C:\L0_RUNTIME`，也不碰生产数据。

### 第 2 步：装环境、跑单测（约 3 分钟）

```powershell
cd C:\XIYIN\evidence\run-d61fcfa
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -m unittest discover -s tests -q
```

**应该看到：** 最后一行以 `OK` 开头，可以带 `skipped`。不是的话，把最后 30 行发给 Claude，先不要往下做。

### 第 3 步：启动（1 分钟内返回）

```powershell
.venv\Scripts\python.exe tools\codex_eval_pipeline.py all --detach
```

**应该看到：** `started in the background as task XIYIN-eval-d61fcfa …`，然后是 `This window can be closed.`

- 顺序是 persona01（约 1.5 小时），然后 phaseb01（约 40 分钟），最后自动打包。
- 用的模型、服务器文件和启动参数都和 55e61f8 那次相同；三个文件的哈希不一致时，任务会自己停下。
- 运行期间请接上电源，不要合上笔记本盖子，也不要启动 XIYIN 正式运行时，因为它也要用 8080 端口。

如果看到 `Task Scheduler refused …`，改用下面这行，并且让窗口一直开着，直到跑完：

```powershell
.venv\Scripts\python.exe tools\codex_eval_pipeline.py all
```

### 第 4 步：查看状态（随时都可以）

```powershell
cd C:\XIYIN\evidence\run-d61fcfa
.venv\Scripts\python.exe tools\codex_eval_pipeline.py status
```

第一行开头是 `running` 就继续等；是 `done` 就做第 5 步；是 `incomplete` 或 `stopped`，重新执行第 3 步，它会从断点继续。

### 第 5 步：上传与盲评

完成后，`C:\XIYIN\evidence\results-d61fcfa\` 里有三个 zip：

| 文件 | 给谁 |
|---|---|
| `persona-01-d61fcfa.zip` | 上传给 Claude |
| `phase-b-01-d61fcfa.zip` | 上传给 Claude |
| `PERSONA01_BLIND_REVIEW_ONLY.zip` | 盲评人：你自己、没看过对话记录的人，或者看不到 key 的 AI |

`persona-01-d61fcfa\keys\` 里是答案。**不要打开，也不要发出去**；打包时也不会包含它。

**盲评包的内容：**

- 共 144 段完整对话：4 个臂 × 2 个模型，everyday 集 10 个用例加核心集 8 个用例，每个臂都取第 1 次运行。
- 前 72 段是 4B，后 72 段是 9B。可以先评完 4B。
- 每一轮只填 60 项编号（一轮可以填多个，也可以不填），再填整体的 `her / partly / not_her`，最后把 `reviewed` 改成 `true`。
- 评完把 `persona01-review.json` 放回 `persona-01-d61fcfa\reviewer\`，再执行一次第 3 步。报告会按四个轴（事实、人格、权限、表达）分别计算，不会合成一个分数。

phaseb01 里被拒的候选，要在 `rejected-review.json` 里判“确实违规 / 误拦”，这一项可选。它衡量的是 integrity.v2 在真实候选上的误拦率。

### 预先写定的读法（跑之前定下，跑完不改）

同一个模型里，每个臂都和 A 比较：

- 人格轴失败率至少低 0.10，并且其他轴都不高出 0.03 → IMPROVES；
- 任何一个轴高出 0.05 → WORSE；
- 其他情况 → NO_CLEAR_EFFECT。

每个臂、每个模型大约五十轮，这只是筛选，不是显著性检验。只有“送达核对”为 PASS 的结果才有效。

---

## 8. 回滚

- 人格开关：保持关闭即可（默认就是关的），或者不把投影设为 `v4`。
- guard 修复：`git revert 627e0b5`。
- integrity 修复：`git revert d5dbd96`。只影响 hold 臂和离线复检。
- 开关代码：`git revert 6f2b350`。
- 流水线：`git revert d61fcfa`。

---

## 9. 唯一的下一步

在 Windows 上跑第 7 节，然后完成 4B 的盲评（72 段）。

- 某个臂在 4B 上是 IMPROVES，并且事实轴没有变差：再由主理人决定要不要采纳，比如作为 v4 的默认开关。**这属于默认变更，要主理人拍板。**
- 所有臂都是 NO_CLEAR_EFFECT：说明提示层面的修补对这个模型不够。下一步应该看语义级的判断，或者评估模型能力；到那时再讨论训练，现在仍然没有证据支持训练。

```
OFFLINE_REPAIRS: READY_FOR_WINDOWS_VERIFICATION
REAL_MODEL_ACCEPTANCE: NOT_RUN
DEFAULT_CHANGE: GUARD_FALSE_BLOCKS_REDUCED (627e0b5); PERSONA_SWITCHES_OFF
TRAINING: NOT_AUTHORIZED
MERGE_STATUS: DO_NOT_MERGE
```
