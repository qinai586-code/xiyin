# XIYIN Foundation A

栖音第一步底座：一个本地模型入口、可成长的人物种子、一套持续经历与记忆，以及可取消的文字流。当前实现对应 Architecture v1.1 §16 的 **A 阶段**；语音身体、真实自然打断、电脑/游戏操作、睡眠调度与 Lab 仍属于后续 B–D。

## 当前行为

- `xiyin.py` 是统一命令入口，旧 `L2_CENTRAL/L2_MAIN/l2_central.py` 的 `submit_to_chain(text, source)` 接到同一核心。旧入口的人工逐字延迟、祈奈回退提示和待审队列不参与新链路。
- `xiyin_paths.py` 以自身定位代码；数据使用 `XIYIN_DATA_ROOT` 或 `config/paths.toml`，要求 `.xiyin_data` 标记。启动不会自动创建空记忆，显式 `init-data` 才初始化。
- `config/persona/character.seed.json` 来自主理人的 v0.2 人物稿。栖止、纹路追踪、轻微不服气、选择性偏爱是初始倾向，成长可以覆盖相应字段。
- `xiyin_runtime/provider.py` 调用本机 OpenAI-compatible SSE 接口。仅交付正文，过滤 reasoning/tool 数据；请求等待和读取都可取消，不重试已输出内容。关闭 HTTP 流不证明服务端 GPU 计算已结束。
- `experience.sqlite3` 保存原始事件、完成/中断状态和有证据的记忆版本。普通记录不走人工待审；明确纠错可替代旧条目；模拟和模型自述不能充当实际技能证据。
- 私密与公开上下文隔离，会话历史按 session 隔离；首版按单一主理人设计，多参与者共享会话尚未开放。中文检索为词面/双字匹配，尚非向量语义检索。
- 同一数据根只允许一个前台 Runtime 持有 OS 文件锁。退出/崩溃释放锁；不靠残留 PID 文件猜存活。

这里的 complete 表示完整生成了文字，不表示音频播放、人已听见或动作执行成功。第一步没有连接音频或设备，模型上下文也明确这一能力范围。

## Windows 上启动

要求 Python 3.12。执行位置可以变化，但运行账户和工作目录仍须符合已有 `config/deployment.toml`；本次没有放宽 SID/ACL。`tools/windows.ps1` 自动切换到仓库的 `L2_CENTRAL` 后运行。已有机器配置若与实际位置不同，doctor 会明确报告，不自动改身份或目录授权。

1. 安装隔离依赖（不以管理员权限运行模型）：

   ```powershell
   .\tools\windows.ps1 -Mode setup
   .\tools\windows.ps1 -Mode doctor
   ```

   doctor 默认不联网、不写数据。未初始化、未核对 Windows 身份或未探测模型时 `ready_for_text_runtime=false`，退出码 2 是未就绪，不是通过。

2. 在已注册的运行身份下初始化数据。新空数据根用：

   ```powershell
   .\tools\windows.ps1 -Mode init-data
   ```

   如果已有 `L1_MEMORY` 内容，先备份，再显式使用 `-AdoptExisting`。此操作只登记该数据根，不把旧 `passed/wait_check` 自动导入栖音的新事实库。已存在有效标记则复用，绝不生成新身份覆盖它。外部 `XIYIN_DATA_ROOT` 必须预先存在；运行时不自动迁移数据。

3. 下载固定版本的一个模型文件：

   ```powershell
   .\.venv\Scripts\python.exe .\tools\download_model.py
   ```

   `config/model.toml` 固定 Hugging Face revision、真实文件名、大小和 SHA-256。约 3.01 GB；下载前可查看清单，`--check` 只检查本地文件。没有下载多套模型或视觉 projector。

