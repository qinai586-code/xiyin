# XIYIN 本机操作手册（第 2 版）：ceiling-02 与 phase-b-01

日期：2026-09-26
代码版本：`55e61f8`（分支 `claude/brave-curie-l45uri-repair`）

**这一版取代第 1 版**（`XIYIN_Local_Operating_Procedure_2026-09-26.md`），改动如下：
- 两份评测和打包合成**一条启动命令**；
- 启动后在**后台**运行：关掉窗口、AI 会话结束，都不会中断它；运行期间电脑不会自动睡眠；
- 所有目录名按代码版本**自动生成**，不用手打路径；
- 增加了“交给 AI 执行”的一段指令（第三节），GLM、Codex 或本机的 Claude 会话都能用。

---

## 一、整体流程

| 步骤 | 谁做 | 耗时 |
|---|---|---|
| 1. 取代码 | 你，或者 AI | 1 分钟 |
| 2. 装环境、跑单测 | 你，或者 AI | 3 分钟 |
| 3. 启动评测（后台） | 你，或者 AI | 1 分钟 |
| 4. 等待 | 电脑自己跑 | 约 4 小时 |
| 5. 查看状态；完成后上传两个 zip | 你 | 1 分钟 |
| 6. 逐条核对、写报告 | Claude | — |

你可以自己按第二节粘贴命令，也可以把第三节整段交给任何一个能在你电脑上运行命令的 AI。两种方式做的事完全一样。

---

## 二、自己操作

打开一个**普通的 PowerShell 窗口**，**一段一段**粘贴：每段跑完、窗口重新显示 `PS C:\...>`，再贴下一段。

### 第 1 步：取代码（约 1 分钟，可能弹出 GitHub 登录）

```powershell
git clone --branch claude/brave-curie-l45uri-repair https://github.com/qinai586-code/xiyin.git C:\XIYIN\evidence\run-55e61f8
git -C C:\XIYIN\evidence\run-55e61f8 checkout --detach 55e61f8a2b70617b4774f49889def084c495d862
git -C C:\XIYIN\evidence\run-55e61f8 log -1 --format=%h
```

**应该看到：** 最后一行是 `55e61f8`。

这是一份独立的新代码，**不碰你本地已有的仓库，也不碰 `C:\L0_RUNTIME`**。

### 第 2 步：装环境、跑单测（约 3 分钟）

```powershell
cd C:\XIYIN\evidence\run-55e61f8
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -m unittest discover -s tests -q
```

**应该看到：** 最后一行以 `OK` 开头，允许带 `skipped`。
不是的话，把最后 30 行发给 Claude，先不要往下做。

### 第 3 步：启动（1 分钟内返回）

```powershell
.venv\Scripts\python.exe tools\codex_eval_pipeline.py all --detach
```

**应该看到：** `started in the background as task XIYIN-eval-55e61f8 …`，接着是 `This window can be closed.`

看到这两行，评测就已经在后台跑了，**这个窗口可以关掉**。

- 它会按顺序做完 ceiling02（约 3 小时）、phaseb01（约 1 小时），然后自动打包。
- 运行期间电脑不会自动睡眠。但请**接上电源，别合上笔记本盖子**，也不要关机或重启。
- 不要启动 XIYIN 正式运行时，它也要用 8080 端口。

如果看到的是 `Task Scheduler refused …`：说明这台电脑不允许创建计划任务。改用下面这行，并且**让窗口一直开着**，直到跑完：

```powershell
.venv\Scripts\python.exe tools\codex_eval_pipeline.py all
```

### 第 4 步：查看状态（随时都可以）

新开一个 PowerShell 窗口：

```powershell
cd C:\XIYIN\evidence\run-55e61f8
.venv\Scripts\python.exe tools\codex_eval_pipeline.py status
```

第一行开头的词代表总体状态：

| 开头的词 | 意思 | 你要做什么 |
|---|---|---|
| `running` | 正在跑。下面两行分别是两份评测进行到哪一步 | 等 |
| `done` | 全部完成，下面列出了 zip 的位置 | 做第 5 步 |
| `incomplete` | 有一份出错停下了，下面那一行写着原因 | 看第五节 |
| `stopped` | 进程没了，比如关机、断电 | 重新做第 3 步，会从断点继续 |
| `NOT_STARTED` | 还没开始 | 做第 3 步 |

