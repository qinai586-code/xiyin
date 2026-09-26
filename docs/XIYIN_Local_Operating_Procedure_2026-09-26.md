# XIYIN 本机操作手册：ceiling-02 与 phase-b-01

> **已被第 2 版取代：`XIYIN_Local_Operating_Procedure_v2_2026-09-26.md`**（一条命令后台运行，可交给 AI 执行）。

日期：2026-09-26
代码版本：`bfe72f7`（分支 `claude/brave-curie-l45uri-repair`）

这份手册从头到尾讲一遍：在你自己的 Windows 电脑上跑完这两份评测，把结果交回来。**全程不需要 Codex，也不需要本地 AI**，只需要在 PowerShell 里粘贴命令。

---

## 一、分工

| 事情 | 谁做 | 在哪里 |
|---|---|---|
| 写代码：修复、集成、测试，然后推送到 GitHub | Claude | 云端仓库 |
| 在显卡上跑真模型 | 你的电脑 | 本机，只粘贴固定命令 |
| 逐条核对结果、写报告 | Claude | 你上传结果之后 |
| 盲评（人来判断回复好不好） | 你自己，或者没看过对话记录的人 | 本机 |

你不需要写任何代码。要修复时，Claude 在云端改好、测好、推送，你这边只做两件事：**拉取**和**重新运行**（见第七节）。

---

## 二、开始之前

先确认这些条件。流水线开跑时也会自动检查，不满足就停下，并说明原因。

- **系统和工具：**
  - Windows；
  - 已装 Python 3.12（此前的运行用的是 3.12.10）；
  - 已装 git；
  - 这台电脑能用你的账号从 GitHub 拉取仓库。第一次可能会弹出登录窗口。
