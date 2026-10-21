# -*- coding: utf-8 -*-
"""TC-DATA-prep：备份用户配置（安全网），并准备沙箱配置。

执行顺序：本脚本 → 各 TC-* 脚本 → TC-DATA-cleanup.py。
隔离机制：uikit.Harness 会把被测程序的 CONFIG_FILE / POS_FILE 指向
`scripts/_tc_config.json` / `_tc_position.json`，测试读写全部落在沙箱，
不会改动用户真实配置；本脚本只做一次备份，便于人工比对。
重复执行安全：已存在备份时不覆盖。
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit


def backup(path):
    bak = path + ".tcbak"
    if os.path.exists(bak):
        print("  已存在备份，跳过：%s" % os.path.basename(bak))
        return
    if os.path.exists(path):
        shutil.copy2(path, bak)
        print("  备份 %s → %s" % (os.path.basename(path), os.path.basename(bak)))


def main():
    print("[TC-DATA-prep] 项目目录 %s" % uikit.PROJ)
    backup(uikit.CONFIG)
    backup(uikit.POS_FILE)

    # 沙箱配置：测试夹具基线（宽 500 / 间隔 3 秒 / 宽基指数 4 条 / 自选 3 条）
    sandbox = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tc_config.json")
    uikit.CFG[0] = sandbox
    uikit.write_cfg(uikit.fix_base())
    uikit.CFG[0] = uikit.CONFIG
    print("  沙箱配置已就绪：scripts/_tc_config.json（测试不写真实 config.json）")
    print("[TC-DATA-prep] 完成")


if __name__ == "__main__":
    main()
