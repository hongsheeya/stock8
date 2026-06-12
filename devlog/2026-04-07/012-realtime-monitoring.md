# 실시간 모니터링 및 토스트 알림

- **ID**: 012
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
대시보드에 30초 주기 자동 폴링 + 카운트다운 인디케이터, 새 거래 이벤트 감지 시 토스트 알림(최대 5개, 5초 자동 소멸) 시스템을 구현했다. 매수/매도 체결, 목표 수익률 도달, 에러 등 이벤트 타입별로 색상·아이콘이 구분되는 슬라이드 토스트 UI를 추가했다.

## 변경 파일 목록

### Frontend - Dashboard
| 파일 | 변경 내용 |
|------|----------|
| `src/app/page.dashboard/view.ts` | Toast 인터페이스, 자동 폴링(30s interval + 1s countdown), silent refresh, 새 로그 감지(detectNewLogs), 토스트 관리(addToast/removeToast, max 5, 5s dismiss), toggleAutoRefresh, ngOnDestroy 클린업 |
| `src/app/page.dashboard/view.pug` | 토스트 오버레이(fixed bottom-right, 이벤트 타입별 아이콘/색상), 자동 갱신 인디케이터(카운트다운 + 토글 버튼), Last Updated 표시 |
| `src/app/page.dashboard/view.scss` | slideInRight 애니메이션, glass-card-light 토스트 배경, status-dot 스타일 |

### 알림 타입 매핑
| 이벤트 타입 | 토스트 타입 | 색상 |
|------------|-----------|------|
| BUY | info | indigo |
| SELL / CYCLE_COMPLETE | success | emerald |
| ERROR | error | red |
| 기타 (auto trade toggle 등) | warning | amber |
