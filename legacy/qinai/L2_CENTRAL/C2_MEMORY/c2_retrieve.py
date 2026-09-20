# =============================================================================
# 祈奈 AI L0-L5 架构 | L2 中枢 C2 记忆桥接模块 (极简本地 RAG 模式)
# Archived predecessor: no runtime imports or management operations.
raise RuntimeError("Legacy QINAI code is archived and disabled; use the current xiyin.py entry.")
# 存放路径: C:\L0_RUNTIME\L2_CENTRAL\C2_MEMORY\c2_retrieve.py
# 运行权限: SJ_Run (仅只读)
# 核心功能: 上下文检索、小批量本地记忆读取、三语种自适应人设联动
# =============================================================================

import os
import re


def _xiyin_init_root():
    """A4/P4 (C2_MEMORY) 极薄入口加载接线：一次性显式加载便携根解析器。

    固定布局 <运行根>/xiyin_paths.py；无上溯、无旧盘符回退；不为加载路径
    启动 L2/模型；sys.modules 中已存在且 __file__ 不符的同名伪模块
    （cwd/PYTHONPATH 注入）直接拒绝。"""
    import importlib.util
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    expected = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "xiyin_paths.py")
    preloaded = sys.modules.get("xiyin_paths")
    if preloaded is not None and os.path.abspath(
            getattr(preloaded, "__file__", "")) != os.path.abspath(expected):
        raise RuntimeError("xiyin_paths pseudo-module rejected: "
                           + repr(getattr(preloaded, "__file__", None)))
    if preloaded is None:
        spec = importlib.util.spec_from_file_location("xiyin_paths", expected)
        module = importlib.util.module_from_spec(spec)
        sys.modules["xiyin_paths"] = module
        spec.loader.exec_module(module)
    return sys.modules["xiyin_paths"]


_XIYIN_ROOT = _xiyin_init_root().project_root()

# === 全域固定路径基线 (严格对齐 C盘/D盘 权限隔离) ===
# C盘：L1 正式记忆库，SJ_Run 只读，C2 唯一主读源
# P4: 主读源由单一受信运行根派生（data = L1_MEMORY）；不再硬编码盘符
_XIYIN_DATA = _xiyin_init_root().resolve_path("data")
C_MEMORY_DIR = str(_XIYIN_DATA / "passed")

# [P1修复] D盘路径对齐实际架构路径
# 原路径 D:\DL0_ARCHIVE\L1_MEMORY_CORE\neko_memory 不存在
# 实际路径为 D:\L0_VERSION_ARCHIVE\DL0_ARCHIVE\L1_MEMORY_CORE
# 该目录为历史归档区，当前标记为 OPTIONAL=False，不参与正式检索
# 如需启用需 SJ_Admin 确认并设置对应 NTFS 只读 ACL
D_MEMORY_CORE  = r"D:\L0_VERSION_ARCHIVE\DL0_ARCHIVE\L1_MEMORY_CORE"
D_MEMORY_OPTIONAL = False  # 归档区默认不接入，改为 True 需主理人确认


def _detect_language(text: str) -> str:
    """
    Function: 极简三语检测，判定输入文本主语言（中文/日文/英文）。
    Input:    text (str) — 原始用户输入字符串。
    Output:   str — "zh" | "ja" | "en" 之一。
    Depends:  re（标准库，无外部依赖）。
    Security: 纯只读操作，不修改任何状态；Unicode 范围匹配，无注入风险。
    """
    jp_chars = len(re.findall(r'[\u3040-\u309F\u30A0-\u30FF]', text))
    cn_chars = len(re.findall(r'[\u4E00-\u9FFF]', text))
    if jp_chars > cn_chars and jp_chars > 0:
        return "ja"
    elif cn_chars >= jp_chars and cn_chars > 0:
        return "zh"
    else:
        return "en"


def _get_memory_header(lang: str) -> str:
    """
    Function: 依语言返回记忆区块的人设化标题行，使记忆注入自然融入 prompt。
    Input:    lang (str) — _detect_language() 返回的语言代码。
    Output:   str — 对应语言的记忆区块标题字符串（含换行符）。
    Depends:  无外部依赖。
    Security: 纯字符串返回，无文件 I/O，无注入面。
    """
    if lang == "ja":
        return "【祈奈の過去の記憶】\n"
    elif lang == "zh":
        return "【祈奈的专属历史记忆】\n"
    else:
        return "[QINAI's Historical Memory]\n"


