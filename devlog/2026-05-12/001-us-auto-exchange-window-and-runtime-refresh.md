# 미장 자동환전 예약매수 시간 표시 및 런타임 갱신 보강

- **ID**: 001
- **날짜**: 2026-05-12
- **유형**: 기능 추가

## 작업 요약
미국 단타 자동매매가 원화 자동환전을 포함한 예약매수 예산을 17:40 KST 이후 실주문 가능 금액으로 해석하도록 복구했다.
미국 단타 화면과 상태 API에 자동매매 거래 시간 정보를 추가하고, 이미 떠 있는 공유 struct/엔진 캐시도 새 모델 클래스로 교체되도록 런타임 갱신 로직을 보강했다.

## 원문 요청사항
```text
ㅅㅂ 저번에 자동환전 기능 추가했었잖아. 다시 구현 좀 하고 자동 매매 거래 시간이 언제인지 표시해봐. 예약매수라 17시반 이후면 상관없어. 17시40분으로 맞춰놔
```

## 변경 파일 목록
### 백엔드
- `src/portal/trading/model/struct/kis_api.py`
  - 17:40 KST 기준 미국 자동환전 예약매수 가능 시간 계산 헬퍼 추가
  - 미국 주문가능금액 응답에 `executable_amount`, `executable_qty`, `auto_exchange_ready` 반영
- `src/portal/trading/model/struct/daytrade_engine.py`
  - 미국 자동매매 BUY가 17:40 KST 이전에는 대기 상태를 반환하도록 가드 추가
  - 예약매수 가능 시간 메타데이터 생성 헬퍼 추가
- `src/portal/trading/model/struct/engine.py`
  - 미국 무한매수 주문 전 검사도 `executable_amount`, `executable_qty` 기준으로 정렬
- `src/portal/trading/model/struct.py`
  - 캐시된 단타 엔진 모델이 새 헬퍼 메서드를 잃은 경우 다시 로드하도록 보강
- `src/app/page.daytrade.us/api.py`
  - 자동매매 상태/스냅샷 응답에 `auto_buy_window` 포함
  - 공유 struct 싱글톤에 캐시된 trading 서브모델을 최신 클래스로 교체하는 런타임 갱신 로직 추가

### 프론트엔드
- `src/app/page.daytrade.us/view.ts`
  - 자동매매 거래 시간 표시용 getter 추가
- `src/app/page.daytrade.us/view.html`
  - “자동매매 거래 시간” 패널과 17:40 KST 예약매수 대기 상태 표시 추가

### 검증
- 프로젝트 일반 빌드 성공
- `us_get_auto_status`, `us_snapshot` API 응답에서 `auto_buy_window.scheduled_at = 17:40 KST` 및 대기 상태 노출 확인
