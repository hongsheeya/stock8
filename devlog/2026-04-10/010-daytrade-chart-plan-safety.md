# 단타 연구실: 차트+매매계획 표시, 강제매수 제거, UI 전면 개편

- **ID**: 010
- **날짜**: 2026-04-10
- **유형**: 기능 추가 + 버그 수정 + 리팩토링

## 작업 요약
단타 연구실 페이지를 전면 개편. (1) 종목 선택 시 SVG 가격 차트에 매수/매도 트리거 레벨을 시각적으로 표시, (2) 매매 계획(진입조건·청산조건·보유포지션) 명확히 테이블로 제공, (3) 강제매수(force buy) 기능 완전 제거로 안전장치 강화, (4) 학습/추천이 백테스트임을 UI에 명시, (5) HOLD 상태에서 트리거 가격까지의 격차를 표시하여 "신호 없음" 상태를 명확히 설명.

## 변경 파일 목록

### API (백엔드)
- `src/app/page.daytrade/api.py` — `chart_data()` 신규 엔드포인트 추가 (차트 바 + 트리거 + 매매계획 + 시그널 통합 응답), `execute_live()` force 파라미터 제거 (항상 force=False)

### Frontend - TypeScript
- `src/app/page.daytrade/view.ts` — SVG 차트 계산 로직 (pricePath, areaPath, triggerLines, triggerY, indexToX 등), `loadChartData()` 메서드, `executeSignal()` (강제매수 없음, 시그널 오직 기반), i18n import 제거

### Frontend - Template
- `src/app/page.daytrade/view.pug` — SVG 가격 차트 (트리거 수평선 + 현재가 마커), 매매 계획 섹션 (진입/청산/포지션), HOLD 상태 설명 UI, 강제매수 버튼 제거, "백테스트" 명시

### 주요 변경 사항
1. **chart_data API**: 5분봉 5일 데이터 + 시그널 트리거(anchor/buy1/buy2/jackpot/recent/rescue) + 매매계획(entries/exits/position) + 백테스트 요약 통합 응답
2. **SVG 차트**: 가격 라인 + 영역 그라데이션 + 트리거 레벨 대시선(색상별 구분) + 현재가 마커
3. **강제매수 제거**: execute_live는 반드시 force=False, HOLD 시 주문 미실행
4. **매매계획 표시**: 진입조건(BUY1/BUY2 트리거가격·예상수량), 청산조건(잭팟/방어/구조 목표가·예상수익), 보유포지션(수량·평단가·평가손익)
5. **HOLD 설명**: 현재가 vs BUY1 트리거 가격 격차를 숫자로 표시
