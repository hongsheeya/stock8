# 거래일지 브로커 동기화 우선 경로 복구

- **ID**: 006
- **날짜**: 2026-05-04
- **유형**: 버그 수정

## 작업 요약
국장/미장 거래일지 API가 로컬 요약 경로를 우선 사용하면서 브로커 체결과 어긋나던 문제를 수정했다.
일별 거래일지와 미장 런타임 검증이 브로커 동기화 요약을 먼저 사용하고, 실패 시에만 기존 로컬 요약으로 안전하게 폴백하도록 소스·빌드·런타임 파일을 동기 반영했다.

## 원문 요청사항
```text
거래일지 좀 동기화 제대로 해
```

## 변경 파일 목록
### Source
- `src/app/page.daytrade/api.py`: 거래일지 공통 브로커 동기화 helper 추가, 국장/미장 일지 및 미장 런타임 검증이 브로커 요약을 우선 사용하도록 수정
- `src/app/page.daytrade.us/api.py`: 별도 미장 거래일지/검증 API가 브로커 동기화 요약을 우선 사용하도록 수정

### Build Runtime Mirror
- `build/src/app/page.daytrade/api.py`: 소스와 동일한 거래일지 동기화 수정 반영
- `build/src/app/page.daytrade.us/api.py`: 소스와 동일한 미장 거래일지 동기화 수정 반영

### Bundle Runtime Mirror
- `bundle/src/app/page.daytrade/api.py`: 런타임 백엔드 반영용 동기화 수정 반영
- `bundle/src/app/page.daytrade.us/api.py`: 런타임 백엔드 반영용 동기화 수정 반영

### 검증
- 수정한 6개 API 파일에 대해 editor diagnostics 확인
- `python -m py_compile`로 6개 파일 문법 검증 완료
