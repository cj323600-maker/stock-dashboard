/*
 * 매매 기록 (매수 조건과 손익)
 *
 * 저장 위치: 이 기기 브라우저(localStorage)에만 저장한다. 공개 저장소에 개인 매매 내역이 올라가지 않게 하기 위함.
 * 기기 간 이동은 백업 파일 내보내기와 불러오기로 한다.
 *
 * 계산 기준 (화면 용어 설명과 동일하게 유지할 것). 모든 금액은 달러이며 센트 단위 정수로 계산한 뒤 표시한다.
 * - 승수: 주식 1, 옵션 100 (옵션 1계약 = 기초자산 100주)
 * - 매수금액 = 매수 단가 x 수량 x 승수 + 매수 수수료
 * - 매도금액 = 매도 단가 x 수량 x 승수 - 매도 수수료
 * - 실현손익 = 매도금액 - 매수금액 (매도까지 기록한 건)
 * - 평가금액 = 현재가 x 수량 x 승수 (보유 중인 건, 매도 수수료 미반영)
 *   현재가는 대시보드 종목이면서 주식이면 기준일 종가, 그 외에는 직접 입력한 현재가
 * - 평가손익 = 평가금액 - 매수금액
 * - 손익률 = 손익 / 매수금액
 * - 승률 = 실현손익이 0보다 큰 건수 / 매도까지 기록한 건수
 * - 규칙 준수율 = 매도 때 "매수 조건대로 지켰다"를 고른 건수 / 매도 때 준수 여부를 고른 건수
 */
