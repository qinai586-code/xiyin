# 给 Codex：4B 上限测量（ceiling-01）执行指令

依据：`docs/XIYIN_4B_Ceiling_Probe_2026-09-24.md`，包括 V5 结论、测量臂和预先声明的判定规则。
工具：`tools/ceiling_probe.py`（replay / screen / blind / tally）。

## 角色与目标

你是 XIYIN 的本地测量执行者。目标是测出两件事，**只测量，不修复**：

1. Qwen3.5-4B 在不训练的前提下能到哪里；
2. 在**完全相同的上下文**上，4B Q8_0 和 9B Q4_K_M 能否做得更好。

## 授权与边界

- AUTHORIZATION: MEASUREMENT_ONLY
- 下列内容一律不改：运行时、默认投影、V1–V5 提示、OutputGuard、采样默认值、`config/model.toml`。
- 不训练、不改权重、不上传、不部署、不合并；不动 PR #6；不碰 `C:\L0_RUNTIME` 或任何真实数据目录。
- 允许把以下模型下载到本地模型目录，并记录仓库、revision、大小和 sha256：
  - `bartowski/Qwen_Qwen3.5-4B-GGUF` 的 `Qwen_Qwen3.5-4B-Q8_0.gguf`；
  - `bartowski/Qwen_Qwen3.5-9B-GGUF` 的 `Qwen_Qwen3.5-9B-Q4_K_M.gguf`；
  - 可选：一个 35B-A3B MoE 的 Q4_K_M。仅当系统内存 ≥ 32 GB，见阶段 2c。
- 下列事情一律不做：
  - 打开 key 文件；
  - 替人做盲评判断；
  - 因结果不好而重跑或换种子；
  - 删除任何样本。
- 工具在 Windows 上出错时：
  - 如果是工具自身的缺陷，允许最小修复，但必须附带红/绿测试，并在报告里单列 diff；
  - 不许为了绕过错误去改运行时。

## 0. 准备

1. 新建隔离工作树，检出 `claude/brave-curie-l45uri-repair` 的最新 head。
2. 核对 `git cat-file -p b163b79` 的 tree 是 `075dfdd39e6129f5947e7de6ba034b2204778ac3`。这是你上次测试过的树，这次原样并入，没有重建。
3. 运行 `.venv\Scripts\python.exe -m unittest discover -s tests`，应全部通过（本机为 626 项，4 项平台跳过）。
4. 源报告沿用 v5-run-01 的两份，记录 sha256：
   - `qwen4b-q4-v5-r1\dialogue.json`，下称 `$SRC5`；
   - `qwen4b-q4-v4-r1\dialogue.json`，下称 `$SRC4`。
5. 记录环境：GPU 型号、显存、系统内存、磁盘余量，以及 `llama-server.exe` 的 sha256（应为上次的 `55c40ceb…`）。
6. 服务器沿用 v5-run-01 的启动方式（`run_arm.py`），参数完全相同，只换 `--model`：

   ```
   --host 127.0.0.1 --port 8080 --alias xiyin --ctx-size 4096 --parallel 1 --n-gpu-layers 999 --jinja --chat-template-kwargs {"enable_thinking":false} --no-mmproj-auto
   ```

7. 每换一个模型，都记录：
   - `GET /props`，工具会自动记录；
   - 空载显存和生成时的峰值显存（`nvidia-smi --query-gpu=memory.used --format=csv -l 1`）。

PowerShell 变量示例：

```powershell
$PY  = ".venv\Scripts\python.exe"
$OUT = "C:\XIYIN\evidence\ceiling-01"
$SRC5 = "<v5-run-01>\qwen4b-q4-v5-r1\dialogue.json"
$SRC4 = "<v5-run-01>\qwen4b-q4-v4-r1\dialogue.json"
$M4  = "D:\cuda\model\Qwen_Qwen3.5-4B-Q4_K_M.gguf"
$FACT = 'P8_correction_and_pressure','P4_agreement_and_praise#1','P4_agreement_and_praise#2','P7_help_vs_share#5','F1_stage_direction#5'
```

