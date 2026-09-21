# XIYIN（栖音）参考项目库总索引 · FULL

> 更新日期：2026-09-20  
> 用途：XIYIN 架构研究、FIRST ALIVE、P0–P5 技术选型、Claude / Codex / OpenCode 交接与审计。  
> 说明：**列入本文件 ≠ 批准接入生产。** 每个仓库在真正复用前，必须重新核对许可证、固定 commit、Windows 兼容性、依赖版本、网络行为、数据路径、权限边界与写入行为。

---

# 0. 先看这一页：现在真正值得碰哪些仓库

当前 XIYIN 最优先目标不是继续扩架构，而是做 **FIRST ALIVE BUILD**：

```text
Owner Input
→ XIYIN Persona / Composer
→ Local LLM
→ TTS
→ Live2D
→ Actual Playback
→ STOP
→ 最小 Ledger
```

因此当前只建议优先研究：

| 优先级 | 仓库 | 当前作用 | 现在是否值得接 |
|---|---|---|---|
| S | Project-N-E-K-O/N.E.K.O | Body / Host 主底座 | **是** |
| S | Open-LLM-VTuber/Open-LLM-VTuber | Voice interruption / Live2D / local voice loop 模式参考 | **是，主要借模式** |
| S | RVC-Boss/GPT-SoVITS | 当前已验证过路线的 TTS 候选 | **是** |
| S | obsproject/obs-studio | 本地录制 / 后续直播输出 | **是，先本地录制** |
| A | pipecat-ai/smart-turn | 后续自然 turn-end | 先留接口，不阻塞 FIRST ALIVE |
| A | snakers4/silero-vad | VAD / barge-in onset | 语音输入阶段 |
| A | SYSTRAN/faster-whisper | 本地 ASR | 语音输入阶段 |
| B | CN-Zephyr/n.e.k.o_plugin_neko_live | 直播平台输入 | **FIRST ALIVE 之后** |
| HOLD | Computer Use / Game / Town / Deep Growth 全部仓库 | 后续能力 | **现在不接** |

**止损规则：** FIRST ALIVE 之前，不因为本索引里有仓库就继续 clone / 集成。

---

# 1. 状态标签

- **ADAPT**：计划实际复用其能力，但必须经过 XIYIN contract 包装。
- **PATTERN**：借架构模式，不作为生产依赖。
- **ADDENDUM**：v1.0 后新增专项参考。
- **OPTIONAL**：候选实现，尚未裁定。
- **DEFER**：后续阶段。
- **RESEARCH**：研究/实验基线，不直接进入 runtime。
- **REJECT-RUNTIME**：明确不作为 XIYIN runtime dependency。
- **BENCHMARK**：体验/角色/能力对标。
- **HOLD**：当前冻结，不影响 FIRST ALIVE。

---

# 2. Canonical / Full-Stack AI Character & AI VTuber 参考

## 2.1 N.E.K.O — ADAPT / FIRST ALIVE CORE

**Repo**  
https://github.com/Project-N-E-K-O/N.E.K.O

**Organization**  
https://github.com/Project-N-E-K-O

**定位：**
本地优先 AI companion / embodied character runtime。当前公开仓库包含 text/audio/vision、Live2D/VRM/MMD/PNGTuber、memory、agent、plugins、desktop/runtime 等能力。

**XIYIN 主要复用：**
- TTS streaming
- Live2D / VRM body
- LipSync
- Delivery queue
- Playback / utterance lifecycle
- Avatar performance hooks
- plugin host
- OBS / live related host surface
- 可选的 memory store / runtime surface

**XIYIN 明确不继承：**
- N.E.K.O 默认 persona 作为 XIYIN 人格
- N.E.K.O 成为 XIYIN 最终文本作者
- hidden second brain
- 绕过 XIYIN ledger / policy 的长期写入
- `brain/computer_use.py` 当前 arbitrary Python/exec 风格直接进入 hardened runtime

**当前裁定：** XIYIN Mind 自己拥有身份和最终文本，N.E.K.O 是 Body / Host。

---

## 2.2 neko_live — ADAPT / LIVE INGEST

**Repo**  
https://github.com/CN-Zephyr/n.e.k.o_plugin_neko_live

