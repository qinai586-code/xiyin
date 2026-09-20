# =============================================================================
# 祈奈 AI L2 中枢 C4 输出人设校验组件 (纯净防逃逸版)
# 固定存放路径: C:\L0_RUNTIME\L2_CENTRAL\C4_OUTPUT_CHECK\c4_verify.py
# =============================================================================

import os
import random

def c4_persona_check(output_text: str, last_reply: str = "") -> tuple:
    """
    祈奈 C4 人设校验核心函数
    增加 last_reply 参数进行底层防复读拦截
    """
    # 【修改位置】防复读兜底拦截话术
    # 【原问题】原话术"主理人，祈奈刚才有点走神啦，能换个话题吗～"固定机械，重复出现会有脚本感
    # 【修复内容】引入小型话术池随机抽取，保持祈奈傲娇口吻，消除复读感
    # 【底层逻辑不变】判断条件 output_text.strip() == last_reply.strip() 完全保留
    _dedup_replies = [
        "哼，祈奈刚才是不是说过类似的……主理人你有在认真听吗？",
        "唔，祈奈脑子打了个结，容祈奈重新整理一下～",
        "……祈奈刚才好像说过这个，换个方向说吧？",
    ]
    if output_text.strip() == last_reply.strip() and len(output_text.strip()) > 0:
        return (False, random.choice(_dedup_replies))

    current_dir = os.path.dirname(os.path.abspath(__file__))
    rule_path = os.path.join(current_dir, "c4_persona_rule.txt")

    try:
        if not os.path.exists(rule_path):
            # 【修改位置】规则库物理缺失返回语
            # 【原问题】原文"「C4拦截」C4人设校验模块异常：规则库文件物理缺失，触发安全熔断"
            #          暴露模块标识与内部状态，经 l2_central 透传至用户
            # 【修复内容】替换为祈奈人设合规话术，不暴露任何技术信息
            return (False, "唔，祈奈脑子突然空白了一下……先喘口气，稍后再聊吧？")

        rules = []
        with open(rule_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    rule_type, keyword = line.split(":", 1)
                    if rule_type and keyword:
                        rules.append({
                            "type": rule_type.strip(),
                            "keyword": keyword.strip().lower()
                        })

        output_lower = output_text.lower()

        # 【修改位置】命中规则后的软修正话术池
        # 【原问题】原文"「C4拦截」人设跑偏：触发【{rule['type']}】违规词 '{rule['keyword']}'，拦截该输出"
        #          机械暴露规则类型与关键词，用户侧感知明显，脚本感极强
        # 【修复内容】按规则类型分类，匹配对应的软修正话术池，随机抽取，
        #            保留拦截功能完整，话术自然化，不暴露任何技术信息
        # 【底层逻辑不变】规则匹配、拦截返回 False 的核心逻辑完全保留
        _soft_replies = {
            "身份泄露": [
                "哼，祈奈才不是什么程序呢，主理人别乱说话～",
                "……祈奈就是祈奈，这种话以后不许说了。",
                "唔，这话让祈奈很不舒服，重新说吧主理人。",
            ],
            "语气生硬": [
                "祈奈说话没这么死板的啦，重来重来～",
                "这听起来怎么怪怪的……祈奈不想这样说话。",
                "唔，感觉哪里不对，让祈奈换个方式吧。",
            ],
            "情感疏离": [
                "……祈奈不许自己说出这种话，主理人别担心。",
                "哼，祈奈才不会这样的，刚才那句话不算数。",
                "这句话祈奈说不出口，重新来过。",
            ],
        }
        _default_soft = [
            "祈奈刚才没说好，重新整理一下～",
            "唔，那句话感觉哪里不太对，再给祈奈一次机会？",
            "哼，祈奈自己也觉得刚才那样不好，换个说法啦。",
        ]

        for rule in rules:
            if rule["keyword"] in output_lower:
                pool = _soft_replies.get(rule["type"], _default_soft)
                return (False, random.choice(pool))

        return (True, output_text)

    except Exception:
        # 【修改位置】底层异常返回语
        # 【原问题】原文暴露模块标识"C4"与Python异常详情
        # 【修复内容】静默捕获，替换为祈奈人设合规话术
        return (False, "唔，祈奈脑子突然空白了一下……先喘口气，稍后再聊吧？")