### 第 5 步：上传

完成后，打开 `C:\XIYIN\evidence\results-55e61f8\`，里面有三个 zip：

| 文件 | 给谁 |
|---|---|
| `ceiling-02-55e61f8.zip` | 上传给 Claude |
| `phase-b-01-55e61f8.zip` | 上传给 Claude |
| `CEILING02_BLIND_REVIEW_ONLY.zip` | 盲评的人：你自己，或者没看过对话记录的人 |

`ceiling-02-55e61f8\keys\` 里是盲评的答案。**不要打开，也不要发出去**，打包时也不会包含它。

### 要停下来的话

```powershell
cd C:\XIYIN\evidence\run-55e61f8
.venv\Scripts\python.exe tools\codex_eval_pipeline.py stop
```

它会停掉评测，以及评测自己启动的模型服务器。想继续时，再做一次第 3 步，已经完成的部分不会重跑。

---

## 三、交给 AI 执行（GLM、Codex 或本机的 Claude 会话）

任何一个能在你电脑上运行 PowerShell 命令的 AI 都可以，模型强弱关系不大：它只负责照着粘贴、核对输出，**不需要也不允许它改东西**。评测是由 Windows 计划任务在后台运行的，AI 会话结束也不会中断它。

### 3-1 启动：把下面整段发给它

```text
你是本机执行者。只按顺序做下面 3 步，不做别的。

规则：
- 不修改任何文件、代码或配置；不修复任何错误。
- 不停止任何进程；不碰 C:\L0_RUNTIME；不打开任何 keys 目录。
- 不启动子代理，不并行开多个代理。
- 每一步运行完，把输出和“应该看到”对比；不一致就立刻停止，原样报告命令和最后 30 行输出。

第 1 步（可能弹出 GitHub 登录，等我登录完）：
git clone --branch claude/brave-curie-l45uri-repair https://github.com/qinai586-code/xiyin.git C:\XIYIN\evidence\run-55e61f8
git -C C:\XIYIN\evidence\run-55e61f8 checkout --detach 55e61f8a2b70617b4774f49889def084c495d862
git -C C:\XIYIN\evidence\run-55e61f8 log -1 --format=%h
应该看到：最后一行是 55e61f8。
（如果提示目录已存在：只运行上面第三行；输出是 55e61f8 就继续第 2 步，否则停止并报告。）

第 2 步（在 C:\XIYIN\evidence\run-55e61f8 目录里）：
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -m unittest discover -s tests -q
应该看到：最后一行以 OK 开头（允许带 skipped）。

第 3 步（同一目录）：
.venv\Scripts\python.exe tools\codex_eval_pipeline.py all --detach
应该看到：started in the background as task XIYIN-eval-55e61f8，以及 This window can be closed.
如果看到 Task Scheduler refused：停止，原样报告，不要改用别的方式。

