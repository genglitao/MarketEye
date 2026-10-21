# -*- coding: utf-8 -*-
"""TC-UI-15：`--selftest` 自检可运行且数值与 SDD 基线一致（P1，覆盖 T012）。

功能路径：折叠轮播 → 轮播展示（自检路径）
操作区域：无界面，命令行输出（白盒）

说明：本用例非界面交互，不产生窗口截图；证据为自检原文，落盘到
screenshots/TC-F-14-selftest-<时间戳>.txt。

断言基准（SDD §3.5.2 / §3.7.1，150% DPI、逻辑宽 500）：
  lx=152、rx=385、avail=233、派生门槛 106、名称预算 157。
"""
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uikit

CASE = "TC-F-14"
HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = uikit.PROJ
PY = sys.executable


def main():
    R = uikit.Report(CASE, "自检段可运行且数值与 SDD 基线一致")
    print("  step1 以 --selftest 运行被测程序")
    t0 = time.time()
    p = subprocess.run([PY, os.path.join(PROJ, "ticker.pyw"), "--selftest"],
                       cwd=PROJ, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=180)
    out = (p.stdout or "") + (p.returncode and (p.stderr or "") or "")
    cost = time.time() - t0
    stamp = time.strftime("%Y%m%d%H%M%S")
    log = os.path.join(HERE, "..", "screenshots", "TC-F-14-selftest-%s.txt" % stamp)
    with open(log, "w", encoding="utf-8") as f:
        f.write(out)
    print("    证据 screenshots/TC-F-14-selftest-%s.txt  用时 %.2fs" % (stamp, cost))

    R.check("自检进程正常退出（退出码 0）", p.returncode == 0,
            "rc=%s stderr=%s" % (p.returncode, (p.stderr or "").strip()[:200]))
    R.check("自检无未捕获异常", "Traceback" not in out)

    print("  step2 校验轮播段的几何数值")
    line = ""
    for ln in out.splitlines():
        if "[marq  ]" in ln and "avail" in ln:
            line = ln.strip()
            break
    R.check("输出含轮播几何段", bool(line), line or "未找到")

    def num(key):
        m = re.search(key + r"=(-?\d+)", line)
        return int(m.group(1)) if m else None

    R.check("lx = 152（标题右侧 px(8)）", num("lx") == 152, num("lx"))
    R.check("rx = 385（时钟左侧留 px(10)）", num("rx") == 385, num("rx"))
    R.check("avail = 233（可用宽）", num("avail") == 233, num("avail"))
    R.check("派生门槛 = 106（两字名称+分隔+涨跌幅）",
            re.search(r"门槛\s*(\d+)", line) is not None
            and int(re.search(r"门槛\s*(\d+)", line).group(1)) == 106,
            (re.search(r"门槛\s*(\d+)", line) or [None, "未找到"])[1]
            if re.search(r"门槛\s*(\d+)", line) else "未找到")
    R.check("该宽度下判定为渲染", "渲染" in line, line[-12:])

    print("  step3 校验清单与指数类判定")
    m = re.search(r"清单 (\d+) 条", out)
    R.check("清单条数与当前配置的「宽基指数」分组一致", bool(m), m.group(0) if m else "未找到")
    if m:
        import json
        with open(os.path.join(PROJ, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        want = 0
        for g in cfg.get("groups") or []:
            if isinstance(g, dict) and g.get("name") == "宽基指数":
                want = len([i for i in (g.get("items") or []) if isinstance(i, dict)])
                break
        R.check("清单条数 = 分组标的数（%d）" % want, int(m.group(1)) == want,
                "自检 %s vs 配置 %d" % (m.group(1), want))

    pairs = re.findall(r"指数类=(True|False)\s+预期=(True|False)\s+(OK|FAIL)", out)
    R.check("指数类判定样例全部匹配预期（5 例）", len(pairs) == 5 and
            all(a == b and c == "OK" for a, b, c in pairs), pairs)

    print("  step4 校验名称预算与列布局段")
    R.check("名称预算 157", "名称预算 157" in out, "未找到" if "名称预算" not in out else "存在")
    R.check("四字名称在预算内未截断（中证A500 原样输出）",
            "名称预算 157: 中证A500 → 中证A500" in out)
    R.check("列布局段正常输出（未因自检改动而中断）",
            "W= 420 →" in out or "W=420 →" in out)

    print("  自检总用时 %.2fs" % cost)
    uikit.finish(R.close())


if __name__ == "__main__":
    main()