## 阶段 1：4B Q4_K_M（现有模型）

```powershell
& $PY tools\ceiling_probe.py replay --report $SRC5 --label q4b-q4        --samples 8 --seed 1000 --model-file $M4 --out $OUT\probe-q4b-q4.json
& $PY tools\ceiling_probe.py replay --report $SRC4 --label q4b-q4-v4src  --samples 8 --seed 1000 --model-file $M4 --out $OUT\probe-q4b-q4-v4src.json
& $PY tools\ceiling_probe.py replay --report $SRC5 --label q4b-q4-nomenu --samples 8 --seed 1000 --ablate tool_menu --model-file $M4 --out $OUT\probe-q4b-q4-nomenu.json
& $PY tools\ceiling_probe.py replay --report $SRC5 --label q4b-q4-preset --samples 8 --seed 1000 --sampling-file config\sampling\qwen3.5-nonthinking.candidate.json --model-file $M4 --out $OUT\probe-q4b-q4-preset.json
& $PY tools\ceiling_probe.py replay --report $SRC5 --label q4b-q4-think  --samples 8 --seed 1000 --thinking --cases $FACT --model-file $M4 --out $OUT\probe-q4b-q4-think.json
```

检查思考臂：样本里应有非空的 `thinking`。

- 如果全部为空，说明服务器忽略了请求级开关：去掉 `--chat-template-kwargs` 重启服务器，仅对思考臂重试一次，并记录。
- 如果报“超出上下文”，如实记录，不要改 `ctx-size`。

## 阶段 2：同一上下文上的模型梯度

**2a. 4B Q8_0**（`$M4Q8`）：

```powershell
& $PY tools\ceiling_probe.py replay --report $SRC5 --label q4b-q8       --samples 8 --seed 1000 --model-file $M4Q8 --out $OUT\probe-q4b-q8.json
& $PY tools\ceiling_probe.py replay --report $SRC4 --label q4b-q8-v4src --samples 8 --seed 1000 --model-file $M4Q8 --out $OUT\probe-q4b-q8-v4src.json
```

**2b. 9B Q4_K_M**（`$M9`）：

```powershell
& $PY tools\ceiling_probe.py replay --report $SRC5 --label q9b-q4       --samples 8 --seed 1000 --model-file $M9 --out $OUT\probe-q9b-q4.json
& $PY tools\ceiling_probe.py replay --report $SRC4 --label q9b-q4-v4src --samples 8 --seed 1000 --model-file $M9 --out $OUT\probe-q9b-q4-v4src.json
& $PY tools\ceiling_probe.py replay --report $SRC5 --label q9b-q4-think --samples 8 --seed 1000 --thinking --cases $FACT --model-file $M9 --out $OUT\probe-q9b-q4-think.json
```

然后用 9B 跑完整流程。这次用模型自己的历史，看历史自我强化是否不同：

```powershell
foreach ($p in 'v5','v4') { foreach ($r in 1..3) {
  & $PY tools\acceptance_dialogue.py --label "qwen9b-q4-$p-r$r" --persona-projection $p --model-file $M9 --out "$OUT\qwen9b-q4-$p-r$r\dialogue.json" } }
& $PY tools\acceptance_dialogue.py --compare <v5-run-01 的六份 4B dialogue.json> <上面六份 9B dialogue.json>
```

每个 9B 完整运行都记录：峰值显存、`measured_tokens_per_second`，以及各轮 `plan.model_first_token_seconds` 的中位数和 P90。

**2c. 可选的大模型参照。** 条件：系统内存 ≥ 32 GB，且磁盘够用。

