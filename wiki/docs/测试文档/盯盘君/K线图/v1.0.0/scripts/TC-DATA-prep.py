# -*- coding: utf-8 -*-
"""TC-DATA-prep：测试前备份真实 config.json / position.json 并记录 md5。"""
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
os.makedirs(BAK, exist_ok=True)

rec = {}
for name in ("config.json", "position.json"):
    src = os.path.join(PROJ, name)
    dst = os.path.join(BAK, name)
    if os.path.exists(src):
        shutil.copy2(src, dst)
        with open(src, "rb") as f:
            rec[name] = hashlib.md5(f.read()).hexdigest()
        print("备份 %s → %s (md5=%s)" % (src, dst, rec[name]))
    else:
        rec[name] = None
        print("%s 不存在，跳过备份" % src)

with open(os.path.join(HERE, "_tc_md5.json"), "w", encoding="utf-8") as f:
    json.dump(rec, f, ensure_ascii=False, indent=2)
print("TC-DATA-prep 完成")
