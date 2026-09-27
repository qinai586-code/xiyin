# 证据清单：2026-09-26 Windows 评测（代码 55e61f8）

用途：供独立复审使用，只读。指令见 `docs/XIYIN_Codex_Cloud_ReReview_Instructions_2026-09-27.md`。

| 文件 | 字节 | sha256 | 来源 |
|---|---|---|---|
| `ceiling-02-55e61f8.zip` | 2609906 | `69852d7f87c9e4da5fc23e0a31551e45c55997b92bcd6f0c96600d02358dfa0e` | 主理人 Windows 运行，2026-09-26（C:\\XIYIN\\evidence\\results-55e61f8） |
| `phase-b-01-55e61f8.zip` | 1836988 | `e9ce2547b74640d180d76c5eb95400737d74ccc6eddb0787081f773af1d59240` | 同上 |
| `CEILING02_BLIND_REVIEW_ONLY.zip` | 58955 | `dbcdabc4998045a4cedc66e2576c12ebbd0445da3ad375881ba797db66906cbd` | 同上；只有题目，不含答案 |
| `ceiling-01.zip` | 4850620 | `aa72e9e9e0deba9552987f83e46100bba7ed3f5c447640882fb8ad201e92e4d0` | Codex 本机 ceiling-01 交回包，2026-09-25 |
| `v5-run-01.zip` | 1839184 | `a8fdbc2b23a39f1954a0b24191574cf8d999f429e3fdcf996a86dc8830431fe6` | Codex 本机 V5 运行交回包，2026-09-24；**已去掉 keys/**，见下 |
| `AI_Definition__Rulings.md` | 65848 | `64022d26e79e3953eab67f84b071e4bb878a74fddcd8a2293bf440282ba22972` | 主理人 AI 定义最新版（仓库 legacy/ 下的是旧版） |

**改动说明：**
- `v5-run-01.zip` 的原包 sha256 是 `2bd3c75dca20b9cf627bdb45f7f2aecbb851a808595392d3fdbd10570d30a7e4`。原包里有盲评答案目录 `v5-run-01/keys/`（`key-r1.json`、`key-r2.json`、`key-r3.json`）。按规则，答案不进仓库，所以重新打包时去掉了这个目录，其余 109 个文件原样保留。
- 其他文件都是原样复制。

**还需要主理人补上：**
- `XIYIN_Character_Bible_v0.2_Integrated_Candidate_2026-09-20_CN.md`，以及两份 v0.1 人物设定；
- `FAILURE_STATEMENT.md`（模板见复审指令第一部分）。

**不在这里，也不应放进来：**
- `ceiling-02-55e61f8\keys\`（本次盲评答案，留在主理人本机）；
- `C:\L0_RUNTIME` 里的任何内容；
- 任何凭据。
