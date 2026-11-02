# -*- coding: utf-8 -*-
"""TC-DATA-cleanup：测试后校验真实配置未被污染（md5 比对），必要时还原，
并清理沙箱文件。"""
import hashlib
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = HERE
for _ in range(9):
    if os.path.exists(os.path.join(PROJ, "ticker.pyw")):
        break
    PROJ = os.path.dirname(PROJ)
BAK = os.path.join(HERE, "_tc_backup")


def md5(p):
    with open(p, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


with open(os.path.join(HERE, "_tc_md5.json"), encoding="utf-8") as f:
    rec = json.load(f)

dirty = False
for name, old in rec.items():
    src = os.path.join(PROJ, name)
    if old is None:
        continue
    if not os.path.exists(src):
        print("!! %s 测试后丢失，从备份还原" % name)
        shutil.copy2(os.path.join(BAK, name), src)
        dirty = True
        continue
    new = md5(src)
    if new != old:
        print("!! %s 在测试期间被改动（md5 %s → %s），从备份还原" % (name, old, new))
        shutil.copy2(os.path.join(BAK, name), src)
        dirty = True
    else:
        print("ok %s 未被测试触碰（md5 一致）" % name)

if not dirty:
    print("全部真实数据文件零改动 ✓")
else:
    print("已从备份还原（存在被改动的文件）")

# 清理沙箱
for name in ("_tc_config.json", "_tc_position.json", "_tc_md5.json"):
    p = os.path.join(HERE, name)
    if os.path.exists(p):
        os.remove(p)
if os.path.isdir(BAK):
    shutil.rmtree(BAK, ignore_errors=True)
print("TC-DATA-cleanup 完成")