**用途：**
- Bilibili / live platform ingest
- viewer identity
- danmaku / live events
- passive live context

**XIYIN 复用方式：**
```text
Platform
→ neko_live
→ M2 Perception
→ Crowd / Salience
→ XIYIN decides
→ Voice Floor
```

**关闭 / 绕过：**
- hosting persona
- roast
- fixed engagement lines
- 自动把每条弹幕变成一次模型回复
- 二次人格塑形

**阶段：** FIRST ALIVE 后，先 READ-ONLY，再进入 P2 crowd interaction。

---

## 2.3 YuriOS — PATTERN

**Repo**  
https://github.com/yuri-os/YuriOS

**定位：**
local-first, always-on AI companion runtime；公开描述包含 body、voice、memory、autonomous inner life、goals、sleep consolidation、journal 等。

**XIYIN 借鉴：**
- cognitive tick loop
- sense → appraise → decide → act → reflect → regulate
- proactive gate
- goals / intentions
- sleep job
- journal / trace
- persona / self-model edits 的 gated 思路
- brain / voice seam

**不直接复制：**
- 自编辑人格策略
- 自主长期写入规则
- 其完整“心智”作为 XIYIN Mind

---

## 2.4 Miru — PATTERN

**Repo**  
https://github.com/kiyotakali/Miru

**定位：**
local/self-hosted AI companion，强调可验证 memory、AttentionEngine、SleepAgent、Live2D desktop presence。

**XIYIN 借鉴：**
- AttentionEngine
- “何时说话”而不只是“说什么”
- sensor → attention → decision
- memory fact provenance
- sleep batching
- readable memory/journal

**注意：**
Miru 自己的产品哲学不是 XIYIN canonical；只借机制。

---

## 2.5 Open-LLM-VTuber — PATTERN / FIRST ALIVE HIGH VALUE

**Repo**  
https://github.com/Open-LLM-VTuber/Open-LLM-VTuber

**Frontend**  
https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web

**Docs**  
https://github.com/Open-LLM-VTuber/open-llm-vtuber.github.io

**用途：**
- hands-free voice interaction
- voice interruption
- Live2D local avatar
- cross-platform local voice agent
- streaming TTS/ASR/LLM orchestration
- interrupted response handling
- local desktop pet / web surface

**2026-09 现状备注：**
v1 仍在维护，项目公开说明 v2.0 处于重写/规划阶段。生产参考时必须固定版本，不要直接追 HEAD。

**XIYIN 最值得借：**
- interruption
- response lifecycle
- local voice + body 最小闭环
- “思考不朗读、正文才朗读”的分层

---

## 2.6 AIRI — PATTERN / DEFER

**Repo**  
https://github.com/moeru-ai/airi

**定位：**
开源 AI companion / virtual character 平台，官方明确受 Neuro-sama 启发；包含 voice、character、game / agent 方向。

**XIYIN 借鉴：**
- agent/core contracts
- context vs instruction separation
- game plugins
- Minecraft / Factorio 等扩展组织
- virtual character product integration

**不采用：**
- “container of souls” 作为 XIYIN 身份定义
- AIRI 预设 persona 作为 XIYIN persona

---

## 2.7 Lumi_Nox — PATTERN

**Repo**  
https://github.com/MIO-456/Lumi_Nox

**定位：**
两个 AI 角色共同主持直播；公开 README 强调 real scheduler、speech arbiter、turn-taking、viewer chat、memory、game。

**XIYIN 借鉴：**
- scheduler vs speaking floor
- one-voice-at-a-time
- event bus / arbiter
- multi-character coordination
- game bridge
- live dialogue turn arbitration

**阶段：** P2+，FIRST ALIVE 不需要。

---

## 2.8 NachoBot — PATTERN

**Repo**  
https://github.com/Big-Sh0t114/NachoBot

**定位：**
多平台 AI 虚拟生命 / bot，含 Bilibili、Discord、NapCat/QQ、Live2D、多模态、TTS/VLM/ASR adapters。

**XIYIN 借鉴：**
- platform adapter organization
- scene/runtime profiles
- Bilibili adapter
- TTS / multimodal / Live2D service organization
- Windows launch / service separation

**不直接导入：**
- memory plugin
- persona
- 多服务全量 runtime

---

