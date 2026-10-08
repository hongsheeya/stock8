# 국내 시장별 주문 처리 (2026-10-01)

## 확인한 공식 규격

- [KIS 2026-09-09 변경 공지](https://apiportal.koreainvestment.com/community/10000000-0000-0011-0000-000000000001/post/26dfe350-eb72-48e5-8175-34eb27970f3e)
- [KIS 현금 주문](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/order_cash/order_cash.py)
- [KIS 정정취소](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/order_rvsecncl/order_rvsecncl.py)
- [NXT 시장시간](https://nextrade.co.kr/main.do)

| 시장 | 시간(KST) | 지원하는 주문 경로 |
|---|---|---|
| KRX 정규 접속매매 | 09:00–15:20 | KRX, 지정가 00 / 시장가 01 |
| KRX 종가 단일가 | 15:20–15:30 | 자동 신규 주문 제외 |
| NXT 프리 | 08:00–08:50 | NXT, GTP 지정가 27 |
| NXT 메인 | 09:00:30–15:20 | NXT, 지정가 00 |
| NXT 애프터 | 15:40–20:00 | NXT, 지정가 00 |
| KRX 애프터 | 16:00–20:00 | KRX, 애프터 지정가 41 |

끝 시각은 포함하지 않는다. 시간외 종가/주문접수만 가능한 시간은 자동 주문 대상이 아니다.
주말은 차단한다. 연장장에는 당일 개장일, 종목별 거래가능 여부, 거래정지 여부 확인이 추가로 필요하다.
KRX 애프터 ETP는 제외한다. NXT 미체결 프리 주문을 정규장으로 넘기지 않도록 GTP만 지원한다.
SOR 자동 배분 및 실패 후 타 시장 재주문은 구현하지 않는다.

## 구현과 배포 상태를 구분할 것

구현: 순수 시간/주문 검증 모듈, KIS 시세 J/NX/UN, 주문 거래소 필드,
현행 TR ID, 원주문 시장/주문유형을 이용한 취소, 체결조회 ALL,
엔진 주문 로그의 시장 메타데이터 보존. POST 재시도는 하지 않는다.

연장장 자동운용은 **아직 활성화하지 않았다**. `domestic_extended_orders_enabled`
기본값은 false이며 이를 true로 변경하지 않았다. 기존 자동엔진은 여전히
KRX 정규장으로 동작한다. 추가 인자를 받는 주문 어댑터만으로 20시 자동운용이
완성됐다고 표시하면 안 된다.

남은 통합 조건:

1. 해당 시장의 최신 시세/분봉으로 전략을 계산하고 시장 전환 때 캐시를 분리할 것.
2. 당일 휴장/지연 개장 및 종목별 애프터 거래제외 정보의 검증된 공급자를 연결할 것.
3. 확인된 정보만 `domestic_order_plan` evidence로 전달할 것. HTTP 폼 값을 신뢰하면 안 된다.
4. 신규진입/청산/예약취소/부분체결 회수까지 같은 시장 컨텍스트를 사용해 통합시험할 것.
5. 그 전에는 15:20 가드만 20:00으로 바꾸거나, 기존 MARKET 주문을 임의 지정가로 바꾸지 말 것.

삼성전자 KIS 기본정보 및 KRX/NXT 시세 읽기 전용 조회 성공(2026-10-01).
NXT 거래종목 여부 `cptt_trad_tr_psbl_yn` 및 `nxt_tr_stop_yn` 응답을 확인했다.
이 조회는 주문 실행 또는 단타 엔진 정상 가동을 증명하지 않는다.

테스트는 네트워크를 모의 처리하며 실제 주문을 제출하지 않는다.
`python -m unittest discover -s tests -p test_domestic_market.py -v`