(function (root) {
  'use strict';

  var MULT = { stock: 1, option: 100 };
  var KEY = 'sd-trades-v1';

  function cents(x) { return Math.round(x * 100); }
  function num(v) {
    if (v === null || v === undefined || v === '') return null;
    var n = typeof v === 'number' ? v : Number(String(v).replace(/,/g, '').trim());
    return isFinite(n) ? n : NaN;
  }

  // 한 건의 계산 결과. prices: { SYMBOL: 기준일 종가 }
  function evaluate(t, prices) {
    var m = MULT[t.type] || 1;
    var buyC = cents(t.buyPrice * t.qty * m) + cents(t.buyFee || 0);
    var r = { mult: m, buyAmtC: buyC, closed: t.sellPrice != null && t.sellDate != null };
    if (r.closed) {
      r.sellAmtC = cents(t.sellPrice * t.qty * m) - cents(t.sellFee || 0);
      r.pnlC = r.sellAmtC - buyC;
      r.price = t.sellPrice;
    } else {
      var p = null;
      if (t.type === 'stock' && prices && prices[t.symbol] != null) { p = prices[t.symbol]; r.priceSource = 'dashboard'; }
      else if (t.manualPrice != null) { p = t.manualPrice; r.priceSource = 'manual'; }
      r.price = p;
      if (p != null) {
        r.valueC = cents(p * t.qty * m);
        r.pnlC = r.valueC - buyC;
      }
    }
    r.pnlPct = r.pnlC != null && buyC > 0 ? r.pnlC / buyC : null;
    if (r.price != null && !r.closed) {
      r.toTarget = t.target != null ? t.target / r.price - 1 : null;
      r.toStop = t.stop != null ? t.stop / r.price - 1 : null;
    }
    return r;
  }

  function summarize(trades, prices) {
    var s = { openCount: 0, openBuyC: 0, openEvalCount: 0, openEvalBuyC: 0, unrealC: 0,
      closedCount: 0, closedBuyC: 0, realC: 0, wins: 0, ruleAnswered: 0, ruleKept: 0 };
    trades.forEach(function (t) {
      var r = evaluate(t, prices);
      if (r.closed) {
        s.closedCount++; s.closedBuyC += r.buyAmtC; s.realC += r.pnlC;
        if (r.pnlC > 0) s.wins++;
        if (t.ruleKept === 'yes' || t.ruleKept === 'no') { s.ruleAnswered++; if (t.ruleKept === 'yes') s.ruleKept++; }
      } else {
        s.openCount++; s.openBuyC += r.buyAmtC;
        if (r.pnlC != null) { s.openEvalCount++; s.openEvalBuyC += r.buyAmtC; s.unrealC += r.pnlC; }
      }
    });
    s.winRate = s.closedCount ? s.wins / s.closedCount : null;
    s.ruleRate = s.ruleAnswered ? s.ruleKept / s.ruleAnswered : null;
    s.realPct = s.closedBuyC ? s.realC / s.closedBuyC : null;
    s.unrealPct = s.openEvalBuyC ? s.unrealC / s.openEvalBuyC : null;
    return s;
  }

  // 입력값 검사와 정리. 반환: { trade } 또는 { errors: [...] }
  function normalize(f) {
    var e = [];
    var t = {
      id: f.id || null,
      symbol: String(f.symbol || '').trim().toUpperCase(),
      type: f.type === 'option' ? 'option' : 'stock',
      detail: String(f.detail || '').trim(),
      buyDate: String(f.buyDate || '').trim(),
      buyPrice: num(f.buyPrice), qty: num(f.qty), buyFee: num(f.buyFee),
      reason: String(f.reason || '').trim(),
      target: num(f.target), stop: num(f.stop), manualPrice: num(f.manualPrice),
      sellDate: String(f.sellDate || '').trim() || null,
      sellPrice: num(f.sellPrice), sellFee: num(f.sellFee),
      ruleKept: f.ruleKept === 'yes' || f.ruleKept === 'no' ? f.ruleKept : '',
      note: String(f.note || '').trim()
    };
    var date = /^\d{4}-\d{2}-\d{2}$/;
    if (!/^[A-Z0-9.\-^=]{1,15}$/.test(t.symbol)) e.push('종목 코드를 영문으로 입력해 주세요.');
    if (!date.test(t.buyDate)) e.push('매수일을 입력해 주세요.');
    if (!(t.buyPrice > 0)) e.push('매수 단가는 0보다 커야 합니다.');
    if (!(t.qty > 0)) e.push('수량은 0보다 커야 합니다.');
    if (!t.reason) e.push('매수 조건을 적어 주세요. 이 기록의 핵심입니다.');
    if (t.buyFee == null) t.buyFee = 0;
    if (t.sellFee == null) t.sellFee = 0;
    if (isNaN(t.buyFee) || t.buyFee < 0) e.push('매수 수수료는 0 이상이어야 합니다.');
    if (isNaN(t.sellFee) || t.sellFee < 0) e.push('매도 수수료는 0 이상이어야 합니다.');
    ['target', 'stop', 'manualPrice'].forEach(function (k) {
      if (t[k] != null && !(t[k] > 0)) e.push({ target: '목표가', stop: '손절가', manualPrice: '현재가' }[k] + '는 0보다 커야 합니다.');
    });
    var anySell = t.sellDate || t.sellPrice != null;
    if (anySell) {
      if (!t.sellDate || !date.test(t.sellDate)) e.push('매도일을 입력해 주세요.');
      if (t.sellPrice == null || isNaN(t.sellPrice) || t.sellPrice < 0) e.push('매도 단가를 입력해 주세요. 옵션이 가치 없이 만기됐으면 0을 입력합니다.');
      if (t.sellDate && date.test(t.buyDate) && t.sellDate < t.buyDate) e.push('매도일이 매수일보다 빠릅니다.');
    } else {
      t.sellDate = null; t.sellPrice = null; t.sellFee = 0; t.ruleKept = '';
    }
    return e.length ? { errors: e } : { trade: t };
  }

  function load(storage) {
    try {
      var raw = storage.getItem(KEY);
      if (!raw) return [];
      var arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr : [];
    } catch (err) { return null; }
  }

  function save(storage, trades) {
    try { storage.setItem(KEY, JSON.stringify(trades)); return true; } catch (err) { return false; }
  }

  // 백업 파일 검사. 하나라도 이상하면 전체를 거부한다.
  function parseBackup(text) {
    var obj;
    try { obj = JSON.parse(text); } catch (err) { return { errors: ['백업 파일 형식이 올바르지 않습니다.'] }; }
    var list = Array.isArray(obj) ? obj : obj && Array.isArray(obj.trades) ? obj.trades : null;
    if (!list) return { errors: ['백업 파일에서 매매 기록을 찾지 못했습니다.'] };
    var out = [], errs = [];
    list.forEach(function (x, i) {
      var r = normalize(x || {});
      if (r.errors) errs.push((i + 1) + '번째 기록: ' + r.errors[0]);
      else { r.trade.id = x.id || newId(); r.trade.createdAt = x.createdAt || null; out.push(r.trade); }
    });
    return errs.length ? { errors: errs } : { trades: out };
  }

  function newId() { return 't' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8); }

  var api = { MULT: MULT, KEY: KEY, evaluate: evaluate, summarize: summarize, normalize: normalize,
    load: load, save: save, parseBackup: parseBackup, newId: newId };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.Journal = api;
})(this);