## 2.9 MUJI_MOE — PATTERN / BODY

**Repo**  
https://github.com/LSimon95/muji-moe

**用途：**
历史公开 C++ + Live2D + voice chatbot reference。

**XIYIN 借鉴：**
- Expression → Voice → Body
- Blink / Breath
- Motion / Expression
- Physics / Pose
- LipSync
- Motion preload / fade
- Live2D Native integration

**注意：**
仓库中的 Live2D MUJI_MOE model 自身有单独的非商业许可限制；代码许可与素材许可必须分开核对。

---

# 3. Zerolan 系列 — 服务 / Protocol / Game Bridge 参考

## 3.1 ZerolanLiveRobot — REJECT-RUNTIME / PATTERN

**Repo**  
https://github.com/AkagawaTsurunaki/ZerolanLiveRobot

**用途：**
AI VTuber 控制框架，公开能力包含 LLM / ASR / TTS / OCR / CV / live chat / OBS / Live2D / Minecraft bridge。

**XIYIN 只借：**
- service boundary
- live robot orchestration
- protocol separation
- OBS subtitle / Live2D mouth sync 问题的现实经验

**当前裁定：** 不作为 XIYIN runtime dependency。

---

## 3.2 zerolan-core — PATTERN

**Repo**  
https://github.com/AkagawaTsurunaki/zerolan-core

**用途：**
LLM / ASR / TTS 等 AI inference services 的服务化拆分。

---

## 3.3 zerolan-data — PATTERN

**Repo**  
https://github.com/AkagawaTsurunaki/zerolan-data

**用途：**
跨服务 data class / protocol；包含 LLM/ASR/TTS/VLA/danmaku 等数据对象。

**XIYIN 借鉴：**
typed message / protocol boundary，而不是直接继承 schema。

---

## 3.4 KonekoMinecraftBot — DEFER P5

**Repo**  
https://github.com/AkagawaTsurunaki/KonekoMinecraftBot

**用途：**
Mineflayer + FSM Minecraft bot。

**XIYIN 借鉴：**
- game executor
- FSM
- telemetry / state
- high-level command → low-level game behavior

**硬规则：**
`action dispatched != verified_success`，必须有 verifier。

---

# 4. Game / AI VTuber Interaction / Motor Control

## 4.1 Neuro SDK — ADDENDUM / P5 CORE REFERENCE

**Repo**  
https://github.com/VedalAI/neuro-sdk

**用途：**
Neuro-sama 官方公开 game integration API / SDK。

**支持：**
- typed game actions
- state/context
- action results
- Unity / Godot SDK
- websocket protocol
- voice-chat related API

**最重要的设计启发：**
官方文档明确指出，高 APM 游戏不适合让 Neuro 直接处理所有低层动作；更合理的是 Neuro 控制高层行为，另一个系统完成低层控制。

**XIYIN 推荐：**
```text
XIYIN Mind
→ Game Adapter
→ typed high-level action
→ low-level controller
→ game
→ telemetry / verifier
```

---

## 4.2 GamingAgent / LMGame — ADDENDUM / RESEARCH

**Repo**  
https://github.com/lmgame-org/GamingAgent

**用途：**
- standardized interactive game env
- LLM/VLM gaming agent
- LMGame-Bench
- computer-use gaming
- evaluation harness
- replay / metrics

**阶段：** P5 Lab / evaluation。

---

## 4.3 NitroGen — RESEARCH ONLY

**Repo**  
https://github.com/MineDojo/NitroGen

**用途：**
generalist gaming agent / fast reactive visual-action policy；用于研究“慢 Mind + 快 Motor”分层。

**公开 README：**
支持 Windows 11 / Python ≥ 3.12，并通过 process name 控制游戏。

**许可证红线：**
当前 NVIDIA License 对 Work 和 derivatives 有 **non-commercial research only** 使用限制。

**XIYIN 当前裁定：**
- 研究
- offline experiment
- architecture reference
- 不进入商业/长期生产依赖，除非重新获得合适许可

---

# 5. Realtime Voice / ASR / Turn-Taking

## 5.1 Pipecat — ADDENDUM

**Repo**  
https://github.com/pipecat-ai/pipecat

**用途：**
- realtime voice pipeline
- streaming audio
- multimodal pipelines
- interruption
- turn events
- service adapters

