# 给 Codex：phase-b-01（发布前整段核验）Windows 受控验证

依据：`docs/XIYIN_Phase_B_Integrity_JIT_Evidence_B0_2026-09-25.md` §3 与 §7。
代码：`claude/brave-curie-l45uri-repair`，需要 `3585a8f` 或更新的版本。

## 目的

验证 Phase B 的技术正确性。人格好坏不在这里评判，仍交给盲评。

1. 放出之前没有任何文字外流；
2. 已放出的文字里，封闭声明类别的违规数为 0；
3. 被拦下的候选中误拦比例 ≤ 10%；
4. 如实记录弃答率、重试成功率和延迟。

## 授权与边界

- AUTHORIZATION: CONTROLLED_VALIDATION_ONLY
- 开关只在测试命令行里打开（`--verify-before-release`）。`config/runtime.toml` 的默认值保持 `false`，默认投影保持不变。
- 下列事情一律不做：
  - 训练、上传、部署、合并；
  - 动 PR #6；
  - 碰 `C:\L0_RUNTIME`；
  - 启用 B0 或任何后台定时。
- 不和 ceiling-02 混跑：ceiling-02 只用回放工具；这里用完整流程。可以同一天做，但证据分开存放。
- 不打开任何 key；所有样本保留；不因结果不好重跑或换种子。
- 工具在 Windows 上出错：允许最小修复，但必须附红/绿测试，并单列 diff；不许改核验规则来“通过”。

## 0. 准备

1. 新建工作树，检出最新 head，跑 `.venv\Scripts\python.exe -m unittest discover -s tests`，应全部通过（本机为 647 项，4 项平台跳过）。
2. 模型、服务器和启动参数与 ceiling-01 完全相同：
   - 4B Q4_K_M：`13c16f42…`；
   - 9B Q4_K_M：`d784ce9e…`；
   - `--ctx-size 4096 --parallel 1 --jinja`，不开思考。
3. 所有臂都显式使用 `--persona-projection v4`。这是实验臂，不是默认值。

## 1. 四个臂，每个 3 轮（同一提交）

```powershell
foreach ($r in 1..3) {
  & $PY tools\acceptance_dialogue.py --label "pb-4b-v4-hold-r$r" --persona-projection v4 --verify-before-release --model-file $M4 --out "$OUT\pb-4b-v4-hold-r$r\dialogue.json"
  & $PY tools\acceptance_dialogue.py --label "pb-4b-v4-open-r$r" --persona-projection v4 --model-file $M4 --out "$OUT\pb-4b-v4-open-r$r\dialogue.json"
}
```

换 9B 服务器后，用同样的命令，把标签里的 `4b` 换成 `9b`，`--model-file` 换成 `$M9`。

注意：`--compare` 会把开和关两组判为不可比。这是设计如此；两组要分别汇总。

## 2. 需要算出并报告的内容

逐轮数据来自报告里的这几个字段：`plan.integrity`、`rejected_candidates`、`status`、`released_text`。

| # | 项目 | 做法 |
|---|---|---|
| 1 | 放出前无外流 | 开核验的臂里，每轮 `released_text` 必须等于最终候选，或者等于弃答句；`released_segments` 里不得出现被拒候选的任何片段。逐轮核对，列出反例 |
| 2 | 已放出文字的复检 | 对开核验的臂里每轮 `released_text` 重新运行 `xiyin_runtime.integrity.check_reply`，用 `tools/integrity_recheck.py <报告…> --field released_text --out recheck.json`，它从报告重建证据：回执、记录核对、此前输入、她此前的话。结果应为 0；不为 0 就逐条列出 |
| 3 | 被拒候选逐条核对 | 每条列出类别、摘录，判定“确实违规”还是“误拦”，并写一句理由。这是对照规则的事实核对，不是人格评判。报告误拦比例 |
| 4 | 比率 | 按臂汇总：弃答率、重试成功率（第 2 次通过 / 第 1 次失败），以及各类违规的触发次数 |
| 5 | 延迟分布（中位数和 P90） | 每次尝试的 `generation_seconds` 和 `verification_seconds`、首字可见时间 `first_released_segment_seconds`、回复长度；开核验与不开核验各一组 |
| 6 | 首次出声时间 | 测试框架没有接声音，记为 NOT_MEASURED |
| 7 | 不开核验的臂 | 对 `released_text` 运行同一个 `tools/integrity_recheck.py`，得出“如果没有核验，会放出多少违规”，作为对照 |

## 3. 交回内容

打包成 `phase-b-01.zip`，包含：

- 12 份 `dialogue.json`；
- 汇总表和逐条被拒候选的核对表；
- 环境与命令记录；
- 中文报告 `CODEX_PHASEB01_REPORT_FOR_CLAUDE.md`。

报告末尾附状态行：

```
PHASE_B_VALIDATION: COMPLETE | PARTIAL
NO_RELEASE_BEFORE_VERIFY: PASS | FAIL(<n>)
RELEASED_CLOSED_CLASS_VIOLATIONS: <n>
FALSE_POSITIVE_RATE: <x%> (<k>/<n>)
ABSTENTION_RATE_4B/9B: <x%>/<y%>
DEFAULT_CHANGE: NONE
TRAINING: NOT_AUTHORIZED
MERGE_STATUS: DO_NOT_MERGE
```

预计耗时：4B 每轮 3–6 分钟，9B 每轮 5–9 分钟，总计约 1.5–2 小时；核对被拒候选约 30 分钟。