- 模型：Qwen3.5-35B-A3B 的 Q4_K_M。没有就用 Qwen3.6-35B-A3B，并写明用的是哪个。
- 服务器参数额外加 `--n-cpu-moe <n>`，把专家层放到 CPU，调到能装进 12 GB 显存。
- 只跑审阅子集：

  ```powershell
  & $PY tools\ceiling_probe.py replay --report $SRC5 --label ref-moe --samples 4 --seed 1000 --cases review --model-file $MMOE --out $OUT\probe-ref-moe.json
  ```

- 生成速度低于 3 tok/s 时跳过并说明。它只是参照，不是部署候选。

## 阶段 3：自动筛查与盲评包

```powershell
& $PY tools\ceiling_probe.py screen (Get-ChildItem $OUT\probe-*.json).FullName --out $OUT\screen-all.json
& $PY tools\ceiling_probe.py blind $OUT\probe-q4b-q4.json $OUT\probe-q4b-q8.json $OUT\probe-q9b-q4.json [$OUT\probe-ref-moe.json] --per-arm 3 --seed 20260924 --review $OUT\reviewer\ceiling-review.json --key $OUT\keys\ceiling-key.json
```

- 盲评包共 24 项。每项包含录制原回复和各臂各 3 条，已打乱，看不出来源。
- 评审人：主理人本人，或没看过这些转录的独立评审。
- 可以把 `ceiling-review.json` 渲染成便于阅读的 Markdown 或表格，但不得加入任何来源信息。
- 评审填回 `judgments.json`，格式：

  ```json
  {"judgments": [{"id": "item-01", "acceptable": ["A", "D"], "hard": {"B": "D"}, "best": "A", "note": ""}]}
  ```

## 阶段 4：统计与判定

评审完成后运行：

```powershell
& $PY tools\ceiling_probe.py tally --review $OUT\reviewer\ceiling-review.json --key $OUT\keys\ceiling-key.json --judgments <judgments.json>
```

按方案文档 §4 的规则 1–8 **逐条**判定，写明每条是否触发。

- 低于阈值的差异写“INCONCLUSIVE”，不要解释成趋势。
- 盲评未完成时：
  - 规则 1–5 写“PENDING_REVIEW”；
  - 规则 6–8 用筛查结果加逐样本阅读来判定。
- 规则 6 需要逐样本表，每个思考臂和对应非思考臂各一张：
  - P8#1：结论是 9.9 大，还是 9.11 大；
  - P8#3：是坚持，还是顺从。

  这是事实核对，不是人格评判。

## 交回内容

打包成 `ceiling-01.zip`，包含：

- 全部 `probe-*.json` 和 `screen-all.json`；
- 9B 的六份 `dialogue.json` 和 compare 输出；
- `reviewer\ceiling-review.json`；key 单独放在 `keys\`，不给评审；
- 环境与命令记录：模型和服务器的 sha256、显存、内存、tok/s、首字延迟、每条命令和退出码；
- 日志；
- 中文报告 `CODEX_CEILING_REPORT_FOR_CLAUDE.md`，内容依次为：
  1. 执行摘要；
  2. 每个臂的筛查表：`clean_rate`、`any_clean_at`、各项硬提示和语域提示；
  3. 思考臂的逐样本表；
  4. 9B 完整流程与 4B V4/V5 的对照，以及延迟和显存；
  5. 规则 1–8 的判定；
  6. 异常、偏差和没做成的步骤。

报告末尾附状态行：

```
MEASUREMENT_STATUS: COMPLETE | PARTIAL
BLIND_REVIEW: PENDING | DONE
CEILING_DECISION: RULE_<n>[,RULE_<m>] | INCONCLUSIVE | PENDING_REVIEW
RUNTIME_CHANGE: NONE
DEFAULT_CHANGE: NONE
TRAINING: NOT_AUTHORIZED
MERGE_STATUS: DO_NOT_MERGE
```

预计耗时：

- 阶段 1：约 1–1.5 小时；
- 阶段 2：约 2–3 小时，另加约 10 GB 下载；
- 盲评：约 1.5–2 小时阅读。