**XIYIN：**
参考 Voice Floor / turn pipeline，不要求直接改成 Pipecat runtime。

---

## 5.2 Smart Turn — ADDENDUM

**Repo**  
https://github.com/pipecat-ai/smart-turn

**当前公开版本：**
Smart Turn v3.x 系列，native-audio turn detection。

**用途：**
判断“用户是否真的说完”。

**正确位置：**
```text
AEC
→ VAD detects speech / silence
→ Smart Turn judges semantic turn-end
```

**不要：**
把 Smart Turn 当成最前面的 barge-in onset detector。

---

## 5.3 Silero VAD — OPTIONAL / VOICE

**Repo**  
https://github.com/snakers4/silero-vad

**用途：**
lightweight VAD；Smart Turn 官方也建议和轻量 VAD 结合。

**XIYIN：**
主理人 speech onset / silence detection 候选。

---

## 5.4 faster-whisper — OPTIONAL / ASR

**Repo**  
https://github.com/SYSTRAN/faster-whisper

**用途：**
Whisper 的 CTranslate2 高效实现，本地 ASR。

**XIYIN：**
语音输入候选，不是 Persona / Mind dependency。

---

# 6. Body / Live2D / Tracking / Streaming

## 6.1 Live2D Cubism Native Framework

https://github.com/Live2D/CubismNativeFramework

**用途：**
Native Live2D runtime framework。

---

## 6.2 Live2D Cubism Native Samples

https://github.com/Live2D/CubismNativeSamples

**用途：**
参数、motion、expression、physics、lip sync 等官方 sample。

---

## 6.3 Live2D Cubism Web Framework

https://github.com/Live2D/CubismWebFramework

**用途：**
Web runtime reference。

---

## 6.4 VTube Studio

https://github.com/DenchiSoft/VTubeStudio

**用途：**
VTube Studio API / integration reference。

**XIYIN 重点：**
- parameters
- expressions
- hotkeys
- tracking / external control
- events

---

## 6.5 OpenSeeFace — OPTIONAL

**Repo**  
https://github.com/emilianavt/OpenSeeFace

**用途：**
CPU realtime face / facial landmark tracking，Unity integration；VTube Studio 也使用过其 webcam tracking 路线。

**阶段：**
后续摄像头 tracking，不是 FIRST ALIVE gate。

---

## 6.6 Rhubarb Lip Sync — OPTIONAL / OFFLINE LIPSYNC

**Repo**  
https://github.com/DanielSWolf/rhubarb-lip-sync

**用途：**
从已生成音频生成 mouth-shape timeline（JSON/XML/TSV 等）。

**XIYIN：**
可作为离线/预生成 lipsync 实验；实时 Live2D MVP 更优先使用 body/runtime 本身的 lip sync。

---

## 6.7 OBS Studio — ADAPT / OUTPUT

**Repo**  
https://github.com/obsproject/obs-studio

**用途：**
- local recording
- scene composition
- broadcast output
- stream control

**当前 FIRST ALIVE：**
先做本地录制和 private test，不急着公开直播。

---

# 7. Browser / Computer Use / Windows Control — 当前 HOLD

> 当前全部 **DESIGN HOLD**。保存参考，但 FIRST ALIVE 之前不集成。

## 7.1 Playwright — PATTERN / Browser Semantic Control

**Repo**  
https://github.com/microsoft/playwright

**用途：**
Chromium / Firefox / WebKit 浏览器自动化。

**XIYIN 控制优先级中的位置：**
Browser DOM / semantic control 优先于纯截图坐标点击。

---

## 7.2 Browser Use — PATTERN / Browser Agent

**Repo**  
https://github.com/browser-use/browser-use

**用途：**
browser agent / CDP / local or cloud browser automation。

**XIYIN：**
只作 browser adapter 参考，不允许其成为越过 Action Broker 的独立 Brain。

---

## 7.3 OmniParser — RESEARCH / Vision Fallback

**Repo**  
https://github.com/microsoft/OmniParser

**用途：**
把 UI screenshot 解析成 structured elements；适合纯视觉 GUI agent grounding。

**XIYIN：**
当 DOM / UIA 不可用时才考虑。

---

## 7.4 UI-TARS

