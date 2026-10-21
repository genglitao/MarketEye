# -*- coding: utf-8 -*-
"""TC-DATA-cleanup：比对用户配置是否被改动，并清理沙箱与备份。

正常情况下测试全程只写沙箱，本脚本只在检测到真实 config.json 被改动时才还原。
"""
import filecmp
import os
import shutil

import uikit


def restore_if_changed(path):
    bak = path + ".tcbak"
    if not os.path.exists(bak):
        print("  无备份，跳过：%s" % os.path.basename(path))
        return
    if os.path.exists(path) and filecmp.cmp(path, bak, shallow=False):
        os.remove(bak)
        print("  %s 未被改动，删除备份" % os.path.basename(path))
        return
    shutil.move(bak, path)
    print("  !! %s 被改动，已还原为用户原配置" % os.path.basename(path))


def main():
    print("[TC-DATA-cleanup]")
    restore_if_changed(uikit.CONFIG)
    restore_if_changed(uikit.POS_FILE)
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("_tc_config.json", "_tc_position.json"):
        p = os.path.join(here, name)
        if os.path.exists(p):
            os.remove(p)
            print("  清理沙箱 %s" % name)
    print("[TC-DATA-cleanup] 完成")


if __name__ == "__main__":
    main()
