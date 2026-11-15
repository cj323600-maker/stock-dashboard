#!/usr/bin/env python3
"""백테스트 결과 검증. run_backtest.py와 다른 방식(보유 여부 배열 + 일별 배수 곱)으로 다시 계산해 대조한다."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
data = {t["symbol"]: t for t in json.loads((ROOT / "data" / "prices.json").read_text(encoding="utf-8"))["tickers"]}
res = json.loads((ROOT / "backtest" / "results.json").read_text(encoding="utf-8"))
F = res["fee"]
errs, checks = [], 0


def ok(cond, msg):
    global checks
    checks += 1
    if not cond:
        errs.append(msg)


def positions(t, rule, s):
    """pos[i] = i일 시가 이후 보유 여부. i일 신호는 i+1일 시가에 반영."""
    n = len(t["close"]); pos = [0] * n; entry = None
    for i in range(s, n):
        prev = pos[i - 1] if i > s else 0
        if i == s:
            pos[i] = 1 if rule == "hold" else 0
        else:
            j = i - 1  # 어제 종가 신호
            if rule == "hold":
                pos[i] = 1
            elif rule == "trend":
                pos[i] = 1 if t["ma20"][j] > t["ma60"][j] else 0
            else:
                if prev == 0:
                    pos[i] = 1 if t["rsi14"][j] <= 30 else 0
                else:
                    stop = t["close"][j] / entry - 1 <= res["stop"]
                    pos[i] = 0 if (t["rsi14"][j] >= 70 or stop) else 1
        if pos[i] == 1 and prev == 0:
            entry = t["open"][i]
    return pos


for row in res["tickers"]:
    t = data[row["symbol"]]; o, c = t["open"], t["close"]
    s = t["dates"].index(row["start"]); n = len(c)
    ok(t["ma60"][s - 1] is not None and t["ma60"][s - 2] is None, f"{row['symbol']} 시작일 오류")
    for rule, r in row["results"].items():
        pos = positions(t, rule, s)
        eq, curve, buys, held = 1.0, [], 0, 0
        for i in range(s, n):
            prev = pos[i - 1] if i > s else 0
            if prev == 1 and pos[i] == 1:
                eq *= c[i] / c[i - 1]
            elif prev == 0 and pos[i] == 1:
                eq *= (1 - F) * c[i] / o[i]; buys += 1
            elif prev == 1 and pos[i] == 0:
                eq *= o[i] / c[i - 1] * (1 - F)
            held += pos[i]
            curve.append(eq)
        if pos[n - 1] == 1:
            eq *= 1 - F; curve[-1] = eq
        tag = f"{row['symbol']} {rule}"
        ok(abs(eq - r["final"]) < 2e-6, f"{tag} 최종값 {r['final']} vs {eq:.6f}")
        ok(len(curve) == len(r["equity"]) and all(abs(a - b) < 2e-6 for a, b in zip(curve, r["equity"])), f"{tag} 일별 자산 불일치")
        ok(buys == r["trades"], f"{tag} 거래 수 {r['trades']} vs {buys}")
        ok(abs(held / (n - s) - r["exposure"]) < 2e-6, f"{tag} 보유비중 불일치")
        peak, mdd = 0, 0
        for e in curve:
            peak = max(peak, e); mdd = min(mdd, e / peak - 1)
        ok(abs(mdd - r["mdd"]) < 2e-6, f"{tag} 최대낙폭 불일치")
        ok(abs(sum(1 for x in r["trade_list"] if x["ret"] > 0) - r["wins"]) == 0, f"{tag} 승 수 불일치")
        prod = 1.0
        for x in r["trade_list"]:
            prod *= 1 + x["ret"]
        ok(abs(prod - r["final"]) < 2e-5, f"{tag} 거래별 수익률 곱 {prod:.6f} vs 최종 {r['final']}")
    h = row["results"]["hold"]["final"]
    ok(abs(h - (1 - F) ** 2 * c[-1] / o[s]) < 2e-6, f"{row['symbol']} 보유 공식 불일치")

if errs:
    print(f"검증 실패 {len(errs)}건 / {checks}건"); [print(" -", e) for e in errs[:20]]; sys.exit(1)
print(f"백테스트 검증 통과: 검사 {checks}건, 오류 0건")