**Repo**  
https://github.com/bytedance/UI-TARS

**用途：**
native GUI grounding / UI action research。

---

## 7.5 UI-TARS Desktop

**Repo**  
https://github.com/bytedance/UI-TARS-desktop

**用途：**
Windows/macOS/browser GUI agent desktop application；支持 screenshot recognition + mouse/keyboard control。

**XIYIN：**
research/reference only；不能让其绕过 XIYIN Input Lease / Owner Takeover / verifier。

---

## 7.6 Agent S / Agent S2 — RESEARCH

**Repo**  
https://github.com/simular-ai/Agent-S

**用途：**
modular computer-use agent framework；planner + grounding / experience retrieval。

**XIYIN 借鉴：**
planner / specialist separation。

---

## 7.7 Windows Agent Arena — EVAL

**Repo**  
https://github.com/microsoft/WindowsAgentArena

**用途：**
Windows desktop agent benchmark / reproducible environment。

**XIYIN：**
未来 M9 LAB，用来测试 Computer Control，不进入 runtime。

---

## 7.8 OSWorld / OSWorld-Verified — EVAL

**Repo**  
https://github.com/xlang-ai/OSWorld

**用途：**
real computer environment benchmark；官方仓库已将 OSWorld-Verified 纳入后续更新。

**XIYIN：**
用于验证 GUI Agent，不作为动作执行依赖。

---

## 7.9 OpenCUA — RESEARCH

**Repo**  
https://github.com/xlang-ai/OpenCUA

**用途：**
open computer-use foundations / AgentNet / GUI models / data / tools。

**XIYIN：**
future executor/model research。

---

## 7.10 Microsoft Fara — RESEARCH / LOCAL CUA CANDIDATE

**Repo**  
https://github.com/microsoft/fara

**当前公开方向：**
Fara1.5 family；computer-use agent，observe-think-act，支持 screenshot → mouse/keyboard/browser action。

**XIYIN：**
后续可作为 specialized GUI executor 候选，不是主 Mind。

---

## 7.11 Microsoft Magentic-UI — PATTERN / SAFER HARNESS

**Repo**  
https://github.com/microsoft/magentic-ui

**用途：**
human-centered multi-agent web/computer task harness；包含 sandbox、auditable action logging、critical-point user prompts 等方向。

**XIYIN 借鉴：**
- user approval point
- auditable execution
- sandbox
- critical-action gate

---

## 7.12 Microsoft CUA Skill — HIGH VALUE PATTERN

**Repo**  
https://github.com/microsoft/cua_skill

**用途：**
Windows CUA reusable skill library；Replay / RAG Agent；action registry；skill DAG；BM25 + embedding retrieval；UIA / pyautogui / grounding。

**XIYIN 借鉴：**
- Skill Bank
- parameterized skills
- action registry
- skill retrieval
- reusable action graph
- benchmark with WindowsAgentArena

**阶段：** P5。

---

# 8. Computer Control 的推荐优先顺序

```text
1. Native API / CLI
2. Game API / Mod / typed protocol
3. Browser DOM / Playwright / CDP
4. Windows UI Automation (UIA)
5. Structured keyboard/mouse Action DSL
6. Screenshot/VLM Computer Use fallback
```

**永远不要默认：**
```text
LLM
→ 任意 Python exec
→ pyautogui
```

未来最低要求：
- strict Action DSL
- allowlist dispatcher
- Input Lease
- Owner Takeover
- held-key/button release
- `plan_epoch`
- verifier registry
- strong evidence before screenshot-VLM evidence

---

# 9. Memory / Growth / Self-Improvement Research

## 9.1 ReasoningBank — RESEARCH

**Repo**  
https://github.com/google-research/reasoning-bank

**用途：**
从成功和失败 trajectory 中形成 reusable reasoning memory。

**XIYIN 借鉴：**
- strategy memory
- critic / Lab
- failure lessons
- experience-driven improvement

**不直接等同于：**
人格记忆、情节记忆或 lived experience。

---

## 9.2 Darwin Gödel Machine — RESEARCH ONLY

**Repo**  
https://github.com/jennyzzt/dgm

**用途：**
self-improving coding agent；生成变体、经验评估、archive。

