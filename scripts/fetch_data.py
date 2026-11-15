#!/usr/bin/env python3
"""미국 주식 일별 시세를 Yahoo Finance에서 받아 지표를 계산하고 data/prices.json에 저장한다.

지표 정의 (index.html 용어 설명과 동일하게 유지할 것)
- 종가: 액면분할 반영, 배당 미반영 종가
- 전일 대비: 직전 거래일 종가 대비 변동
- 수익률: 기준일 종가 / 비교 시점 종가 - 1 (배당 미반영)
  비교 시점 = 달력 기준 N개월(주) 전 날짜, 그날이 휴장이면 그 이전 마지막 거래일
  연초 대비 = 전년도 마지막 거래일 종가 대비
- 이동평균: 최근 N거래일 종가의 단순 평균 (20/60/120일)
- RSI(14): Wilder 방식 14일
- 52주 고가/저가: 기준일 포함 최근 52주(364일) 동안의 장중 고가/저가 (Yahoo Finance와 같은 기준)
- 변동성(60일, 연환산): 최근 60개 일간 로그수익률의 표본 표준편차 x sqrt(252)
"""
import json
import math
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
HOSTS = ["query1.finance.yahoo.com", "query1.finance.yahoo.com", "query2.finance.yahoo.com", "query2.finance.yahoo.com"]
UA = "Mozilla/5.0"  # 긴 브라우저 UA는 Yahoo가 429로 거절함 (2026-11 확인)
HISTORY_DAYS = 365 * 3 + 30
NY = ZoneInfo("America/New_York")
MA_WINDOWS = (20, 60, 120)
RSI_N = 14
VOL_N = 60


def fetch_chart(symbol, now_ts):
    p1 = now_ts - HISTORY_DAYS * 86400
    last_err = None
    for attempt in range(4):
        host = HOSTS[attempt % len(HOSTS)]
        url = (f"https://{host}/v8/finance/chart/{symbol}"
               f"?period1={p1}&period2={now_ts}&interval=1d&events=div%2Csplit")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.load(r)
            res = body["chart"]["result"]
            if not res:
                raise RuntimeError(f"빈 응답: {body['chart'].get('error')}")
            return res[0]
        except Exception as e:  # 네트워크 오류, 429 등은 재시도
            last_err = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{symbol} 시세 수신 실패: {last_err}")


def shift_months(d, months):
    """d에서 months개월 전 날짜. 해당 일이 없으면 그 달 말일."""
    y, m = d.year, d.month - months
    while m <= 0:
        y, m = y - 1, m + 12
    day = d.day
    while True:
        try:
            return date(y, m, day)
        except ValueError:
            day -= 1


def close_on_or_before(dates, closes, target):
    """target 이하인 마지막 거래일의 (날짜, 종가). 없으면 None."""
    found = None
    for d, c in zip(dates, closes):
        if d <= target:
            found = (d, c)
        else:
            break
    return found


def sma(values, n):
    out = [None] * len(values)
    for i in range(n - 1, len(values)):
        out[i] = sum(values[i - n + 1:i + 1]) / n
    return out


def rsi_wilder(closes, n):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(closes)):
        if i > n:
            ag = (ag * (n - 1) + gains[i - 1]) / n
            al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def annual_vol(closes, n):
    if len(closes) < n + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - n, len(closes))]
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    return math.sqrt(var) * math.sqrt(252)


def rnd(x, nd):
    return None if x is None else round(x, nd)


