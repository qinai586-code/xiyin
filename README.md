# XIYIN — Living Runtime

栖音现在使用统一运行核心：人物与状态、经历记忆、目标调度、身体动作、语音打断、睡眠、成长和维护共用同一套运行接口。完整对应关系见 [ARCHITECTURE.md](ARCHITECTURE.md)，上游使用范围见 [OPEN_SOURCE.md](OPEN_SOURCE.md)。

这次重构交付的是**可进行无模型整体验收的代码**。真实模型自然度、麦克风/扬声器延迟、游戏技能和训练收益仍需实机验证。未配置的身体后端会报告不可用。

## Windows: first run without a model

Python 3.12，当前普通 Windows 账户即可；不需要 `runas`、SJ_Run 密码、管理员权限或固定 C 盘路径。虚拟环境应在这台机器重建，不复制另一台电脑的 Python/venv。

```powershell
.\tools\windows.ps1 -Mode setup
.\tools\windows.ps1 -Mode test
.\tools\windows.ps1 -Mode verify
```

`verify` 从正式 `XIYINRuntime.open(model_enabled=False)` 进入，读取真实 Windows token，在全新临时目录执行记忆纠错、目标→文件操作→验证、策略采用/回退、睡眠唤醒、停止恢复、SQLite 备份恢复及重启连续性。结束删除自身临时测试目录；输出结果 JSON。**0 次模型请求，不触碰原人物数据，不点击真实窗口。** 失败返回非零退出码，不能用组件测试代替报告整体通过。

`test` 是无模型自动测试，包括合成 ASR/TTS/播放、HTTP 和桌面 API 替身；它们明确标注为测试输入，不能解释为真实模型/设备能力。

## Keep one runtime running

使用新数据根测试常驻服务：

```powershell
$XiyinData = Join-Path $env:TEMP ('XIYIN_DATA_' + [guid]::NewGuid().ToString('N'))
$XiyinWork = Join-Path $env:TEMP ('XIYIN_WORK_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $XiyinData,$XiyinWork | Out-Null
$env:XIYIN_DATA_ROOT = $XiyinData
.\tools\windows.ps1 -Mode init-data
.\.venv\Scripts\python.exe .\xiyin.py serve --no-model --workspace $XiyinWork
```

`serve` 接受本地 JSON-lines，保持一个事件循环。逐行输入，下一个指令不必等待前一个模型请求结束；stop 会优先处理。它没有开放网络端口。

```json
{"kind":"remember","payload":{"text":"我喜欢解谜游戏","kind":"preference"}}
{"kind":"plan","payload":{"objective":{"skill":"write_text","path":"note.txt","text":"栖音的第一条真实任务"}}}
{"kind":"status"}
{"kind":"sleep"}
{"kind":"wake"}
{"kind":"stop"}
{"kind":"resume"}
```

已排队目标会自行执行并保存操作回执，不需要每一步再发命令。当前规则 planner 只实例化已知读写技能；开放自然语言规划可通过 Director 的 planner 接口替换，不能以无模型验收声称已经拥有通用自主规划。空闲默认 300 秒整理入睡，可在 `config/runtime.toml` 设置；用户输入唤醒。未知外部动作不会盲目重试。

在另一个终端设置同一个 `XIYIN_DATA_ROOT` 后可运行 `xiyin.py stop` / `resume`。它们只操作独立停止标记，不抢正在运行的 SQLite lease；活跃生成和身体动作各自监视该标记。进程彻底挂死时仍需 OS/设备侧停止方式，不能把 Python watcher 宣称为独立硬件急停。

## Character and memory

`config/persona/character.seed.json` 保留主理人 v0.2 人物稿来源。种子是成长起点；当前有效人物记忆可覆盖倾向和私下/公开表达，不固定每轮台词或字数。`feedback` 可记录明确反馈，`grow` 根据同会话真实反馈提出并默认采用低风险人物字段，`rollback_growth` 恢复先前投影。稳定身份与权限不通过角色文本改写。

`remember` / `--supersedes` 执行真正的长期记忆写入和纠错；聊天生成只是对话事件，不能凭“我记住了”就宣布保存。上下文投影保留来源与原话，隐藏内部 ID/状态码，不全局删除括号、文学描写或正常标点。没有用输出清洗冒充自然度改善。

