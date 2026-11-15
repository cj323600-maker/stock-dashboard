# 미국 주식 분석 대시보드

관심 종목의 종가, 수익률, 이동평균, RSI(14), 52주 고가/저가, 변동성을 한 화면에서 보는 정적 대시보드입니다.

## 구성

| 파일 | 역할 |
|---|---|
| `index.html` | 대시보드 화면 (폰과 PC 공용) |
| `tickers.json` | 관심 종목 목록. 여기만 고치면 종목이 바뀝니다 |
| `scripts/fetch_data.py` | Yahoo Finance에서 일별 시세를 받아 지표를 계산하고 `data/prices.json`에 저장 |
| `scripts/verify_data.py` | 지표를 다른 방식으로 다시 계산해 대조하고, Yahoo가 따로 내려주는 종가와 52주 고가/저가와도 대조 |
| `.github/workflows/update-data.yml` | 평일 미국 장 마감 후 자동 수집, 검증 통과 시에만 반영 |
| `journal.js` | 매매 기록(매수 조건, 매수/매도, 손익) 계산과 저장 |
| `vendor/chart.umd.js` | 차트 라이브러리 Chart.js 4.4.7 (MIT) |

## 종목 바꾸기

`tickers.json`에 미국 종목 코드와 표시 이름을 추가하거나 지웁니다.

```json
{"symbol": "AAPL", "name": "애플"}
```

저장하면 다음 자동 갱신 때 반영됩니다. 바로 반영하려면 Actions 탭에서 "주가 데이터 갱신"을 수동 실행합니다.

## 직접 실행

```
python3 scripts/fetch_data.py
python3 scripts/verify_data.py
python3 -m http.server 8000
```

## 지표 정의

화면 아래 "용어 설명"과 `scripts/fetch_data.py` 상단 주석에 같은 내용으로 적혀 있습니다. 정의를 바꿀 때는 수집 스크립트, 검증 스크립트, 화면 용어 설명 세 곳을 함께 고칩니다.

## 매매 기록

화면의 "매매 기록"에서 매수할 때 조건을 먼저 적고, 매도하면 결과와 조건 준수 여부를 남깁니다. 실현손익, 평가손익, 승률, 규칙 준수율이 자동 계산됩니다.

기록은 쓰는 기기의 브라우저에만 저장되고 이 공개 저장소에는 올라가지 않습니다. 폰과 PC는 따로 저장되므로 "백업 파일 내보내기"로 받은 파일을 다른 기기에서 "백업 파일 불러오기"로 옮깁니다. 브라우저 데이터를 지우면 기록도 사라지니 주기적으로 백업해 두세요.

## 백테스트

`backtest/run_backtest.py`가 보유, 추세(20일선 > 60일선), RSI(30 매수, 70 매도, -10% 손절) 세 규칙을 같은 기간으로 시험하고 `backtest/results.json`에 저장합니다. `backtest/verify_backtest.py`가 다른 계산 방식으로 결과를 대조합니다. 규칙과 체결 가정은 `run_backtest.py` 상단 주석에 있습니다.

```
python3 backtest/run_backtest.py
python3 backtest/verify_backtest.py
```

## 유의 사항

참고용 정보이며 투자 권유가 아닙니다. 수익률은 배당을 포함하지 않습니다. Yahoo Finance는 비공식 경로라 응답이 막히면 그날 갱신은 건너뛰고 기존 데이터를 유지합니다.