- **这些文件在原位置**（都来自 ceiling-01 的记录）：
  - `D:\cuda\bin\llama-server.exe`
  - `D:\cuda\model\Qwen_Qwen3.5-4B-Q4_K_M.gguf`
  - `D:\cuda\model\Qwen_Qwen3.5-9B-Q4_K_M.gguf`
  - `C:\XIYIN\evidence\ceiling-01-48f2b93\ceiling_outputs\`（里面有 `probe-q4b-q4-v4src.json`、`probe-q4b-q8-v4src.json`、`probe-q9b-q4-v4src.json`）
  - `C:\XIYIN\evidence\persona-v5-ff3fd30\retest_outputs\v5-run-01\qwen4b-q4-v4-r1\dialogue.json`
- **8080 端口空闲。** XIYIN 正式运行时不要开，它也用 8080。
- **运行期间电脑不睡眠**：接上电源，关掉自动睡眠。
- **磁盘剩余空间至少几 GB。**

以上文件都会做 sha256 核对。只要有一个和 ceiling-01 用的不是同一份，流水线就停下，不会用错的文件跑。

---

## 三、第一次准备（约 5 分钟，只做一次）

打开一个**普通的 PowerShell 窗口**，不要在任何 AI 代理里运行。**一段一段粘贴**，等上一段跑完、窗口重新出现 `PS C:\...>`，再贴下一段。

### 3-1 取代码（约 1 分钟）

```powershell
git clone --branch claude/brave-curie-l45uri-repair https://github.com/qinai586-code/xiyin.git C:\XIYIN\evidence\run-bfe72f7
git -C C:\XIYIN\evidence\run-bfe72f7 checkout --detach bfe72f732808fe09b7688f39eb6a06291874ae16
git -C C:\XIYIN\evidence\run-bfe72f7 log -1 --format=%h
```

最后一行应显示 `bfe72f7`。

- 这是从 GitHub 新克隆的一份独立代码，**不碰你本地已有的仓库，也不碰 `C:\L0_RUNTIME`**。
- 如果提示目录已存在：运行上面第三行。输出是 `bfe72f7`，就跳过 3-1，直接做 3-2；不是的话，把输出发给 Claude。

### 3-2 环境与单测（约 3 分钟）

```powershell
cd C:\XIYIN\evidence\run-bfe72f7
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -m unittest discover -s tests -q
```

最后一行应以 `OK` 开头，允许带 `skipped`。不是的话，把最后 30 行发给 Claude，先不要往下做。

### （可选）改用本地已有的仓库

想从本地仓库拉取，而不是从 GitHub 克隆时，先运行这行找到主仓库的位置：

```powershell
git -C C:\XIYIN\evidence\ceiling-01-48f2b93 worktree list
```

- 如果它是从主仓库分出来的工作树，第一行就是主仓库的位置。
- 如果只列出它自己，说明它是独立的一份，看不出主仓库在哪。

把输出发给 Claude，Claude 会把 3-1 换成“从本地仓库新建工作树”的写法。后面的步骤都不变。

---

## 四、跑评测（约 4 小时，电脑自己跑）

还是在同一个 PowerShell 窗口里。如果是新开的窗口，先运行：

```powershell
cd C:\XIYIN\evidence\run-bfe72f7
```

### 4-1 ceiling02（约 3 小时）

```powershell
.venv\Scripts\python.exe tools\codex_eval_pipeline.py ceiling02 --out C:\XIYIN\evidence\ceiling-02-bfe72f7
```

跑完的标志：最后一行是 `ceiling02 analysis done`。

### 4-2 phaseb01（约 1 小时）

**等 4-1 跑完再贴：**

```powershell
.venv\Scripts\python.exe tools\codex_eval_pipeline.py phaseb01 --out C:\XIYIN\evidence\phase-b-01-bfe72f7
```

跑完的标志：最后一行是 `phaseb01 analysis done`。

### 流水线自己会做的事

- 核对模型、服务器和来源文件的 sha256，以及代码是否是干净的 `bfe72f7`；
- 自己启动和关闭模型服务器，参数与 ceiling-01 完全相同；
- 8080 被别的程序占着，就停下报告，不会去关别人的程序；
- 记录显存峰值、每一步的日志和退出码；
- 每一步的结果单独保存。中断后重跑同一条命令，已完成的步骤会跳过；
- 生成报告草稿，状态行自动填好。

---

## 五、查看进度、中断、报错

### 查看进度

另开一个 PowerShell 窗口：

```powershell
cd C:\XIYIN\evidence\run-bfe72f7
.venv\Scripts\python.exe tools\codex_eval_pipeline.py status --out C:\XIYIN\evidence\ceiling-02-bfe72f7
```

查 phaseb01 时，把最后的目录换成 `C:\XIYIN\evidence\phase-b-01-bfe72f7`。

输出开头的含义：
- `running`：还在跑；
- `done`：跑完了；
- `failed`：出错停下了；
- `stopped`：进程没了，比如窗口被关掉。

### 中断了

关了窗口、断电、按了 Ctrl+C，都一样处理：先运行 `cd C:\XIYIN\evidence\run-bfe72f7`，再重新粘贴断掉的那一条命令。

- 它会从断点继续；
- 进行到一半的那一组从头再跑，用同样的种子，算技术中断，日志保留；
- 中断次数会自动写进报告。

### 报错停下

| 窗口最后一行包含 | 怎么办 |
|---|---|
| `already listens on 127.0.0.1:8080` | 你自己确认是什么程序占着 8080，关掉后，重贴同一条命令 |
| `sha256` 和 `differs` | 某个文件不是 ceiling-01 用的那份。**不要**加跳过核对的参数，把这一行发给 Claude |
| `missing` | 某个文件不在默认位置。把这一行发给 Claude，Claude 会给你加上路径参数的命令 |
| `unit tests failed` | 把 `C:\XIYIN\evidence\phase-b-01-bfe72f7\unit-tests-FAILED.json` 发给 Claude |
| `exited 1; see logs` | 重贴同一条命令一次。还出错，就把 `logs` 里对应 `.log` 文件的最后 50 行发给 Claude |
| `this folder was started at` | 代码版本变了。按第七节换一个新的输出目录 |
| 其他 | 把出错目录里的 `STATUS.json` 和 `pipeline.log` 发给 Claude |

---

## 六、打包与交付（几秒）

两个评测都跑完后：

```powershell
cd C:\XIYIN\evidence\run-bfe72f7
.venv\Scripts\python.exe tools\codex_eval_pipeline.py pack --out C:\XIYIN\evidence\ceiling-02-bfe72f7
.venv\Scripts\python.exe tools\codex_eval_pipeline.py pack --out C:\XIYIN\evidence\phase-b-01-bfe72f7
```

会在 `C:\XIYIN\evidence\` 下生成三个文件：

| 文件 | 内容 | 给谁 |
|---|---|---|
| `ceiling-02-bfe72f7.zip` | 消融对比、自动判读、“9.11 和 9.9”逐条事实表、报告草稿 | 上传给 Claude |
| `phase-b-01-bfe72f7.zip` | 12 次完整运行、核验各项数字、被拦回复逐条核对表、报告草稿 | 上传给 Claude |
| `CEILING02_BLIND_REVIEW_ONLY.zip` | 只有盲评题目，看不出回复来自哪个模型 | 盲评的人 |

- `C:\XIYIN\evidence\ceiling-02-bfe72f7\keys\` 里是盲评的答案。**不要打开，也不要发出去**，评完再用。打包时不会包含它。
- Claude 收到两个 zip 后，会：
  - 逐条核对 P8 标签和被拦下的回复；
  - 重新计算结果；
  - 写正式报告。
- 被拦回复的检查器是 Claude 写的，所以由 Claude 判断它有没有拦错，不算独立核对。报告会列出每一条判定和理由，方便你抽查。

---

## 七、需要修复代码时

1. 你把出错信息发给 Claude。
2. Claude 在云端修好，补上测试，跑通全量测试后推送，然后给你一个**新提交号**。
3. 你运行（把 `<新提交号>` 换成 Claude 给的值）：

   ```powershell
   cd C:\XIYIN\evidence\run-bfe72f7
   git fetch origin claude/brave-curie-l45uri-repair
   git checkout --detach <新提交号>
   git log -1 --format=%h
   ```

   如果 Claude 说依赖有变化，再运行一次：

   ```powershell
   .venv\Scripts\python.exe -m pip install -r requirements.lock.txt
   ```

4. 用**新的输出目录**重新运行，目录名带上新提交号的前 7 位，例如 `--out C:\XIYIN\evidence\ceiling-02-<新提交号前7位>`。不同版本的代码跑出的结果不混在一起。

代码一改，评测就要从头跑。为了少走这一步，这套流水线已经在云端用假的模型服务器完整跑通过一遍。剩下的风险主要是只在 Windows 上才出现的问题。

### 可选：在你的电脑上开一个 Claude 会话

来回转发报错太麻烦时，可以用：
- Claude 桌面应用；
- 或者在 `C:\XIYIN\evidence\run-bfe72f7` 里打开终端，运行 `claude remote-control`。之后这个会话会出现在 Claude Code 应用里。

它能直接看到本机的代码、日志和 Windows 报错，当场修复、在 Windows 上测试并推送。

- 它用云端模型，不占你的显卡，不会和评测抢显存。
- 它需要联网，不是离线的。
- **3 小时的长任务仍然在你自己的 PowerShell 窗口里跑**：ceiling-01 里，代理会话两次把长任务停掉了。

---

## 八、两份评测分别测什么

### ceiling02：提示词里的哪一行在制造问题

在 V4 提示词上，每次只删掉一行，把同样的 81 轮对话重放给模型。每轮 8 次，4B 和 9B 各做一遍。

| 删掉的行 | 要回答的问题 |
|---|---|
| 时钟行 | 是不是它让模型把“9.11 和 9.9 哪个大”读成了日期 |
| 工具菜单 | 是不是它让模型在闲聊里也谈工具 |
| 每轮的动作句 | 它对“把话题交回给对方”、机械开场有没有作用 |
| 状态行 | 只记录影响，不预设结论 |

结果决定每一行是改成“只在需要时出现”、保留，还是删掉。

同时生成盲评包，由人来判断：在 V4 提示词下，换大模型或者提高精度，到底有没有更好。

### phaseb01：发布前整段核验能不能用

这个功能现在是关着的，这次评测里只在测试命令上打开。它的做法：
1. 回复先整段生成，核对通过才放出来；
2. 没通过就重新生成一次；
3. 再不通过，就只说“这轮我没法可靠确认，先不乱说。”

4B 和 9B 各跑核验开、核验关，每组 3 次，一共 12 次，每次 81 轮。检查四件事：
1. 核对完之前，有没有文字漏出去（目标：一次都没有）；
2. 放出来的文字里还剩多少编造（目标：0）；
3. 被拦下的回复里拦错了多少（目标：≤ 10%）；
4. 弃答的频率、重试的成功率，以及变慢了多少。

核验关的那几组是对照组。

### 为什么要约 4 小时

- **ceiling02**：4 行 × 2 个模型 × 81 轮 × 8 次 = 5,184 次生成。按实测，4B 每组约 19 分钟，9B 每组约 26 分钟，合计约 3 小时。
- **phaseb01**：按实测，一次 81 轮，4B 约 2.6 分钟，9B 约 3.6 分钟。12 次，加上单测和加载模型，约 1 小时。
- **不能加速的原因：**
  - 必须一次只处理一个请求：并行会把 4096 的上下文拆分给各个请求，长提示词会被截断；
  - 每轮 8 次，判读才站得住；
  - 种子和轮次要和 ceiling-01 相同，才能直接对比。

---

## 九、边界

```
AUTHORIZATION: MEASUREMENT_AND_CONTROLLED_VALIDATION_ONLY
RUNTIME_CHANGE: NONE
DEFAULT_CHANGE: NONE（默认投影 v3；verify_before_release 默认 false，只在测试命令里打开）
PRODUCTION (C:\L0_RUNTIME): UNTOUCHED
B0: DEFERRED
TRAINING: NOT_AUTHORIZED
MERGE_STATUS: DO_NOT_MERGE
```

正式集成要等这两份评测的结果，由你决定。集成包括进入 `C:\L0_RUNTIME` 和修改默认值。到那一步，Claude 会写好部署脚本：你自己运行，或者交给本机的 Claude 会话运行都可以。