文字与语音共用输出前 `OutputGuard`：缓冲短段，检查正文内部标签、常见人设规则回显、内部标识和非创作场景动作旁白。动作旁白判定先剥离表情等装饰，再扫描所有括号组（含嵌套）与 `*强调*`，所以 `（😊歪头）`、`（歪了歪头）`、`（歪头(笑)）` 都会拦下，而 `（也就是周二）`、`(≧▽≦)` 照常通过。命中报 `OutputBlocked`，停止本轮并清语音队列；正常括号、数学、表情和明确创作按场景保留。失败原文只留在诊断账本，不进入正常历史、睡眠摘录或数据候选；不自动重试、不替换成固定台词。规则覆盖、局部字面引用例外与未解决的语义问题见 [ARCHITECTURE.md](ARCHITECTURE.md#shared-output-gate)。

回答依据取自账本而不是提示里的告诫：已验证的动作回执、本轮说法的记录核对、按主题的真实清单（包括「0 条」）都会进入模型请求，排序按「错答会变成假否认或假经历」的程度。每轮生成预算按请求分档并受上下文窗口与实测吞吐约束，简短与详细不再共用同一个 512 上限和同一个 60 秒超时；每轮记一条 `response_plan` 事件，含计划、实际字数与首 token 时间。详见 [ARCHITECTURE.md](ARCHITECTURE.md#grounding-disposition-and-generation-budgets)。

主理人提供的原始设计稿入档在 [docs/](docs/)，其中 v1.0 与 v1.1 各有一节 2026-09-20 修订记录，逐条列出被更晚记录取代的决定、依据，以及 Windows 报告六项失败的根因与修复。参考项目索引按其 §17 放在 [docs/research/](docs/research/)，不进运行路径；据其 §0 止损规则，本轮未新增任何第三方运行依赖。

```powershell
.\.venv\Scripts\python.exe .\xiyin.py remember '我喜欢解谜游戏' --kind preference
.\.venv\Scripts\python.exe .\xiyin.py backup 'D:\XIYIN_Backups\new-backup'
# 关闭使用同一数据根的 Runtime 后：
.\.venv\Scripts\python.exe .\xiyin.py restore 'D:\XIYIN_Backups\new-backup'
```

备份父目录须已存在、目标须为新目录。恢复校验数据根身份/校验和并在真实控制台确认一次；普通记忆、成长和已授权范围内的任务不需要多轮审核。旧文件记忆不自动导入，已有 `.xiyin_data` 和 `experience.sqlite3` 不会被重置。

## Body and voice

- 文件身体：显式 workspace 范围，真实写后读回验证，拒绝链接/越界；活动学习策略实际约束读写预算。
- Windows 桌面：`serve --window <HWND>` 显式绑定窗口；`--capture` 启用可选 Pillow 截图。失焦/停止/超时释放本系统持有的键；动作需独立可观察后置条件才能成功。未做现场设备验收。
- 游戏：`TypedGameAdapter` 接注册动作 schema 与真实 transport。接收到 action/result 不等于通关或动作完成；需要关联动作和新状态回执。
- 语音：主机调用 `runtime.attach_speech(SpeechController(asr=...,tts=...,sink=...))`，再向返回的 voice session 输入 PCM。输入和输出并行，确认打断取消同一 Runtime 的生成、TTS 和播放；旧 epoch 不再输出。ASR/TTS/实际播放/AEC 后端仍需安装配置，本轮没有偷偷下载模型。
- Avatar、直播平台等通过 Body 接口接入，尚无已配置实例；不会创建另一个角色作者或记忆库。

本地模型沿用固定 `config/model.toml`。需要真实对话时再使用 `tools/download_model.py`、`tools/start_model.ps1`，然后 `tools/windows.ps1 -Mode doctor -ProbeModel` / `-Mode chat`；这些命令会下载或调用模型，**不属于本轮无模型任务**。doctor 默认只读、未探测模型时退出码 2 表示尚未确认文字运行就绪。

## Upgrade and verification boundary

Lab 的策略检查、采用、实际执行变化和回退已经接通；Supervisor 的代码/模型清单登记只是选定候选，明确返回 `manifest_selection_only`，不声称已自动重启换版或训练了模型。数据导出为本地未审阅候选，默认不具备训练资格，不上传给 QINAI 或云服务。

CI 在 Ubuntu/Windows 跑无模型测试，Windows 另跑上述正式入口 `verify`。自然打断的声学 p95、噪声/回声、显存与自然对话长短适应必须单独实测。

旧 QINAI 代码与历史资料保存在 `legacy/qinai/`，已退出正式链路；原有部署备份未删除。源代码回退可用 Git 旧提交，数据库回退用对应有效备份；不要删除仓库或人物标记来“修复”。DeepSeek 应使用合并后的完整独立副本，重建 venv，原样执行 test/verify，报告真实失败，不更改人设、架构、账户、ACL 或断言来凑通过。
