# 단타 국장·미장 네비게이션 및 미장 전용 API 독립화

- **ID**: 004
- **날짜**: 2026-05-06
- **유형**: 리팩토링

## 작업 요약
상단 트레이딩 네비게이션에서 국장 단타와 미장 단타를 분리해 각각 별도 진입 링크로 노출했다.
또한 미장 전용 페이지의 API에 실행·자동매매·청산 감시 함수를 보강해 국장 페이지 API에 남아 있던 미장 전용 동작 의존도를 낮췄다.

## 원문 요청사항
```text
단타에서 국장 미장 제대로 구분해놔. 지금 매매알고리즘이 하나로 묶였잖아.
멈추지 말고 계속 진행해
```

## 변경 파일 목록
### 코드 수정
- `src/app/component.nav.trading/view.ts`
  - `/daytrade`와 `/daytrade/us`를 별도 활성 링크로 판별하도록 수정
  - `/daytrade/us` 경로에서 시장 개장 여부를 미장 기준으로 계산하도록 수정
- `src/app/component.nav.trading/view.pug`
  - 관리자 메뉴에 `국장 단타`, `미장 단타`를 별도 링크로 분리
- `build/src/app/component.nav.trading/component.nav.trading.component.ts`
  - 동일 수정 반영
- `build/src/app/component.nav.trading/view.pug`
  - 동일 수정 반영
- `src/app/page.daytrade.us/api.py`
  - `us_execute_live`, `us_toggle_auto`, `us_get_auto_status`, `us_manual_sell`, `us_auto_cycle`, `us_execute_exit_watch` 추가
- `build/src/app/page.daytrade.us/api.py`
  - 동일 수정 반영
- `bundle/src/app/page.daytrade.us/api.py`
  - 동일 수정 반영

## 후속 메모
- 국장 페이지 API 파일 안에는 미장 호환 함수가 여전히 일부 남아 있으나, 미장 전용 페이지는 이제 자체 API만으로 주요 기능을 수행할 수 있다.
- 다음 단계는 국장 추천 종목 소실 문제를 분석해 추천 유지 로직을 안정화하는 것이다.
