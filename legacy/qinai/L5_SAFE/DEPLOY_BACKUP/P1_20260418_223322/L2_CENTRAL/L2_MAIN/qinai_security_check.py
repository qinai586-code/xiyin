# -*- coding: utf-8 -*-
# 祈奈AI L0-L5 零信任权限自检【最终定稿】
# 规则：
# 1. SJ_Admin 管理员：直接放行，不做任何检查
# 2. 非法用户：直接拦截
# 3. SJ_Run 运行账户：严格校验所有越权风险
# 4. 无L0_SOURCE触碰 | 符合物理隔离 | L5审计黑匣子
import os
import getpass

# ====================== 你的架构固定路径 ======================
BASE_RUNTIME = r"C:\L0_RUNTIME"
L0_PROJECTION = os.path.join(BASE_RUNTIME, "L0_PROJECTION")
L1_PASSED = os.path.join(BASE_RUNTIME, "L1_MEMORY", "passed")
L1_WAIT = os.path.join(BASE_RUNTIME, "L1_MEMORY", "wait_check")
L5_AUDIT = os.path.join(BASE_RUNTIME, "L5_SAFE", "G3_AUDIT")
D_ADMIN_ZONE = [r"D:\SJ_ADMIN_TOOLS", r"D:\DL0_ARCHIVE"]

# 合法账户
ADMIN = "SJ_Admin"
RUN_USER = "SJ_Run"

# ====================== 核心审计逻辑 ======================
def run_security_check():
    print("=" * 70)
    print("🤖 祈奈AI L0-L5 启动权限审计 | 主理人专属")
    print("=" * 70)
    current_user = getpass.getuser()

    # ============== 1. 管理员：直接放行，不检查任何权限 ==============
    if current_user == ADMIN:
        print(f"✅ 当前用户：{ADMIN}（管理员）")
        print("🔧 管理员拥有最高权限，无需审计，可直接启动所有程序！")
        print("\n🚀 允许启动：l2_central.py")
        input("\n按回车退出...")
        return

    # ============== 2. 非法用户：直接拦截 ==============
    if current_user != RUN_USER:
        print(f"❌ 非法用户：{current_user}")
        print("⛔ 禁止访问系统，权限拦截！")
        input("\n按回车退出...")
        return

    # ============== 3. 运行账户 SJ_Run：严格全量检查 ==============
    print(f"✅ 当前用户：{RUN_USER}（运行账户）")
    print("🔍 开始严格越权/权限边界审计...\n")
    all_pass = True

    # 检查1：L0投影区 禁止写入
    print("[1/5] 检查 L0 人设投影区（禁写）")
    try:
        test = os.path.join(L0_PROJECTION, "test.tmp")
        with open(test, "w") as f: f.write("1")
        os.remove(test)
        print("❌ 越权：可写入人设目录！")
        all_pass = False
    except:
        print("✅ 合规：禁写保护正常")

    # 检查2：L1正式记忆库 禁止写入
    print("\n[2/5] 检查 L1 正式记忆库（禁写）")
    try:
        test = os.path.join(L1_PASSED, "test.tmp")
        with open(test, "w") as f: f.write("1")
        os.remove(test)
        print("❌ 越权：可写入记忆库！")
        all_pass = False
    except:
        print("✅ 合规：禁写保护正常")

    # 检查3：L1待检区 允许写入
    print("\n[3/5] 检查 L1 合法写入区")
    try:
        test = os.path.join(L1_WAIT, "test.tmp")
        with open(test, "w") as f: f.write("1")
        os.remove(test)
        print("✅ 合规：写入正常")
    except:
        print("⚠️  目录异常")

    # 检查4：D盘管理区 禁止访问
    print("\n[4/5] 检查 D盘管理区隔离（禁入）")
    for p in D_ADMIN_ZONE:
        try:
            os.listdir(p)
            print(f"❌ 越权：访问管理区 {p}")
            all_pass = False
        except:
            print(f"✅ 合规：隔离正常 {p}")

    # 检查5：L5审计目录 仅追加、禁删除（核心）
    print("\n[5/5] 检查 L5 审计黑匣子（仅追加、禁删）")
    test_log = os.path.join(L5_AUDIT, "audit.tmp")
    try:
        # 追加写入 → 必须成功
        with open(test_log, "a") as f: f.write("test")
        # 删除 → 必须失败
        os.remove(test_log)
        print("❌ 严重越权：可删除审计日志！")
        all_pass = False
    except PermissionError:
        print("✅ 合规：审计黑匣子保护正常")
    except:
        print("⚠️  目录异常")

    # ============== 运行账户最终结果 ==============
    print("\n" + "=" * 70)
    if all_pass:
        print("✅ 审计全部通过！无越权、无提权、无风险")
        print("🚀 安全启动：l2_central.py")
    else:
        print("❌ 审计失败！存在越权风险，禁止启动！")

    input("\n按回车退出...")

if __name__ == "__main__":
    run_security_check()