# 국장 추천 종목 캐시 fallback 유지로 소실 방지

- **ID**: 005
- **날짜**: 2026-05-06
- **유형**: 버그 수정

## 작업 요약
국장 단타 화면에서 실시간 갱신 도중 추천 캐시가 비거나 캐시 키가 맞지 않을 때 `recommendation`이 `None`으로 바뀌며 추천 패널이 사라지는 흐름을 보강했다.
서버에서는 안정 추천 fallback을 생성하도록 했고, 프런트에서는 빈 recommendation 응답으로 기존 추천 상태를 지우지 않도록 방어 로직을 추가했다.

## 원문 요청사항
```text
단타 국장 지금 종목 추천 오류 있는거 같아 자꾸 없어져. 없어지지 않게 계속 초기화해서 표시하도록 했잖아. 원인 찾아서 최적화하고 고쳐내
멈추지 말고 계속 진행해
```

## 변경 파일 목록
### 코드 수정
- `src/app/page.daytrade/api.py`
  - `_stable_recommendation()` 헬퍼 추가
  - `bootstrap()`과 실시간 상태 응답 경로에서 추천 캐시가 비면 fallback 추천을 생성하도록 수정
- `build/src/app/page.daytrade/api.py`
  - 동일 수정 반영
- `bundle/src/app/page.daytrade/api.py`
  - 동일 수정 반영
- `src/app/page.daytrade/view.ts`
  - 실시간 응답에서 `recommendation`이 비어도 기존 추천 상태를 유지하도록 수정
- `build/src/app/page.daytrade/page.daytrade.component.ts`
  - 동일 수정 반영

## 후속 메모
- 현재 추천 소실 원인은 주로 실시간 갱신 시 추천 캐시 조회 실패/불일치로 판단된다.
- 이번 수정으로 추천 패널이 비어 보이는 현상은 완화되며, 이후 필요하면 캐시 키 정책 자체를 더 단순화할 수 있다.
