# 전 거래일지 브로커 동기화 및 대시보드 요약 보강

- **ID**: 008
- **날짜**: 2026-05-04
- **유형**: 버그 수정

## 작업 요약
국장 단타 거래일지 재발 이슈를 기준으로 전체 거래일지 경로를 다시 점검한 결과, 국장 일지의 미해결 매도 fallback과 대시보드 기간 요약이 여전히 로컬 요약을 우선 사용하고 있었다.
국장/미장 거래일지, 공통 엔진, 대시보드 거래요약까지 모두 브로커 실체결 우선 경로로 맞추고, 실패 시에만 로컬 경로로 폴백하도록 전 경로를 정리했다.

## 원문 요청사항
```text
아니 ㅅㅂ 국장 단타에서 거래일지가 문제라고. 너하는 꼬라지 보니까 모든 거래 일지 다 문제겠네. ㅅㅂ 다 고쳐
```

## 변경 파일 목록
### 거래일지 API
- `src/app/page.daytrade/api.py`: 국장 거래일지의 미해결 매도 fallback도 브로커 동기화 우선으로 변경
- `build/src/app/page.daytrade/api.py`: 동일 수정 반영
- `bundle/src/app/page.daytrade/api.py`: 동일 수정 반영

### 대시보드 요약
- `src/app/page.dashboard/api.py`: 기간 단타 요약을 브로커 동기화 우선 + 실패 시 로컬 폴백으로 변경
- `build/src/app/page.dashboard/api.py`: 동일 수정 반영
- `bundle/src/app/page.dashboard/api.py`: 동일 수정 반영

### 공통 엔진/실체결 수집
- `src/portal/trading/model/struct/daytrade_engine.py`: 국내+해외 실체결 병합 및 동기화 메타데이터 보강 유지
- `src/portal/trading/model/struct/kis_api.py`: 해외 체결 조회 NASD/NYSE/AMEX 전체 + 페이지네이션 지원 유지

### 검증
- editor diagnostics 이상 없음
- `python -m py_compile`로 거래일지/대시보드/공통 엔진 관련 파일 전체 문법 검증 완료
- 사용자가 실행한 `npm run build`도 성공 상태 확인