def build(symbol, kr_name, now_ts):
    raw = fetch_chart(symbol, now_ts)
    meta = raw["meta"]
    q = raw["indicators"]["quote"][0]
    rows = []
    for i, ts in enumerate(raw["timestamp"]):
        o, h, l, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
        if None in (o, h, l, c):
            continue
        d = datetime.fromtimestamp(ts, NY).date()
        rows.append((d, o, h, l, c, v or 0, ts))
    # 장중에 실행되면 마지막 봉은 미확정이므로 제외한다
    reg = meta["currentTradingPeriod"]["regular"]
    if rows and reg["start"] <= rows[-1][6] and now_ts < reg["end"]:
        rows.pop()
    # 같은 날짜가 중복되면 마지막 것만 사용
    dedup = {}
    for r in rows:
        dedup[r[0]] = r
    rows = [dedup[d] for d in sorted(dedup)]
    if len(rows) < 260:
        raise RuntimeError(f"{symbol} 데이터 부족: {len(rows)}행")

    dates = [r[0] for r in rows]
    highs = [r[2] for r in rows]
    lows = [r[3] for r in rows]
    closes = [r[4] for r in rows]
    last_d, last_c, prev_c = dates[-1], closes[-1], closes[-2]

    mas = {n: sma(closes, n) for n in MA_WINDOWS}
    rsi = rsi_wilder(closes, RSI_N)

    def ret_since(target):
        base = close_on_or_before(dates, closes, target)
        if base is None:
            return None, None
        return last_c / base[1] - 1, base[0].isoformat()

    periods = {
        "1w": last_d - timedelta(days=7),
        "1m": shift_months(last_d, 1),
        "3m": shift_months(last_d, 3),
        "6m": shift_months(last_d, 6),
        "1y": shift_months(last_d, 12),
        "ytd": date(last_d.year - 1, 12, 31),
    }
    returns, bases = {}, {}
    for k, t in periods.items():
        r, b = ret_since(t)
        returns[k], bases[k] = rnd(r, 6), b

    start52 = last_d - timedelta(weeks=52)
    idx52 = [i for i, d in enumerate(dates) if d > start52]
    high52 = max(highs[i] for i in idx52)
    low52 = min(lows[i] for i in idx52)

    summary = {
        "date": last_d.isoformat(),
        "close": rnd(last_c, 4),
        "prev_close": rnd(prev_c, 4),
        "change": rnd(last_c - prev_c, 4),
        "change_pct": rnd(last_c / prev_c - 1, 6),
        "returns": returns,
        "return_base_dates": bases,
        "rsi14": rnd(rsi[-1], 2),
        "high52": rnd(high52, 4),
        "low52": rnd(low52, 4),
        "from_high52": rnd(last_c / high52 - 1, 6),
        "from_low52": rnd(last_c / low52 - 1, 6),
        "vol60": rnd(annual_vol(closes, VOL_N), 6),
        "ma": {str(n): rnd(mas[n][-1], 4) for n in MA_WINDOWS},
        "vs_ma": {str(n): rnd(last_c / mas[n][-1] - 1, 6) for n in MA_WINDOWS},
    }
    return {
        "symbol": symbol,
        "name": kr_name,
        "name_en": meta.get("longName") or meta.get("shortName") or symbol,
        "currency": meta.get("currency", "USD"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "",
        "yahoo_meta": {
            "regularMarketPrice": meta.get("regularMarketPrice"),
            "regularMarketTime": meta.get("regularMarketTime"),
            "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh"),
            "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow"),
            "market_open_at_fetch": reg["start"] <= now_ts < reg["end"],
        },
        "summary": summary,
        "dates": [d.isoformat() for d in dates],
        "open": [rnd(r[1], 4) for r in rows],
        "high": [rnd(x, 4) for x in highs],
        "low": [rnd(x, 4) for x in lows],
        "close": [rnd(x, 4) for x in closes],
        "volume": [r[5] for r in rows],
        "ma20": [rnd(x, 4) for x in mas[20]],
        "ma60": [rnd(x, 4) for x in mas[60]],
        "ma120": [rnd(x, 4) for x in mas[120]],
        "rsi14": [rnd(x, 2) for x in rsi],
    }


def main():
    tickers = json.loads((ROOT / "tickers.json").read_text(encoding="utf-8"))
    now_ts = int(time.time())
    out = []
    for t in tickers:
        out.append(build(t["symbol"], t["name"], now_ts))
        print(f"{t['symbol']}: {out[-1]['summary']['date']} 종가 {out[-1]['summary']['close']}")
        time.sleep(1)
    as_of = max(x["summary"]["date"] for x in out)
    stale = [x["symbol"] for x in out if x["summary"]["date"] != as_of]
    if stale:
        raise RuntimeError(f"기준일({as_of})과 다른 종목: {stale}")
    payload = {
        "as_of": as_of,
        "updated_at": datetime.fromtimestamp(now_ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Yahoo Finance",
        "tickers": out,
    }
    path = ROOT / "data" / "prices.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"저장 완료: {path} (기준일 {as_of}, {len(out)}개 종목)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)
