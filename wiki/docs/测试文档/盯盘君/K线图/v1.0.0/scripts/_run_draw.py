# -*- coding: utf-8 -*-
"""画线增量轮执行器：顺序跑 TC-UI-08~11，日志留档 _run_draw.log。

前置/收尾各执行一次 TC-DATA-prep / TC-DATA-cleanup（沙箱 md5 对账）。
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
CASES = ["TC-UI-08.py", "TC-UI-09.py", "TC-UI-10.py", "TC-UI-11.py"]


def run(name):
    print("=" * 70)
    print(">>> " + name)
    t0 = time.time()
    p = subprocess.run([PY, os.path.join(HERE, name)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       cwd=HERE, timeout=600)
    dt = time.time() - t0
    print(p.stdout)
    if p.stderr:
        print("[stderr]", p.stderr[-2000:])
    print("<<< %s 退出码 %d  用时 %.1fs" % (name, p.returncode, dt))
    return p.returncode


def main():
    log = open(os.path.join(HERE, "_run_draw.log"), "w", encoding="utf-8")
    _orig = sys.stdout

    class Tee:
        def write(self, s):
            _orig.write(s)
            log.write(s)

        def flush(self):
            _orig.flush()
            try:
                log.flush()
            except ValueError:
                pass                       # 解释器退出时 log 已关闭

    sys.stdout = Tee()
    prep = subprocess.run([PY, os.path.join(HERE, "TC-DATA-prep.py")],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=HERE, timeout=60)
    print("[prep]", prep.stdout.strip()[-400:])
    fails = []
    for c in CASES:
        try:
            if run(c):
                fails.append(c)
        except subprocess.TimeoutExpired:
            fails.append(c + " (timeout)")
    cln = subprocess.run([PY, os.path.join(HERE, "TC-DATA-cleanup.py")],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", cwd=HERE, timeout=60)
    print("[cleanup]", cln.stdout.strip()[-400:])
    print("=" * 70)
    print("画线增量轮完成：失败脚本 %s" % (fails or "无"))
    log.close()
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
