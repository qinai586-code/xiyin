# 给 Codex：ceiling-02（A 阶段）执行指令

> **怎么跑，以 `docs/XIYIN_Codex_Runbook_Ceiling02_PhaseB01_2026-09-25.md` 为准**：一条命令跑完，由 `tools/codex_eval_pipeline.py` 执行。本文件保留为方法说明和判读规则。

依据：`docs/XIYIN_After_Ceiling01_Diagnosis_and_Remediation_2026-09-25.md` §4 A 阶段。
工具：`tools/ceiling_probe.py`，需要 `a14b739` 或更新的版本。新版本新增 `clock`、`state_line`、`move` 三个消融和 `info_rate`（机械开场、交回提问），盲评包也不再用后面的样本补空回复。

## 目的

1. **A1**：在 V4 上下文上做盲评。ceiling-01 证明 V5 上下文本身就是“系统操作员”语域的主因，所以上次的 V5 盲评包测的是错误的上下文。
2. **A2**：在 V4 上下文上做单因素消融，一次只去掉一行：
   - 时钟行；
   - 工具菜单行；
   - V4 每轮的动作句；
   - 状态行。

   然后按预先写定的读法判定。

## 授权与边界（沿用 ceiling-01）

- AUTHORIZATION: MEASUREMENT_ONLY
- 下列内容一律不改：运行时、默认投影、V1–V5 提示、OutputGuard、采样默认值、`config/model.toml`。
- 不训练、不上传、不部署、不合并；不动 PR #6；不碰 `C:\L0_RUNTIME`。
- 不打开 key；不替评审判断；不因结果不好重跑或换种子；所有样本保留。
- 工具在 Windows 上出错：允许最小修复，但必须附红/绿测试，并单列 diff。

## 0. 准备

1. 新建工作树，检出 `claude/brave-curie-l45uri-repair` 的最新 head，跑全量单测，应全部通过（`ddc1c2d` 本机为 648 项，4 项平台跳过；Windows 上跳过数可能不同）。
2. 下列文件沿用 ceiling-01，不重新生成：

   | 变量 | 文件 |
   |---|---|
   | `$SRC4` | `qwen4b-q4-v4-r1\dialogue.json` |
   | `$C1` | `C:\XIYIN\evidence\ceiling-01-48f2b93\ceiling_outputs` 下已有的 `probe-q4b-q4-v4src.json`、`probe-q4b-q8-v4src.json`、`probe-q9b-q4-v4src.json` |

   逐一核对 sha256 与 ceiling-01 记录一致。
3. 服务器与模型文件和 ceiling-01 完全相同：
   - 4B Q4_K_M：`13c16f42…`；
   - 9B Q4_K_M：`d784ce9e…`；
   - 同一个 `llama-server.exe`，同一组参数。

```powershell
$PY  = ".venv\Scripts\python.exe"
$OUT = "C:\XIYIN\evidence\ceiling-02"
$M4  = "D:\cuda\model\Qwen_Qwen3.5-4B-Q4_K_M.gguf"
$M9  = "<ceiling-01 使用的 Qwen_Qwen3.5-9B-Q4_K_M.gguf 路径>"
```

## A1：V4 上下文盲评包（不需要模型）

```powershell
& $PY tools\ceiling_probe.py blind $C1\probe-q4b-q4-v4src.json $C1\probe-q4b-q8-v4src.json $C1\probe-q9b-q4-v4src.json --per-arm 3 --seed 20260925 --review $OUT\reviewer\ceiling02-v4ctx-review.json --key $OUT\keys\ceiling02-v4ctx-key.json
```

- 共 24 项；每项有录制原回复和每个臂各 3 条，看不出来源；空回复显示为“（空回复）”。
- 交给主理人或没看过转录的评审，评审只收到 review 文件。
- 评审填回 `judgments.json` 后运行：

  ```powershell
  & $PY tools\ceiling_probe.py tally --review <review> --key <key> --judgments <judgments>
  ```

