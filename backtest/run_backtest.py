#!/usr/bin/env python3
"""주식 규칙 매매 백테스트. data/prices.json의 일별 데이터를 사용한다.

규칙 (결과를 보기 전에 고정한 교과서적 기본값, 파라미터 튜닝 없음)
- 보유: 시작일 시가에 사서 끝까지 보유 (비교 기준)
- 추세: 20일 이동평균이 60일 이동평균보다 위면 보유, 아래면 현금
- RSI: RSI(14)가 30 이하면 매수, 70 이상이면 매도. 보유 중 종가가 매수가 대비 -10% 이하면 손절

체결 가정
- 신호는 그날 종가까지의 데이터로 계산하고, 주문은 다음 거래일 시가에 체결 (미래 데이터 사용 방지)
- 매수, 매도 때마다 거래금액의 0.25%를 비용으로 차감 (수수료와 체결 오차 합산 가정, 환전 비용 미포함)
- 한 번에 자금 전부를 매수하거나 전부 매도. 현금 이자 없음. 배당 미반영
- 기간 마지막 날 보유 중이면 종가에 매도한 것으로 계산 (비용 차감)
- 시작: 60일 이동평균이 처음 계산되는 날 다음 거래일. 모든 규칙이 같은 날 시작
"""
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEE = 0.0025
STOP = -0.10
RULES = [("hold", "보유"), ("trend", "추세 (20일선 > 60일선)"), ("rsi", "RSI (30 매수, 70 매도, -10% 손절)")]


def signals(rule, t, i, holding, entry_px):
    """i일 종가 기준 신호: 'buy', 'sell', None"""
    c = t["close"][i]
    if rule == "hold":
        return "buy" if not holding else None
    if rule == "trend":
        up = t["ma20"][i] > t["ma60"][i]
        return "buy" if up and not holding else "sell" if not up and holding else None
    if rule == "rsi":
        r = t["rsi14"][i]
        if not holding:
            return "buy" if r <= 30 else None
        if r >= 70 or c / entry_px - 1 <= STOP:
            return "sell"
        return None
    raise ValueError(rule)


def run(t, rule, start):
    o, c, dates = t["open"], t["close"], t["dates"]
    n = len(c)
    cash, shares, holding = 1.0, 0.0, False
    entry_px = entry_cost = None
    pending = "buy" if rule == "hold" else None
    equity, trades, held_days = [], [], 0
    for i in range(start, n):
        if pending == "buy" and not holding:
            entry_cost = cash
            shares = cash * (1 - FEE) / o[i]; cash = 0.0; holding = True
            entry_px = o[i]; entry_date = dates[i]
        elif pending == "sell" and holding:
            cash = shares * o[i] * (1 - FEE); shares = 0.0; holding = False
            trades.append({"buy": entry_date, "sell": dates[i], "ret": cash / entry_cost - 1})
        pending = None
        if holding:
            held_days += 1
        equity.append(cash + shares * c[i])
        if i < n - 1:
            pending = signals(rule, t, i, holding, entry_px)
    if holding:
        cash = shares * c[-1] * (1 - FEE); shares = 0.0
        trades.append({"buy": entry_date, "sell": dates[-1] + " (기간 종료)", "ret": cash / entry_cost - 1})
        equity[-1] = cash
    peak, mdd = 0.0, 0.0
    for e in equity:
        peak = max(peak, e); mdd = min(mdd, e / peak - 1)
    final = equity[-1]
    days = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[start])).days
    return {
        "final": final, "total": final - 1, "cagr": final ** (365.25 / days) - 1, "mdd": mdd,
        "trades": len(trades), "wins": sum(1 for x in trades if x["ret"] > 0),
        "exposure": held_days / (n - start), "equity": equity, "trade_list": trades,
    }


def main():
    data = json.loads((ROOT / "data" / "prices.json").read_text(encoding="utf-8"))
    out = {"as_of": data["as_of"], "fee": FEE, "stop": STOP, "rules": dict(RULES), "tickers": []}
    for t in data["tickers"]:
        start = next(i for i, v in enumerate(t["ma60"]) if v is not None) + 1
        row = {"symbol": t["symbol"], "name": t["name"], "start": t["dates"][start], "end": t["dates"][-1],
               "days": len(t["dates"]) - start, "results": {}}
        for key, _ in RULES:
            r = run(t, key, start)
            row["results"][key] = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items() if k != "equity"}
            row["results"][key]["equity"] = [round(x, 6) for x in r["equity"]]
        out["tickers"].append(row)
    (ROOT / "backtest" / "results.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    print(f"기간 {out['tickers'][0]['start']} ~ {out['tickers'][0]['end']} ({out['tickers'][0]['days']}거래일), 비용 편도 {FEE:.2%}")
    print(f"{'종목':6}" + "".join(f"| {lab[:10]:12} 총수익  연환산  최대낙폭 거래 승 보유비중 " for _, lab in RULES))
    for row in out["tickers"]:
        line = f"{row['symbol']:6}"
        for key, _ in RULES:
            r = row["results"][key]
            line += f"| {r['total']:+8.2%} {r['cagr']:+7.2%} {r['mdd']:+7.2%} {r['trades']:3} {r['wins']:2} {r['exposure']:6.1%} "
        print(line)


if __name__ == "__main__":
    main()
