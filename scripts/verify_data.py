#!/usr/bin/env python3
"""data/prices.json 검증. fetch_data.py와 다른 방식으로 지표를 다시 계산해 대조한다.

하나라도 어긋나면 종료 코드 1로 끝나며, 자동 갱신 워크플로는 그 데이터를 올리지 않는다.
"""
import bisect
import itertools
import json
import math
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
errors, warnings, checks = [], [], 0


def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        errors.append(msg)


def close_to(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def months_back(d, m):
    total = d.year * 12 + (d.month - 1) - m
    y, mo = divmod(total, 12)
    mo += 1
    last = (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, mo, min(d.day, last))


def verify(t):
    s, sym = t["summary"], t["symbol"]
    dates = [date.fromisoformat(x) for x in t["dates"]]
    o, h, l, c = t["open"], t["high"], t["low"], t["close"]
    n = len(dates)
    for key in ("open", "high", "low", "close", "volume", "ma20", "ma60", "ma120", "rsi14"):
        check(len(t[key]) == n, f"{sym} {key} 길이 불일치")
    check(all(a < b for a, b in zip(dates, dates[1:])), f"{sym} 날짜가 오름차순이 아님")
    check(all(d.weekday() < 5 for d in dates), f"{sym} 주말 날짜 포함")
    for i in range(n):
        ok = l[i] - 0.01 <= min(o[i], c[i]) and max(o[i], c[i]) <= h[i] + 0.01 and l[i] > 0
        check(ok, f"{sym} {dates[i]} 시가/고가/저가/종가 관계 이상")
    check(all(abs(c[i] / c[i - 1] - 1) < 0.5 for i in range(1, n)), f"{sym} 하루 50% 이상 변동(분할 미반영 의심)")

    # 요약값과 원본 시계열 대조
    check(s["date"] == t["dates"][-1], f"{sym} 기준일 불일치")
    check(s["close"] == c[-1] and s["prev_close"] == c[-2], f"{sym} 종가/전일 종가 불일치")
    check(close_to(s["change"], c[-1] - c[-2], 1e-3), f"{sym} 전일 대비 금액 불일치")
    check(close_to(s["change_pct"], c[-1] / c[-2] - 1, 1e-5), f"{sym} 전일 대비 비율 불일치")

    # 이동평균: 누적합 방식으로 재계산
    cum = [0.0] + list(itertools.accumulate(c))
    for w in (20, 60, 120):
        series = t[f"ma{w}"]
        for i in range(n):
            exp = None if i < w - 1 else (cum[i + 1] - cum[i + 1 - w]) / w
            if exp is None:
                check(series[i] is None, f"{sym} MA{w} {dates[i]} 값이 있으면 안 됨")
            else:
                check(close_to(series[i], exp, 1e-3), f"{sym} MA{w} {dates[i]} 불일치 {series[i]} vs {exp:.4f}")
        check(close_to(s["ma"][str(w)], series[-1], 1e-9), f"{sym} MA{w} 요약 불일치")
        check(close_to(s["vs_ma"][str(w)], c[-1] / statistics.fmean(c[-w:]) - 1, 1e-5), f"{sym} MA{w} 대비 불일치")

    # RSI(14): 지수평활(alpha=1/14) 형태로 재계산
    diffs = [c[i] - c[i - 1] for i in range(1, n)]
    up = statistics.fmean(max(x, 0) for x in diffs[:14])
    dn = statistics.fmean(max(-x, 0) for x in diffs[:14])
    exp_rsi = [None] * 14 + [100 * up / (up + dn) if up + dn else 100.0]
    for x in diffs[14:]:
        up += (max(x, 0) - up) / 14
        dn += (max(-x, 0) - dn) / 14
        exp_rsi.append(100 * up / (up + dn) if up + dn else 100.0)
    for i in range(n):
        if exp_rsi[i] is None:
            check(t["rsi14"][i] is None, f"{sym} RSI {dates[i]} 값이 있으면 안 됨")
        else:
            check(close_to(t["rsi14"][i], exp_rsi[i], 0.011), f"{sym} RSI {dates[i]} 불일치")
            check(0 <= t["rsi14"][i] <= 100, f"{sym} RSI 범위 이탈")
    check(s["rsi14"] == t["rsi14"][-1], f"{sym} RSI 요약 불일치")

    # 수익률: 이진 탐색으로 비교 시점 재계산
    last = dates[-1]
    targets = {"1w": last - timedelta(days=7), "1m": months_back(last, 1), "3m": months_back(last, 3),
               "6m": months_back(last, 6), "1y": months_back(last, 12), "ytd": date(last.year - 1, 12, 31)}
    for k, target in targets.items():
        j = bisect.bisect_right(dates, target) - 1
        check(j >= 0, f"{sym} 수익률 {k} 비교 시점 없음")
        if j >= 0:
            check(s["return_base_dates"][k] == dates[j].isoformat(), f"{sym} 수익률 {k} 비교일 불일치")
            check(close_to(s["returns"][k], c[-1] / c[j] - 1, 1e-5), f"{sym} 수익률 {k} 불일치")
            check((target - dates[j]).days <= 5, f"{sym} 수익률 {k} 비교일이 목표일과 5일 넘게 차이")

    # 52주 고가/저가
    lo_i = bisect.bisect_right(dates, last - timedelta(days=364))
    hi52, lo52 = max(h[lo_i:]), min(l[lo_i:])
    check(close_to(s["high52"], hi52, 1e-9) and close_to(s["low52"], lo52, 1e-9), f"{sym} 52주 고가/저가 불일치")
    check(close_to(s["from_high52"], c[-1] / hi52 - 1, 1e-5), f"{sym} 52주 고가 대비 불일치")
    check(close_to(s["from_low52"], c[-1] / lo52 - 1, 1e-5), f"{sym} 52주 저가 대비 불일치")
    check(s["low52"] <= s["close"] <= s["high52"], f"{sym} 종가가 52주 범위 밖")

    # 변동성(60일, 연환산)
    lr = [math.log(c[i] / c[i - 1]) for i in range(n - 60, n)]
    check(close_to(s["vol60"], statistics.stdev(lr) * math.sqrt(252), 1e-5), f"{sym} 변동성 불일치")

    # Yahoo가 별도로 내려주는 요약값과 대조 (계산값이 아닌 외부 기준)
    ym = t["yahoo_meta"]
    if not ym["market_open_at_fetch"]:
        check(close_to(s["close"], ym["regularMarketPrice"], 0.006), f"{sym} 종가 {s['close']} vs Yahoo 현재가 {ym['regularMarketPrice']}")
    for mine, theirs, label in ((s["high52"], ym["fiftyTwoWeekHigh"], "52주 고가"), (s["low52"], ym["fiftyTwoWeekLow"], "52주 저가")):
        if ym["market_open_at_fetch"]:
            continue
        check(close_to(mine, theirs, 0.011), f"{sym} {label} {mine} vs Yahoo {theirs}")


def main():
    data = json.loads((ROOT / "data" / "prices.json").read_text(encoding="utf-8"))
    cfg = json.loads((ROOT / "tickers.json").read_text(encoding="utf-8"))
    check([t["symbol"] for t in data["tickers"]] == [t["symbol"] for t in cfg], "종목 목록이 tickers.json과 다름")
    as_of = date.fromisoformat(data["as_of"])
    updated = date.fromisoformat(data["updated_at"][:10])
    check(0 <= (updated - as_of).days <= 6, f"기준일({as_of})이 갱신일({updated}) 대비 너무 오래됨")
    for t in data["tickers"]:
        check(t["summary"]["date"] == data["as_of"], f"{t['symbol']} 기준일이 전체 기준일과 다름")
        verify(t)
    for w in warnings:
        print("주의:", w)
    if errors:
        print(f"검증 실패 {len(errors)}건 / 검사 {checks}건")
        for e in errors[:30]:
            print(" -", e)
        sys.exit(1)
    print(f"검증 통과: 검사 {checks}건, 오류 0건, 주의 {len(warnings)}건 (기준일 {data['as_of']})")


if __name__ == "__main__":
    main()
