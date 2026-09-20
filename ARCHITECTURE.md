# XIYIN Runtime Architecture

实现依据是主理人提供的 `XIYIN_Architecture_v1.1_Design.md`（SHA-256 `883b5514df39dd44aa8972e88a309a652e19debb793a08e0955a4710b37faa8b`）、v1.0.1 两张语音图和 Character Bible v0.2。功能仍沿用原 M1–M10；Runtime / Body / Lab / Supervisor 是职责分组，不是四个大模型。原稿与人物原文保留在设计工作区，本文件记录代码中的对应关系，不将设计要求标成已实测能力。

## Architecture mapping

| 原方案 | 正式代码 | 当前可验证行为 |
|---|---|---|
| M1 身份/自我、M3 状态/动机 | `self_state.py`, `persona.py`, `director.py` | 持久身份、按会话/公开范围的功能状态、人物种子与成长覆盖；明确反馈支持的表达/倾向可自主采用及回退 |
| M2 感知、M4 意图/调度 | `contracts.py`, `agenda.py`, `director.py`, `service.py` | 来源适配、唯一任务队列、优先级、抢占、重启；规则技能规划与可替换 planner；未知外部动作不重放 |
| M5 表达/行动 | `runtime.py`, `context.py`, `voice.py`, `body/` | 同一作者的文字流、语义记忆投影、ASR→Runtime→TTS/播放控制链、观察→动作→验证 |
| M6 经历、M7 记忆 | `experience.py`, `dataset.py` | 原文账本、状态与回执、版本纠错、公开/私密隔离；本地导出未审阅数据候选 |
| M8 睡眠/成长 | `sleep.py`, `architecture.py` | 空闲入睡、真实会话摘录/任务检查点、前台唤醒、持久阶段；不编造停机经历 |
| M9 Lab | `learning.py`, `director.py` | 数据策略候选→独立功能检查→采用→真实执行变化→回退；人物字段成长有真实反馈来源 |
| M10 健康/停止/发布 | `supervisor.py`, `lifecycle.py`, `xiyin_management.py` | 独立停止标记、操作期间监视、身体释放、单实例锁、SQLite 一致备份/恢复；代码/模型产物清单登记与选择 |

一个 `XIYINRuntime` 拥有一份 `ExperienceStore`。`FoundationRuntime` 只是兼容别名。Body 不写第二份人格/记忆，Lab 和 Director 不直接发送按键或播放音频。`serve` 使用一个持续 asyncio loop，旧同步桥复用自己的单个 loop。

## Actual boundaries

- 人格不是 P1 固定台词。稳定身份来自人物稿；可变倾向和表达从有效成长记忆覆盖。当前自动成长采用的是**明确反馈支持的字段变化**；自由人格反思和训练后的自然度尚未证明。情绪数值是调度/表达用的计算状态，不是主观体验证据。
- 文字不按固定字数截短，也不全局删除括号。上下文隐藏账本 ID、错误码等内部结构；保留原始说话者、成功/失败语义和正常符号。生成到 token 上限仍报告截断，不伪造完成。
- 一条 goal 绑定注册时的 adapter、版本、范围与动作集，执行时重新核对。默认规则 planner 实例化已知文件技能，不能冒充已接入自主大模型规划。多身体跨域编排需要显式适配合同。
- 语音候选打断只压低音量；确认后撤销旧 epoch、取消同一 Runtime 生成与 TTS、停止客户端播放并清队列。最终 ASR 文本必须通过输入接纳标记，播放中无回声控制的转写不能绕过确认。生成、合成、client played、output observed 分开记录。
- Windows 身体仅操作明确注册的 HWND，复查前台/尺寸/DPI，按键有短租约和失焦释放；截图为可选 Pillow 后端。发送输入不等于任务成功，缺少可观察后置条件就返回 unknown。它是应用范围约束，不是 OS 沙箱。
- 游戏使用 typed semantic action 与状态版本。Neuro SDK 普通 `action/result success` 可能只是接收/参数验证，不能算游戏动作完成；适配器需要完成事件、匹配 action ID 和新状态的验证结果。
- 学习策略评估独立于候选值，当前测量 `functional_policy_check`；不是泛化、长期保持或智能增长分数。代码/模型发布记录明确 `manifest_selection_only`，尚未实现自动下载权重、执行候选代码或切换运行进程。没有用清单变化冒充已自我升级。
- 语音具体 ASR/TTS/播放客户端、Avatar、直播平台和游戏 transport 仍需要对应后端和现场配置。缺失后端返回 unavailable。没有在这次无模型验收中测自然度、GPU、AEC、声学延迟或真实游戏技能。

## Recovery and migration

数据库新增 documents 表；旧 events/memories 保留。代码更新不生成新人物身份，不移动真实数据。`init-data` 才创建标记；既有数据根及环境覆盖继续使用。

旧 QINAI C2–C7、L3/L4/L5、P1 规则、历史备份已归档到 `legacy/qinai/`。原活跃脚本在任何副作用前拒绝运行；历史备份保留原字节。保留的 C1 与 L2 入口只转向 XIYIN。单账户不再要求 SJ_Run 或固定盘符；显式旧 separate_accounts 配置仍按真实 token 校验。

新备份覆盖实际 `experience.sqlite3`。恢复需要关闭 Runtime、通过独立 lease 和数据根身份检查，并对具体目标在控制台确认一次；其余普通任务和人物成长不走重复人工审核。代码回退与记忆回退分开，不能删 `.xiyin_data` 或覆盖数据库来伪造恢复。
