# 미장 단타 시드 저장 초기화 덮어쓰기 수정 및 추가 검토 결과 가시화

- **ID**: 016
- **날짜**: 2026-05-06
- **유형**: 버그 수정

## 작업 요약
미장 단타 화면이 초기 로딩 때 항상 기본값 `5000` 시드를 함께 보내 저장된 시드를 덮어써 보이던 문제를 수정했다.
또한 추가로 검토한 알고리즘 결과가 화면에서 보이지 않던 문제를 보완하기 위해, 랭킹 응답에 추가 검토 요약과 보류 사유를 넣고 화면에 직접 표시하도록 정리했다.

## 원문 요청사항
```text
뭐야 된거야? 시드 적용 저장이 제대로 안돼. 매매 알고리즘 추가로 찾아본건 어디갔어
```

## 변경 파일 목록
### 시드 저장/초기화 보정
- `src/app/page.daytrade.us/view.ts`
  - 초기 `bootstrap()` 호출에서 임시 `seed` 값을 보내지 않도록 수정하여 저장된 미장 기본 시드가 정상 반영되게 함
- `build/src/app/page.daytrade.us/page.daytrade.us.component.ts`
  - 빌드 런타임에도 동일한 초기화 보정 반영
- `src/app/page.daytrade.us/api.py`
  - `persist_seed=true` 저장 후 `us_defaults()`를 다시 읽어 저장값을 응답에 반영하도록 수정
- `build/src/app/page.daytrade.us/api.py`
  - 빌드 런타임 API에 동일한 저장 후 재조회 로직 반영
- `bundle/src/app/page.daytrade.us/api.py`
  - 번들 런타임 API에 동일한 저장 후 재조회 로직 반영

### 추가 알고리즘 검토 결과 노출
- `src/app/page.daytrade.us/api.py`
  - `research_summary` 필드를 추가해 상위 전략/실거래 보류 전략과 사유를 함께 반환
- `build/src/app/page.daytrade.us/api.py`
  - 빌드 런타임 API에 동일한 연구 요약 필드 반영
- `bundle/src/app/page.daytrade.us/api.py`
  - 번들 런타임 API에 동일한 연구 요약 필드 반영
- `src/app/page.daytrade.us/view.html`
  - 랭킹 패널에 `추가 검토 결과` 영역을 추가해 1순위 전략과 보류 전략 사유를 표시
- `build/src/app/page.daytrade.us/view.html`
  - 빌드 런타임 템플릿에 동일한 가시화 반영

## 검증 메모
- 변경 파일 전부 정적 오류 검사 결과 이상 없음
- 저장된 시드는 이제 첫 로딩에서 서버 기본값을 그대로 읽고, 저장 직후에도 재조회된 값으로 반영됨
- 추가 검토 결과는 랭킹 실행 후 화면에서 바로 확인 가능
