# Open Source Integration

本次区分真实接口依赖、设计借鉴和未接入候选。没有宣称把参考清单中的所有仓库拼装进 Runtime，也没有复制第三方整套角色人格。以下链接对应实际核对的官方资料。

| 项目 | 实际使用方式 | 本轮边界 |
|---|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp/blob/3cf03257f219afbe7334045ff7c6a06ac68c627d/tools/server/README.md) | 现有本地兼容 SSE 客户端、取消、截断状态保留 | 不启动 server，不下载权重 |
| [Pipecat](https://github.com/pipecat-ai/pipecat/tree/dbdf21a017f86624fb7768e35730417169524e0d) | `body/pipecat.py` 可选真实 frame 类型桥；参考其优先打断、取消任务与重建队列机制 | 未安装框架/音频后端；不把 frame 桥说成已完成音频部署 |
| [N.E.K.O playback core](https://github.com/Project-N-E-K-O/N.E.K.O/blob/bf65bef589dae4a624461e1491cb0bf94c8cc3f6/static/app/app-audio-playback.js) | 核对音频 epoch、队列与取消/实际播放生命周期；设计参考 | 未直接移植这段前端，不继承它的宿主、人格或记忆 |
| [YuriOS mind-loop tests](https://github.com/yuri-os/YuriOS/blob/6bab22dc46b89a2315ea47daefaa1ad8d8eddaf7/tests/test_mind_loop.py) | 核对单次意图、ENGAGED 抢占、持久目标与静默任务记录；设计参考 | 自己的 SQLite/Agenda 实现，未引入第二个 Mind |
| [Neuro SDK specification](https://github.com/VedalAI/neuro-sdk/blob/main/API/SPECIFICATION.md) | `body/game.py` 的 typed action 语义与接收/完成分离 | 尚非完整 Neuro WebSocket server；需游戏 transport |
| [AIRI](https://github.com/moeru-ai/airi/tree/1b019c32b3e11c669f3bfcd4b6e43a6583b7f0a3) | 保留原方案的身体/平台参考，核对提供的 commit | 未引入运行依赖，不声称已经移植其代码 |
| [Qwen3.5-4B GGUF](https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF) | 保留 `config/model.toml` 原 revision/文件/SHA-256；核对 Hub 元数据 | 不更换版本，不验证模型自然度 |
| [Smart Turn v3](https://huggingface.co/pipecat-ai/smart-turn-v3) | 核对轮次检测候选的 Hub 元数据 | 未接入推理，EnergyVAD 是可测试的基础后备机制，不等价于 Smart Turn |

新增协调代码为本项目实现；没有把“参考过上游”写成“复制上游实现”。未来实际提取第三方源码必须随组件保留原许可证、署名、来源 commit 和本地差异；不能把候选仓库的许可证沿用到整个 XIYIN 仓库。
