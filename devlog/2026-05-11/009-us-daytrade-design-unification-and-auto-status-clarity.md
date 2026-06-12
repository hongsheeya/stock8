# 미장 단타 디자인 통일 및 자동매매 상태 원인 가시화

- **ID**: 009
- **날짜**: 2026-05-11
- **유형**: 기능 추가

## 작업 요약
미장 단타 전용 화면을 기존 국장 단타와 같은 다크 글래스모피즘 스타일로 재구성했다. 동시에 미장 자동매매 상태 API를 확장해 STOPPED/READY/RUNNING을 단순 토글이 아니라 워커 실행, KIS 연결, 장 상태를 기준으로 설명하도록 바꿨다.

## 원문 요청사항
```text
1. 미장 단타 디자인만 다르잖아. 전체적으로 디자인을 통일 해. 저번에 줬던 디자인 md 이용해 2. 자동매매 상태 위기상태 stopped 인데 원인 찾아봐
```

## 변경 파일 목록
### 프론트엔드
- `src/app/page.daytrade.us/view.html`
  - 미장 단타 페이지 전체를 다크 글래스 카드 레이아웃으로 교체
  - 자동매매 상태 원인 패널, 운영 제어, 랭킹, 검증, 포지션 카드 구성 추가
- `src/app/page.daytrade.us/view.ts`
  - `autoStatus` 로딩 및 토글 액션 추가
  - 상태 라벨/톤/원인, 시장 세션, USD 포맷, 포지션/리스크 배지 헬퍼 추가
- `src/app/page.daytrade.us/view.scss`
  - 페이지 호스트 높이 보장을 위한 `:host` 스타일 추가

### 백엔드
- `src/app/page.daytrade.us/api.py`
  - `us_verify_runtime()` 캐시 키에 현재 미장 자동매매 토글 상태를 포함
  - `us_get_auto_status()` 응답에 워커 상태, KIS 연결, 장 상태, 상태 라벨/원인/톤, 마지막 자동 사이클 정보를 추가

## 검증
- `wiz project build --project=main` 일반 빌드 성공
- 인증 세션으로 `us_get_auto_status`, `us_verify_runtime` 재검증
  - 현재 상태는 `READY`
  - 원인은 `미국 주식 시장(프리마켓/본장)이 열려있지 않습니다.`
  - 워커는 실행 중이고 KIS 연결도 정상으로 확인
