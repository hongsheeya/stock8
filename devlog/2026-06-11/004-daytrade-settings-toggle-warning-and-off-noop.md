# 설정 단타 토글 즉시 경고 추가 및 OFF 무동작 정정

- **ID**: 004
- **날짜**: 2026-06-11
- **유형**: 버그 수정

## 작업 요약
설정 화면의 단타 ON/OFF 토글을 누르는 즉시 OFF→ON 경고 모달이 뜨도록 수정했다.
동시에 단타 OFF 시 예약 취소나 정리 동작이 실행되지 않도록 관련 API와 안내 문구를 정리해, OFF는 자동 운용만 멈추고 나머지는 건드리지 않게 맞췄다.

## 원문 요청사항
```text
ㅅㅂ 경고 어디갔어. 설정 단타 on off에서 키는데 경고문 안뜨잖아. 그리고 off하면 그냥 아무것도 하지마. 정리도 하지마
```

## 변경 파일 목록
- `src/app/page.settings/view.ts`
  - 설정 토글 클릭 시 바로 사용하는 단타 ON 확인 메서드 추가
  - 저장 시점 경고 로직 제거
- `src/app/page.settings/view.pug`
  - 국내/미장 단타 토글을 즉시 경고 메서드로 연결
  - OFF 설명 문구를 무동작 의미에 맞게 수정
- `src/app/page.settings/api.py`
  - 설정 저장으로 OFF 적용 시 예약 매도 정리하던 동작 제거
- `src/app/page.daytrade/api.py`
  - 국장/미장 단타 OFF 시 예약 매도 정리 응답 제거
- `src/app/page.daytrade/view.ts`
  - OFF 완료 메시지에서 예약 취소 안내 제거
- `devlog/2026-06-11/002-daytrade-off-exit-watch-guard.md`
  - 현재 OFF 정책과 맞지 않는 정리 설명 제거
