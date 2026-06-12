# 설정 페이지 KIS 연결 캐시 미반영 및 성공 오판정 수정

- **ID**: 004
- **날짜**: 2026-05-04
- **유형**: 버그 수정

## 작업 요약
설정 페이지에서 KIS API 정보를 저장해도 실제 연결 테스트에 즉시 반영되지 않던 문제를 수정했다.
원인은 `page.settings/api.py`가 설정 저장 시 DB만 직접 갱신하고 `trading.get_config()` 캐시를 갱신하지 않아, 저장 직후 `kis_api.test_connection()`이 이전 값으로 동작하던 점과 프런트가 HTTP 200만 보고 연결 성공으로 오판정하던 점이었다.

## 원문 요청사항
```text
통과해서 반영 제대로 해. 아직도 연결 안되잖아. 원인 찾아서 해결좀해
```

## 변경 파일 목록
### 백엔드 API
- `src/app/page.settings/api.py`
  - `_set_config()`가 `trading.set_config()`를 우선 사용하도록 변경해 설정 캐시 즉시 동기화
  - 계좌번호 정규화/형식 검증 추가 (`12345678-01`)
  - `save_api_settings()`가 저장 직후 실제 `kis_api.test_connection()` 결과를 함께 반환하도록 수정
  - `test_connection()`이 `success=false`를 정상적으로 응답하도록 정리
- `build/src/app/page.settings/api.py`
  - 빌드 소스 동일 수정 동기화
- `bundle/src/app/page.settings/api.py`
  - 런타임 백엔드 동일 수정 동기화

### 프런트엔드
- `src/app/page.settings/view.ts`
  - 저장 후 모달/배너가 실제 연결 성공 여부(`data.success`)를 기준으로 표시되도록 수정
  - 연결 테스트도 HTTP 200 여부가 아니라 `success` 플래그로 판정하도록 수정
  - 저장 실패/요청 예외 메시지 처리 보강
- `build/src/app/page.settings/page.settings.component.ts`
  - 빌드 프런트 동일 수정 동기화

## 검증
- 수정한 `page.settings` API 3개 파일에 대해 `python -m py_compile` 검증 완료
- 런타임 번들 `bundle/www/main.js`에 대해서 `node --check` 검증 완료
- 에디터 진단 기준 수정 파일 오류 없음 확인