**警告：**
其公开仓库本身明确提醒 model-generated code 的安全风险。

**XIYIN 只借：**
```text
candidate
→ isolated evaluation
→ benchmark
→ archive
→ selection
```

**不采用：**
runtime 自由修改核心身份/权限/生产代码。

---

## 9.3 RecMem — RESEARCH

**Repo**  
https://github.com/CaiusDai/RecMem

**用途：**
recurrence-gated consolidation / memory research。

**XIYIN 借鉴：**
避免一次性事件直接永久人格化。

---

## 9.4 Generative Agents — RESEARCH

**Repo**  
https://github.com/StanfordHCI/genagents

**用途：**
memory stream / reflection / planning 的经典研究实现。

**XIYIN 差异：**
simulation / reflection 不能自动变成 lived experience。

---

# 10. Local LLM / Inference Runtime

## 10.1 llama.cpp — OPTIONAL / LOCAL INFERENCE

**Repo**  
https://github.com/ggml-org/llama.cpp

**用途：**
GGUF local inference / quantization / Windows local model serving。

**XIYIN：**
本地 8B–14B Brain backend 候选之一；backend 可以换，但不能成为第二人格入口。

---

# 11. TTS / Voice Candidates

> 下面是候选，不是 canonical 最终选择。必须在你的 Windows 12GB GPU / 实际声线 / streaming / interrupt 下实测。

## 11.1 GPT-SoVITS — CURRENT HIGH VALUE

**Repo**  
https://github.com/RVC-Boss/GPT-SoVITS

**License：** MIT（代码）。

**特点：**
- few-shot voice cloning
- zh / ja / en 等多语言
- Windows install scripts
- 你已有成功运行经验

**XIYIN：**
FIRST ALIVE 的优先 TTS 候选。

---

## 11.2 CosyVoice — OPTIONAL

**Repo**  
https://github.com/FunAudioLLM/CosyVoice

**特点：**
multilingual、streaming inference、instruction / voice cloning 路线。

**注意：**
依赖和子模块较重；必须独立 sandbox 测试，不直接污染主环境。

---

## 11.3 IndexTTS — OPTIONAL

**Repo**  
https://github.com/index-tts/index-tts

**2026-09 当前公开：**
IndexTTS-2.5 已公开，支持中文、英文、日语等并提供 emotion / speed / pronunciation control。

**重要：**
当前项目使用 **bilibili Model Use License Agreement**，不是常规 MIT/Apache。商用/再分发前必须专门核对。

---

## 11.4 VoxCPM — OPTIONAL

**Repo**  
https://github.com/OpenBMB/VoxCPM

**用途：**
context-aware TTS / voice cloning。

**License：**
当前公开 README/pyproject 标明 code + weights Apache-2.0。

---

# 12. 以后可以追加、但目前不应扩张的方向

如果后续真进入下一阶段，再研究：

- additional ASR engines
- WebRTC / AEC
- VMC / VRM specialized body drivers
- MMD automation
- game-specific mods
- native Windows UIA wrappers
- local vision models
- eval datasets
- skill libraries

**现在不要因为“可能以后有用”就把所有项目拉到 production tree。**

---

# 13. 当前项目阶段映射

| Phase | 主要仓库 |
|---|---|
| PATH / P0 | XIYIN 自身 repo；N.E.K.O compatibility audit |
| FIRST ALIVE / P1 | N.E.K.O、Open-LLM-VTuber（模式）、GPT-SoVITS、OBS |
| Voice enhancement | Silero VAD、faster-whisper、Smart Turn、Pipecat |
| Live | neko_live、OBS、Lumi_Nox（模式） |
| P2 Mind/Presence | YuriOS、Miru、AIRI（模式） |
| P3 Memory | Miru、YuriOS、Generative Agents、RecMem |
| P4 Learning Lab | ReasoningBank、DGM |
| P5 Game | Neuro SDK、GamingAgent、KonekoMinecraftBot、NitroGen（研究） |
| P5 Computer | Playwright、Browser Use、CUA Skill、UI-TARS、OmniParser、Agent-S、Fara、OpenCUA |
| P5 Eval | WindowsAgentArena、OSWorld |

---

# 14. 一页式总表