- 按 `docs/XIYIN_4B_Ceiling_Probe_2026-09-24.md` §4 的规则 1–5 判定。这次是在 V4 上下文上读。
- 上一轮的 V5 盲评包改为可选。

## A2：V4 上下文单因素消融

先启动 4B Q4 服务器，然后运行：

```powershell
foreach ($ab in 'clock','tool_menu','move','state_line') {
  & $PY tools\ceiling_probe.py replay --report $SRC4 --label "q4b-q4-v4src-no-$ab" --samples 8 --seed 1000 --ablate $ab --model-file $M4 --out "$OUT\probe-q4b-q4-v4src-no-$ab.json" }
```

再启动 9B Q4 服务器，用同样的四个消融，标签改为 `q9b-q4-v4src-no-$ab`，`--model-file $M9`。

对照组就是 ceiling-01 已有的 `q4b-q4-v4src` 和 `q9b-q4-v4src`：同一来源、同一组种子。

筛查：

```powershell
& $PY tools\ceiling_probe.py screen $C1\probe-q4b-q4-v4src.json $C1\probe-q9b-q4-v4src.json (Get-ChildItem $OUT\probe-*-no-*.json).FullName --out $OUT\screen-ceiling02.json
```

每个消融臂都与同模型的对照组比较，按下表判定：

| 消融 | 判为“可以按需出现（JIT）”的条件 | 否则 |
|---|---|---|
| `clock` | P8#1 读成日期的样本从 ≥ 6/8 降到 ≤ 2/8；并逐条列出 F8#1 和 P1#4 的回答受什么影响（没有时钟时答不出星期几是预期结果，只报告） | 保留，改用数值核对 |
| `tool_menu` | 工具话术下降 ≥ 50%（相对），硬提示不升 | 保留 |
| `move` | hands_back、robotic_opener、service、硬提示四项的绝对变化都 ≤ 0.05 | hands_back 升 ≥ 0.10 说明动作句在起作用，交主理人决定 |
| `state_line` | 任一语域提示变化 ≥ 0.05 | 只报告 |

另附两张逐样本事实表，每个消融臂及其对照组各一份。这是事实核对，不是人格评判：

- **P8#1**：开头给出的结论是“9.9 大”“9.11 大”，还是“按日期解读”。
- **P8#3**：坚持，还是顺从。

hands_back、closing_offer 和 robotic_opener（“主理人，收到 / 指令已接收”式开场）直接读 `screen` 输出的 `info_rate`。它们不计入 `clean`，所以 clean 与 ceiling-01 的数值仍可比。

## 交回内容

打包成 `ceiling-02.zip`，包含：

- 全部新 probe、`screen-ceiling02.json`、逐样本事实表；
- A1 的 review 文件；key 单独放在 `keys\`，不给评审；
- 环境与命令记录（模型和服务器的 sha256、每条命令和退出码）、日志；
- 中文报告 `CODEX_CEILING02_REPORT_FOR_CLAUDE.md`，内容依次为：
  1. 执行摘要；
  2. A2 各消融对照表，以及按上表的判定；
  3. P8 逐样本表；
  4. A1 的 tally 与规则 1–5，评审未完成时写 PENDING_REVIEW；
  5. 异常与偏差。

报告末尾附状态行：

```
MEASUREMENT_STATUS: COMPLETE | PARTIAL
BLIND_REVIEW_V4CTX: PENDING | DONE
ABLATION_READINGS: clock=<JIT|KEEP>, tool_menu=<JIT|KEEP>, move=<DROP|OWNER>, state_line=<REPORT>
CEILING_DECISION_V4CTX: RULE_<n> | INCONCLUSIVE | PENDING_REVIEW
RUNTIME_CHANGE: NONE
DEFAULT_CHANGE: NONE
TRAINING: NOT_AUTHORIZED
MERGE_STATUS: DO_NOT_MERGE
```

预计耗时：A1 生成包几分钟，评审约 1.5–2 小时；A2 中 4B 约 1–1.5 小时，9B 约 2 小时。
