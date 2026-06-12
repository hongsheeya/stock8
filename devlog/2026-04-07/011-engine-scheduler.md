# 엔진 스케줄러 및 자동 매매 실행

- **ID**: 011
- **날짜**: 2026-04-07
- **유형**: 기능 추가

## 작업 요약
Trading 패키지에 REST API 기반 스케줄러 Route(`/api/trading/scheduler/<action>`)를 구현. threading Lock으로 동시 실행 방지, 종목별 순차 처리(engine.run_all), 토큰 기반 인증, 계좌 스냅샷 자동 저장, 헬스체크 엔드포인트 포함.

## 변경 파일 목록

### 신규 생성
- `src/portal/trading/route/scheduler/app.json` - Route 메타 (route=/api/trading/scheduler, controller 없음)
- `src/portal/trading/route/scheduler/controller.py` - 스케줄러 Route (run/status/snapshot/health 액션, Lock 기반 동시실행 방지, 토큰 검증, 계좌 스냅샷)

### 수정
- `src/app/page.dashboard/api.py` - run_engine() 함수 코멘트 개선
