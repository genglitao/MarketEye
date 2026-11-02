# -*- coding: utf-8 -*-
"""全量顺序执行 K 线 TC 脚本，汇总每条用例的 PASS/FAIL。

用法：python _run_all.py            # 全量
      python _run_all.py UI-01 UI-02  # 只跑指定
脚本本身不产生截图，只跑并汇总；退出码 = 失败用例数（0 为全绿）。
"""
import io
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
ORDER = ["API-01", "API-02", "UI-01", "UI-02", "UI-03", "UI-04", "UI-05",
         "UI-06", "UI-07", "regress"]
want = sys.argv[1:] or ORDER

log = []
fails = 0
t_all = time.time()
for key in want:
    name = "TC-UI-regress.py" if key == "regress" else "TC-%s.py" % key
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        print("!! 缺脚本 %s" % name)
        continue
    t0 = time.time()
    p = subprocess.run([PY, path], cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
    out = (p.stdout or "") + (p.stderr or "")
    log.append(out)
    nf = out.count("[FAIL]")
    fails += nf
    print("== %-8s %5.1fs  失败 %d  退出码 %d" % (key, time.time() - t0, nf,
                                                p.returncode))
    for line in out.splitlines():
        if "[FAIL]" in line:
            print("   " + line.strip())

print("-" * 62)
print("总耗时 %.1fs，失败断言 %d 条" % (time.time() - t_all, fails))
with io.open(os.path.join(HERE, "_run_all.log"), "w", encoding="utf-8") as f:
    f.write("\n\n".join(log))
sys.exit(fails)