def _extract_keywords(text: str) -> list:
    """
    Function: 从用户输入提取有意义的词级关键词，用于记忆文件语义评分。
    Input:    text (str) — 净化后的用户输入字符串。
    Output:   list[str] — 关键词列表；jieba 可用时为精准分词，否则正则兜底。
    Depends:  jieba（可选，未安装自动降级）；re（标准库）。
    Security: 不修改文件系统；jieba ImportError 有显式兜底，不会抛出异常。
              [P1修复] 修复原字符级迭代导致语义检索完全失效的严重缺陷。
    原问题：keywords = [w for w in user_input if len(w.strip()) > 0]
            对字符串逐字符迭代，中文每个字均入列、英文每个字母均入列，
            导致关键词命中逻辑退化为单字符匹配，语义检索完全失效。
    修复策略：
      · 优先使用 jieba 中文分词（精准词语切分）
      · jieba 未安装时降级为正则提取：
          - 中文：连续 CJK 字符（2字以上），减少单字噪音
          - 英文：连续字母（2字母以上），过滤单字母
      · 两种路径均过滤空白与单字符碎片
    """
    try:
        import jieba
        words = [w.strip() for w in jieba.cut(text) if len(w.strip()) > 1]
        return words if words else [text.strip()]
    except ImportError:
        # jieba 未安装：正则兜底，仍优于字符级迭代
        words = re.findall(r'[\u4E00-\u9FFF]{2,}|[a-zA-Z]{2,}', text)
        return words if words else [text.strip()]


def c2_get_memory(user_input: str, max_memory_num: int = 5) -> str:
    """
    Function: C2 核心接口，从 L1 passed 记忆库检索与当前输入最相关的历史记忆片段。
    Input:    user_input (str) — C3 净化后的用户输入；
              max_memory_num (int) — 最多返回的记忆条目数，默认 5。
    Output:   str — 格式化记忆区块字符串（含人设标题），供 C5 prompt 注入；
              空字符串表示无可用记忆或记忆目录不存在。
    Depends:  os、re；_extract_keywords、_detect_language、_get_memory_header（本模块内部）；
              jieba（可选分词）；路径常量 C_MEMORY_DIR / D_MEMORY_CORE。
    Security: 严格只读 open()；symlink 拦截（islink + commonpath 双重守卫）防路径逃逸；
              所有文件异常静默跳过，确保 C2→C5 链路永不因单文件损坏而熔断。
    """
    if not user_input or not user_input.strip():
        return ""

    try:
        paths = _xiyin_init_root()
        paths._inside(paths.project_root(), paths.Path(C_MEMORY_DIR))
    except (ValueError, OSError):
        return ""

    memory_files = []

    # 1. 扫描 C 盘正式记忆库（主读源，SJ_Run 只读）
    if os.path.exists(C_MEMORY_DIR):
        for f in os.listdir(C_MEMORY_DIR):
            if f.endswith(".txt"):
                memory_files.append(os.path.join(C_MEMORY_DIR, f))

    # 2. 扫描 D 盘归档记忆库（可选，默认关闭）
    if D_MEMORY_OPTIONAL and os.path.exists(D_MEMORY_CORE):
        for f in os.listdir(D_MEMORY_CORE):
            if f.endswith(".txt") or f.endswith(".md"):
                memory_files.append(os.path.join(D_MEMORY_CORE, f))

    if not memory_files:
        return ""

    # 3. 极简本地 RAG 评分逻辑（零依赖，替代 Faiss/VectorDB）
    # [P1修复] 调用修复后的 _extract_keywords，不再逐字符迭代
    keywords = _extract_keywords(user_input)
    scored_memories = []

    _c_memory_real = os.path.realpath(C_MEMORY_DIR)
    _d_memory_real = os.path.realpath(D_MEMORY_CORE) if D_MEMORY_OPTIONAL else None

    for filepath in memory_files:
        try:
            # 防符号链接越权：拒绝软链接及逃逸出记忆根目录的路径
            if os.path.islink(filepath):
                continue
            try:
                _real = os.path.realpath(filepath)
                _root = _c_memory_real if filepath.startswith(C_MEMORY_DIR) else _d_memory_real
                if _root is None or os.path.commonpath([_root, _real]) != _root:
                    continue
            except ValueError:
                continue
            # 严格只读模式打开，防止越权写入
            with open(filepath, "r", encoding="utf-8") as file:
                content = file.read().strip()
                if not content:
                    continue

                score = 0
                content_lower = content.lower()

                # 基础时间权重：以文件修改时间戳为基准，越新的文件基础分越高
                score += os.path.getmtime(filepath) / 1000000

                # 语义命中提权：关键词匹配
                for k in keywords:
                    if k.lower() in content_lower:
                        score += 10000  # 命中核心关键词大幅提高优先级

                scored_memories.append((content, score))
        except Exception:
            # 静默忽略权限不足或损坏的文件，确保 C2→C5 链路不熔断
            continue

    if not scored_memories:
        return ""

    # 按关联度与时间综合得分降序排序，提取小批量记忆上限
    scored_memories.sort(key=lambda x: x[1], reverse=True)
    top_memories = [m[0] for m in scored_memories[:max_memory_num]]

    # 翻转数组：将最旧的记忆放前面，最新的记忆放末尾
    # 贴合大模型 Transformer 注意力机制阅读习惯
    top_memories.reverse()

    # 4. 人设封装与最终输出
    lang = _detect_language(user_input)
    header = _get_memory_header(lang)
    merged_memory = "\n---\n".join(top_memories)

    return f"{header}{merged_memory}"


if __name__ == "__main__":
    print("=== C2_MEMORY_BRIDGE 链路测试 ===")
    test_input = "祈奈，还记得我们上次关于 5070 Ti 的约定吗？"
    print(c2_get_memory(test_input))