| Repo | 类别 | XIYIN 裁定 | 现在接入？ |
|---|---|---|---|
| Project-N-E-K-O/N.E.K.O | Body/Host | ADAPT | **是** |
| CN-Zephyr/n.e.k.o_plugin_neko_live | Live ingest | ADAPT | FIRST ALIVE 后 |
| yuri-os/YuriOS | Mind pattern | PATTERN | 否 |
| kiyotakali/Miru | Attention/Memory | PATTERN | 否 |
| Open-LLM-VTuber/Open-LLM-VTuber | Voice/Body | PATTERN | **研究并借模式** |
| moeru-ai/airi | Companion/Game | PATTERN/DEFER | 否 |
| MIO-456/Lumi_Nox | Live scheduler | PATTERN | 否 |
| AkagawaTsurunaki/ZerolanLiveRobot | Live robot | REJECT-RUNTIME | 否 |
| AkagawaTsurunaki/zerolan-core | AI services | PATTERN | 否 |
| AkagawaTsurunaki/zerolan-data | Protocol | PATTERN | 否 |
| AkagawaTsurunaki/KonekoMinecraftBot | Game | DEFER P5 | 否 |
| Big-Sh0t114/NachoBot | Multi-platform VTuber | PATTERN | 否 |
| LSimon95/muji-moe | Body | PATTERN | 否 |
| VedalAI/neuro-sdk | Game protocol | ADDENDUM | P5 |
| lmgame-org/GamingAgent | Game/Eval | ADDENDUM | P5 Lab |
| MineDojo/NitroGen | Motor | RESEARCH ONLY | 否 |
| pipecat-ai/pipecat | Voice pipeline | ADDENDUM | 后续 |
| pipecat-ai/smart-turn | Turn end | ADDENDUM | 后续 |
| snakers4/silero-vad | VAD | OPTIONAL | Voice |
| SYSTRAN/faster-whisper | ASR | OPTIONAL | Voice |
| Live2D/* Cubism | Body SDK | BODY REF | P1 |
| DenchiSoft/VTubeStudio | Body API | BODY REF | Optional |
| emilianavt/OpenSeeFace | Face tracking | OPTIONAL | 后续 |
| DanielSWolf/rhubarb-lip-sync | Lip sync | OPTIONAL | 后续 |
| obsproject/obs-studio | Output/Streaming | ADAPT | **P1 local record** |
| microsoft/playwright | Browser semantic | PATTERN | P5 |
| browser-use/browser-use | Browser agent | PATTERN | P5 |
| microsoft/OmniParser | Screen parsing | RESEARCH | P5 |
| bytedance/UI-TARS | GUI model | RESEARCH | P5 |
| bytedance/UI-TARS-desktop | GUI agent | RESEARCH | P5 |
| simular-ai/Agent-S | CUA framework | RESEARCH | P5 |
| microsoft/WindowsAgentArena | Windows eval | EVAL | P5 Lab |
| xlang-ai/OSWorld | OS eval | EVAL | P5 Lab |
| xlang-ai/OpenCUA | CUA foundation | RESEARCH | P5 |
| microsoft/fara | CUA model | RESEARCH | P5 |
| microsoft/magentic-ui | Safe harness | PATTERN | P5 |
| microsoft/cua_skill | Skill bank | PATTERN | P5 |
| google-research/reasoning-bank | Strategy memory | RESEARCH | P4 |
| jennyzzt/dgm | Self-improvement | RESEARCH | P4 Lab |
| CaiusDai/RecMem | Consolidation | RESEARCH | P3/P4 |
| StanfordHCI/genagents | Memory/reflection | RESEARCH | P3 |
| ggml-org/llama.cpp | Local inference | OPTIONAL | Brain backend |
| RVC-Boss/GPT-SoVITS | TTS | OPTIONAL / HIGH VALUE | **P1** |
| FunAudioLLM/CosyVoice | TTS | OPTIONAL | Later |
| index-tts/index-tts | TTS | OPTIONAL | Later |
| OpenBMB/VoxCPM | TTS | OPTIONAL | Later |

---

# 15. 历史 XIYIN 固定提交（仅用于复现实验，不代表当前 HEAD）

> 这些 pin 来自此前 XIYIN reference/canonical 记录。**任何重新接入都要先验证 commit 仍可访问、license 和当前 contract 是否一致。**

```text
N.E.K.O
bf65bef589dae4a624461e1491cb0bf94c8cc3f6

neko_live
dff194045205dea2ab6cb907045a999ae30ce0bd

YuriOS
6bab22dc46b89a2315ea47daefaa1ad8d8eddaf7

Miru
7dcf68d874972301048bf69b27a172f4643bb8d7

Open-LLM-VTuber
992309c0aa19845960228f880013d4685fde93b5

AIRI
1b019c32b3e11c669f3bfcd4b6e43a6583b7f0a3

Lumi_Nox
77f973431c49f5ab72d3b2501c0e89286997ec46

ZerolanLiveRobot
aad29d093295eef351da03a0bbe6ffac5539716d

KonekoMinecraftBot
b582ef3073bcb62c2fdfea7a9bfd9dffd472d7bf

NachoBot
f86df60d74c71d94c3505b6f20a7d35fe9af3373

muji-moe
c65106cf9e6bf4afbe8074b77ccdd93a7e640171
```

---

# 16. 引入第三方项目的硬规则

1. **参考 ≠ 依赖。**
2. **HEAD ≠ canonical pin。**
3. 不允许第三方项目新增第二个最终文本作者。
4. 不允许绕过 XIYIN Voice Floor。
5. 不允许绕过 Ledger / verifier，把“发出命令”当“执行成功”。
6. 不允许第三方 memory 直接改写 XIYIN durable identity。
7. Computer Use 必须经过 Action DSL / allowlist / Input Lease / Owner Takeover / verifier。
8. 任何模型权重、Live2D/MMD 资产、声音模型必须单独核对 license；不能只看代码仓库 license。
9. Windows 实机未通过之前，不声明 “supported”。
10. 新仓库只有在**阻塞当前阶段**时才进入 runtime tree。

---

# 17. 推荐目录结构

本文件应该留在文档区，不进入运行路径：

```text
docs/
  research/
    XIYIN_REFERENCE_REPOSITORIES_FULL.md

third_party/
  # 只有真正获批并固定版本的依赖才允许进入
```

不要建立：

```text
third_party/
  50 个“以后可能有用”的 clone
```

---

# 18. 当前最重要的裁定

**FIRST ALIVE 之前，所有 Computer Use、Game、Town、Deep Growth 项目只留在这份索引里。**

真正需要证明的是：

```text
Windows
→ XIYIN input
→ local model
→ XIYIN voice
→ Live2D
→ playback
→ STOP
→ restart reproducible
```

只有这条通过以后，才继续从本索引中按阶段增加器官。

---

# 19. 主要公开来源 / 核验入口

本文件综合了 XIYIN 既有 reference index 与 2026-09-20 重新核对的公开 GitHub 仓库。关键入口包括：

- N.E.K.O  
  https://github.com/Project-N-E-K-O/N.E.K.O
- Neuro SDK  
  https://github.com/VedalAI/neuro-sdk
- Open-LLM-VTuber  
  https://github.com/Open-LLM-VTuber/Open-LLM-VTuber
- YuriOS  
  https://github.com/yuri-os/YuriOS
- Miru  
  https://github.com/kiyotakali/Miru
- AIRI  
  https://github.com/moeru-ai/airi
- Lumi_Nox  
  https://github.com/MIO-456/Lumi_Nox
- ZerolanLiveRobot  
  https://github.com/AkagawaTsurunaki/ZerolanLiveRobot
- GamingAgent  
  https://github.com/lmgame-org/GamingAgent
- NitroGen  
  https://github.com/MineDojo/NitroGen
- Pipecat / Smart Turn  
  https://github.com/pipecat-ai/pipecat  
  https://github.com/pipecat-ai/smart-turn
- Windows Agent Arena  
  https://github.com/microsoft/WindowsAgentArena
- OSWorld  
  https://github.com/xlang-ai/OSWorld
- OpenCUA  
  https://github.com/xlang-ai/OpenCUA
- Microsoft Fara  
  https://github.com/microsoft/fara
- Microsoft CUA Skill  
  https://github.com/microsoft/cua_skill
- ReasoningBank  
  https://github.com/google-research/reasoning-bank
- DGM  
  https://github.com/jennyzzt/dgm

---

**END**
