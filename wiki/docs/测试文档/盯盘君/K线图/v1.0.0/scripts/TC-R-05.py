# -*- coding: utf-8 -*-
"""TC-R-05：save_json 返回布尔后既有调用点兼容回归（importlib 白盒直调）。

验证点（SDD §4 代码位置表「§3.6 写盘反馈」）：
1. save_json 成功路径返回 True（首次写与改写各一次，顺带验证 .bak 底牌）；
2. 失败路径（非法目录）返回 False 且不抛异常；
3. save_drawings 透传布尔；
4. selftest 全量复跑退出码 0（既有 17 处调用点行为不变的旁证，
   由 _run_draw 轮与 TC-UI-regress.py 另行覆盖）。
"""
import importlib.util
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", "..", "..", ".."))
TICKER = os.path.join(ROOT, "ticker.pyw")

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}" + (f"  <- {detail}" if detail else ""))
    else:
        failed += 1
        print(f"  [FAIL] {name}  <- {detail}")


spec = importlib.util.spec_from_file_location("tkw_mod", TICKER)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

d = tempfile.mkdtemp()
p = os.path.join(d, "cfg.json")
r1 = m.save_json(p, {"groups": []})
check("save_json 首次写返回 True", r1 is True, repr(r1))
r2 = m.save_json(p, {"groups": [], "kline": {}})
check("save_json 改写返回 True（.bak 生成）",
      r2 is True and os.path.exists(p + ".bak"), repr(r2))
r3 = m.save_json(os.path.join(d, "no", "such", "dir", "x.json"), {"a": 1})
check("save_json 非法路径返回 False 且不抛异常", r3 is False, repr(r3))
r4 = m.save_drawings({"groups": []}, {"sh600519": {"day": []}})
check("save_drawings 透传布尔（成功 True）", r4 is True, repr(r4))
# 失败注入：CONFIG_FILE 重定向到不存在的深层目录（save_drawings 内部走 save_json）
_orig_cfg = m.CONFIG_FILE
m.CONFIG_FILE = os.path.join(d, "no", "such", "dir", "cfg.json")
try:
    r5 = m.save_drawings({"groups": []}, {"sh600519": {"day": []}})
finally:
    m.CONFIG_FILE = _orig_cfg
check("save_drawings 失败透传 False（不抛异常）", r5 is False, repr(r5))

# 旁证：selftest 全量复跑
st = subprocess.run([sys.executable, TICKER, "--selftest"], capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=120)
check("selftest 退出码 0（既有调用点行为不变旁证）", st.returncode == 0,
      f"rc={st.returncode}")

print(f"TC-R-05 完成：{passed} PASS / {failed} FAIL")
sys.exit(1 if failed else 0)