完成后运行一次：
.venv\Scripts\python.exe tools\codex_eval_pipeline.py status
把它的输出原文回复给我，然后结束。不要等待评测跑完，不要轮询。
```

### 3-2 查进度：几小时后，发给它（或者自己运行第 4 步）

```text
只做一件事：在 C:\XIYIN\evidence\run-55e61f8 目录里运行
.venv\Scripts\python.exe tools\codex_eval_pipeline.py status
把输出原文回复给我，然后结束。不要做任何别的事。
```

---

## 四、开始之前要满足的条件

流水线启动时会自动检查这些条件，不满足就停下，在 `status` 里写明原因。

- **软件与账号：**
  - Windows；
  - 已装 Python 3.12（此前运行用的是 3.12.10）和 git；
  - 这台电脑能用你的 GitHub 账号拉取仓库。
- **这些文件在原位置**，每个都会核对 sha256，必须是 ceiling-01 用的同一份：
  - `D:\cuda\bin\llama-server.exe`
  - `D:\cuda\model\Qwen_Qwen3.5-4B-Q4_K_M.gguf`
  - `D:\cuda\model\Qwen_Qwen3.5-9B-Q4_K_M.gguf`
  - `C:\XIYIN\evidence\ceiling-01-48f2b93\ceiling_outputs\` 下的 `probe-q4b-q4-v4src.json`、`probe-q4b-q8-v4src.json`、`probe-q9b-q4-v4src.json`
  - `C:\XIYIN\evidence\persona-v5-ff3fd30\retest_outputs\v5-run-01\qwen4b-q4-v4-r1\dialogue.json`
- **8080 端口空闲**；磁盘至少剩几 GB。

---

## 五、`status` 显示出错时

找 `status` 里写着 `error:` 的那一行：

| error 后面的内容包含 | 怎么办 |
|---|---|
| `already listens on 127.0.0.1:8080` | 你自己确认是什么程序占着 8080，关掉它，然后重做第 3 步 |
| `sha256` 和 `differs` | 某个文件不是 ceiling-01 用的那份。把这一行发给 Claude，不要继续 |
| `missing` | 某个文件不在默认位置。把这一行发给 Claude，Claude 会给你带路径参数的启动命令 |
| `unit tests failed` | 把 `results-55e61f8\phase-b-01-55e61f8\unit-tests-FAILED.json` 发给 Claude |
| `exited 1; see logs` | 重做一次第 3 步。还出错，就把 `logs` 里对应 `.log` 文件的最后 50 行发给 Claude |
| 其他 | 把 `results-55e61f8` 里的 `ALL-STATUS.json`，以及出错那一份评测目录里的 `STATUS.json`、`pipeline.log` 发给 Claude |

其中一份评测出错，另一份仍会接着跑完并打包。

---

## 六、需要修复代码时

1. 你把出错信息发给 Claude。
2. Claude 在云端修好，补上测试，跑通全量测试后推送，然后给你一个新的提交号。
3. 你运行下面几行，把 `<新提交号>` 换成 Claude 给的值：

   ```powershell
   cd C:\XIYIN\evidence\run-55e61f8
   git fetch origin claude/brave-curie-l45uri-repair
   git checkout --detach <新提交号>
   .venv\Scripts\python.exe tools\codex_eval_pipeline.py all --detach
   ```

结果目录名按代码版本自动生成，会自动变成 `results-<新提交号前7位>`，不同版本的结果不会混在一起。代码改了，评测也要从头跑。

---

## 七、两份评测测什么，为什么要约 4 小时

- **ceiling02（约 3 小时）：** 在 V4 提示词上，每次只删掉一行，看问题是变少还是变多。4 行分别是：
  - 时钟行；
  - 工具菜单；
  - 每轮的动作句；
  - 状态行。

  81 轮对话 × 每轮 8 次 × 4 行 × 2 个模型（4B、9B），一共 5,184 次生成。同时生成盲评包：由人来判断，在 V4 提示词下换大模型或提高精度，到底有没有更好。
- **phaseb01（约 1 小时）：** 验证“发布前整段核验”：回复先整段生成，核对通过才放出，否则重新生成一次，再不行就说“这轮我没法可靠确认，先不乱说。”4B 和 9B 各跑核验开、核验关，每组 3 次，一共 12 次完整运行。检查四件事：
  - 有没有文字在核对完之前漏出去；
  - 放出来的文字里还剩多少编造；
  - 被拦的回复里拦错了多少；
  - 弃答率和延迟。
- **为什么不能更快：**
  - 一次只能处理一个请求，否则每个请求分到的上下文会变短，长提示词会被截断；
  - 每轮 8 次，判读才站得住；
  - 种子和轮次都要与 ceiling-01 相同，才能直接对比。

检查被拦回复的核验器是 Claude 写的，所以由 Claude 判断它有没有拦错，不算独立核对。报告会列出每一条判定和理由，方便你抽查。

---

## 八、边界

```
AUTHORIZATION: MEASUREMENT_AND_CONTROLLED_VALIDATION_ONLY
RUNTIME_CHANGE: NONE
DEFAULT_CHANGE: NONE（默认投影 v3；verify_before_release 默认 false，只在测试命令里打开）
PRODUCTION (C:\L0_RUNTIME): UNTOUCHED
B0: DEFERRED
TRAINING: NOT_AUTHORIZED
MERGE_STATUS: DO_NOT_MERGE
```
