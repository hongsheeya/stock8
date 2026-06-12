# 단타 페이지 view.ts 재구성 및 모듈 스크립트 MIME 오류 복구

- **ID**: 005
- **날짜**: 2026-05-08
- **유형**: 버그 수정

## 작업 요약
국장 단타 페이지의 `view.ts`가 WIZ 빌드 규약과 맞지 않아 프런트 빌드가 깨지고, 그 여파로 브라우저가 모듈 스크립트 대신 HTML을 받아 MIME 오류가 발생하던 문제를 복구했다.
또한 국장 거래일지 로딩 병목을 빠른 기간 요약 경로로 정리하고, 중복 메서드 정리 이후 빌드와 HTTP 응답까지 다시 검증했다.

## 원문 요청사항
```text
중복 메서드 삭제에서 무한루프 걸려서 진행이 안된거 같은데 다시 진행하고 검증까지 진행해. 또 지금 국장 단타 로딩시간 너무 길어. 원인 찾아서 잡아

view.ts 문제 해결해주고 Failed to load module script: Expected a JavaScript-or-Wasm module script but the server responded with a MIME type of "text/html". Strict MIME type checking is enforced for module scripts per HTML spec. 이 오류도 해결해
```

## 변경 파일 목록
### 백엔드 / 성능
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 중복 정의되어 있던 단타 관련 메서드 블록을 제거해 무한 정리 루프 원인을 해소
- `src/app/page.daytrade/api.py`
  - `daily_log()` 경로에서 무거운 로컬 요약 우회 경로를 제거하고 `engine.period_trade_summary(...)` 기반으로 정리
  - 국장 거래일지 응답 필드를 화면 요구사항에 맞게 정규화

### 프런트엔드
- `src/app/page.daytrade/view.ts`
  - WIZ 규약에 맞는 `export class Component` 구조로 전체 재작성
  - 잘못된 서비스 import와 구식 API 호출을 현재 단타 API 구조에 맞게 정리
  - 국장 화면 핵심 상태/추천/라이브 상태/거래일지/기간 요약/수동 매도 동작을 다시 연결
  - 미장 탭 관련 액션은 `/daytrade/us` 리다이렉트로 안전하게 처리
- `src/types/wiz-modules.d.ts`
  - `view.ts` 타입 오류를 없애기 위한 최소 선언 참조 유지

## 검증 내용
- `src/app/page.daytrade/view.ts` 진단 결과 파일 오류가 없어짐
- 프로젝트 빌드 재실행 후 `Project 'main' build completed.` 확인
- `/daytrade` 응답에서 참조되는 `main.js`를 다시 확인해 `text/javascript; charset=utf-8`로 내려오는 것까지 검증
- 모듈 스크립트가 HTML로 내려오던 기존 MIME 오류 재현 조건이 해소됨

## 비고
- 이번 수정은 대형 `view.pug` 템플릿 전체를 깨지지 않게 복구하는 데 우선순위를 두고, 현재 백엔드 API와 맞는 안정 동작 중심으로 `view.ts`를 재구성했다.
- 추가 UI 세부 동작은 실제 브라우저 상호작용 기준으로 후속 미세 조정 가능하다.