4. 准备兼容 Qwen3.5 的 [llama.cpp Windows server](https://github.com/ggml-org/llama.cpp/releases)，在另一个终端启动：

   ```powershell
   .\tools\start_model.ps1 -ServerPath 'C:\Tools\llama.cpp\llama-server.exe' -PythonPath '.\.venv\Scripts\python.exe'
   ```

   CPU 是明确的默认；确认后端支持且显存允许时再传 `-GpuLayers`。脚本只绑定 `127.0.0.1:8080`，模型 alias 为 `xiyin`，单前台槽、4K 上下文。不自动选择 CUDA、不调用云模型。研究源码 pin 不是已实测的 Windows 二进制版本；实际 server 版本和 GPU offload 必须记录在实机验证中。

5. 验证真实推理，再开始文字会话：

   ```powershell
   .\tools\windows.ps1 -Mode doctor -ProbeModel
   .\tools\windows.ps1 -Mode chat
   ```

   输入 `/quit` 退出；生成时 Ctrl+C 取消当前回复，再次 Ctrl+C 可退出。网络/模型失败显示系统错误，不用人物台词冒充成功。探针分别记录 `/health` 与真实文本生成，不把 HTTP 200 当成 GPU 已工作。

## 记忆和成长接口

在已注册工作目录下，可用绝对路径调用 `xiyin.py`。例如明确记下一项由主理人提供的偏好：

```powershell
& '..\.venv\Scripts\python.exe' '..\xiyin.py' remember '我喜欢解谜游戏' --kind preference --subject owner
```

命令输出记忆 ID。纠正同一 kind/subject/scope 的条目可加 `--supersedes <旧ID>`；保存的是有来源的用户陈述，不宣称独立核实。底层 `ExperienceStore.remember()` 使用已有事件引用，替代与新版本在一个事务中提交。`kind=goal` 可保存续做事项，自动目标调度尚未实现。

人物投影读取有效的 `persona/preference/opinion/relationship` 记忆；如 `subject=tendency:gentle_defiance` 可为该倾向提供有经历支持的新描述。重载 seed 不会覆写这些记录。A 阶段提供存储与投影，不宣称已经实现自动人格反思或自我训练。

异步调用使用 `FoundationRuntime.stream_turn()`；事件包含 request/session ID、start、text_delta、complete、cancelled 或 error。提前退出必须 `aclose()`，推荐 `contextlib.aclosing`；取消后旧请求不能恢复输出。同步兼容入口仅支持已映射来源，默认 sidecar 被隔离为公开的独立会话；其他来源应显式实现 scope/session 适配，不能以来源字符串冒充主理人。

关闭 Runtime 前先等流结束或关闭流；进行中的 `close()` 会请求取消并抛出 `RuntimeBusy`，保留数据库与进程锁，等中断记录保存后再关闭。

## 验证与边界

```powershell
.\tools\windows.ps1 -Mode test
```

测试覆盖路径与标记、Windows junction、人物成长优先、中文召回、来源和范围隔离、流取消竞态、重启连续性与失败恢复。GitHub Actions 在 Windows/Ubuntu 跑相同离线测试，并解析 PowerShell。夹具和模拟 HTTP 响应不是模型/音频实测，CI 不下载权重、不修改账户、不启动旧 G4 执行器。

旧 `L5_SAFE/BASELINE`、`DEPLOY_BACKUP`、规则与评测资料保留原状；其中 QINAI 的人格或阶段冻结断言不代表 Foundation A 的验收标准。原 C2–C6 文件和管理工具是 legacy 路径，当前统一入口不调用它们；不要混用旧 `wait_check` 与新 SQLite 为两份权威。

采用前保留现有部署文件和数据备份。若需要撤回代码，可回到此前 Git 提交；不要删除 `.xiyin_data` 或覆盖 SQLite 来“回滚人格”。本阶段没有修改旧记忆，没有不可逆数据库迁移，也没有变更 Windows 权限。依赖使用 `requirements.lock.txt` 固定；模型和参考录音/形象素材各自保留来源信息。
