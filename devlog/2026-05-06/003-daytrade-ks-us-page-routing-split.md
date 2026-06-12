# 단타 국장 페이지에서 미장 전용 페이지로 분리 라우팅

- **ID**: 003
- **날짜**: 2026-05-06
- **유형**: 버그 수정

## 작업 요약
국장 단타 페이지 안에 남아 있던 미장 탭 진입을 전용 미장 페이지로 라우팅하도록 바꿔 화면 진입 경로를 분리했다.
또한 미장 전용 페이지가 국장 페이지와 동일한 접근 제어를 사용하도록 `admin` 컨트롤러를 적용했다.

## 원문 요청사항
```text
단타에서 국장 미장 제대로 구분해놔. 지금 매매알고리즘이 하나로 묶였잖아.
계속 진행해. 그리고 todo로 만들어달라고 했는데 지금 바로 적용중인거야?
```

## 변경 파일 목록
### 코드 수정
- `src/app/page.daytrade/view.ts`
  - `switchMarketMode('US')` 호출 시 국장 페이지 내부 상태 전환 대신 `/daytrade/us` 전용 페이지로 이동하도록 수정
- `build/src/app/page.daytrade/page.daytrade.component.ts`
  - 동일 수정 반영
- `src/app/page.daytrade.us/app.json`
  - 미장 전용 페이지 `controller`를 `admin`으로 조정
- `build/src/app/page.daytrade.us/app.json`
  - 동일 수정 반영
- `bundle/src/app/page.daytrade.us/app.json`
  - 동일 수정 반영

## 후속 메모
- 현재 `page.daytrade/api.py` 내부에는 미장 전용 API 함수가 여전히 남아 있어, 화면 분리 후에도 백엔드 코드 정리는 추가로 필요하다.
- 다음 단계에서는 미장 전용 API를 `page.daytrade.us/api.py` 기준으로 완전히 분리하고 국장 페이지의 미장 잔여 코드를 정리할 예정이다.
