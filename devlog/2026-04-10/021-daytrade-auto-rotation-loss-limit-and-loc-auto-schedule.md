# 단타 자동순환·일일손실제한·17시40분 LOC 자동예약 적용

- **ID**: 021
- **날짜**: 2026-04-10
- **유형**: 기능 추가

## 작업 요약
남는 원화 시드가 있으면 국내 단타 엔진이 변동성/유동성 점수가 높은 종목을 자동으로 다시 훑고 실행할 수 있도록 자동순환 로직을 추가했다.
동시에 일일 손실 제한을 도입해 손실이 한도에 도달하면 신규 BUY를 막고, 무한매수 LOC 예약은 매일 17:40 KST 이후 스케줄러가 자동으로 한 번만 접수하도록 정리했다.

## 변경 파일 목록
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 단타 자동순환 후보 선정, 포트폴리오 사용 금액 계산, 일일 손실 제한 계산, 신규 BUY 차단 가드레일 추가
- `src/portal/trading/route/scheduler/controller.py`
  - 스케줄러 실행 시 단타 자동순환과 17:40 KST LOC 자동예약을 함께 처리하도록 확장
- `src/app/page.settings/api.py`
  - 단타 자동순환, 일일 손실 제한, 최대 감시 종목 수, LOC 자동예약 설정 load/save 추가
- `src/app/page.settings/view.ts`
  - 신규 설정 필드 상태 관리 추가
- `src/app/page.settings/view.pug`
  - 전략 탭에 단타 자동순환/손실제한/LOC 자동예약 UI 추가
- `.github/custom/daytrade-usage.md`
  - 수동 감시형 설명을 자동순환 혼합 구조에 맞게 갱신
