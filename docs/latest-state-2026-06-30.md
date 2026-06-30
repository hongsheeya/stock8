# Latest Stock8 State - 2026-06-30

이 문서는 2026-06-30 기준 GitHub에 복구 가능한 형태로 남겨야 하는 최신 코드 상태, 운영 규칙, 배포 절차, 핵심 파일 설명을 한곳에 모아 둔 문서다.

## GitHub 복구 기준

- 원격 저장소: `git@github.com:hongsheeya/stock8.git`
- 기본 브랜치: `main`
- 2026-06-30 1차 복구 태그: `recovery-2026-06-30`
- 이 문서까지 포함한 최신 복구 태그는 별도로 `recovery-2026-06-30-detailed`로 남긴다.
- GitHub에는 코드, 테스트, 공개 문서, 복구 스크립트를 저장한다.
- GitHub에는 실계좌 API 키, DB 비밀번호, FireGate 토큰, 실제 운영 DB 덤프 같은 비공개 정보는 저장하지 않는다.

## 서버 위치와 실행 방식

운영 서버에서 실제 프로젝트 위치는 다음과 같다.

```text
/mnt/data/wiz/project/main
/opt/app/project/main -> /mnt/data/wiz/project/main
```

서버 실행 기준 디렉터리는 `/opt/app`이다.

```bash
cd /opt/app
setsid /opt/conda/envs/app/bin/wiz run --log /var/log/wiz/app >/tmp/wiz-run.out 2>/tmp/wiz-run.err < /dev/null &
```

서버 상태 확인은 다음 명령을 사용한다.

```bash
netstat -ltnp | grep ':3000'
curl -I http://127.0.0.1:3000/dashboard
curl -I http://127.0.0.1:3000/history
tail -n 80 /tmp/wiz-run.err
```

## 빌드와 배포 절차

`src/`만 수정하면 실제 서버 화면에 바로 반영되지 않을 수 있다. 수정 후에는 프로젝트 빌드와 프런트 번들 재생성을 수행한다.

```bash
cd /mnt/data/wiz/project/main
/opt/conda/envs/app/bin/wiz project build main
./scripts/rebuild_frontend_bundle.sh
```

일부 WIZ 화면은 빌드 산출물의 `view.html`을 `src/` 쪽에도 맞춰 둔다.

```bash
cp build/src/app/page.history/view.html src/app/page.history/view.html
cp build/src/app/page.settings/view.html src/app/page.settings/view.html
```

그 다음 `/opt/app`에서 기존 서버 프로세스 그룹을 내리고 다시 실행한다.

```bash
listener="$(netstat -ltnp 2>/dev/null | awk '/:3000/ {split($7,a,"/"); print a[1]; exit}')"
if [ -n "$listener" ]; then
  pgid="$(ps -o pgid= -p "$listener" | tr -d ' ')"
  kill -TERM -"$pgid" 2>/dev/null || true
  sleep 2
  kill -KILL -"$pgid" 2>/dev/null || true
fi
setsid /opt/conda/envs/app/bin/wiz run --log /var/log/wiz/app >/tmp/wiz-run.out 2>/tmp/wiz-run.err < /dev/null &
```

## 무한매수 운영 원칙

무한매수 예약은 FireGate를 절대 기준으로 따라간다.

- FireGate 표의 매수 가격, 매도 가격, 수량, 주문방식이 기준이다.
- 로컬 코드가 FireGate 가격이나 수량을 다시 계산해서 예약값을 만들면 안 된다.
- FireGate authoritative mode에서는 로컬 fallback 예약을 금지한다.
- FireGate와 KIS 예약이 하나라도 다르면 원칙적으로 전체 취소 후 FireGate 기준으로 다시 예약한다.
- 단, KIS 예약조회 실패나 빈 응답을 불일치로 오판해서 전체 재예약하면 안 된다.
- 브로커 예약조회가 매수와 매도 모두 빈 응답이면 자동 전체 재예약을 보류한다.
- 예약 POST는 재시도하지 않는다. 주문 POST 재시도는 중복 예약을 만들 수 있으므로 `retries=0`을 유지한다.
- 예약 검증은 5분마다 수행한다.
- FireGate와 KIS 예약이 3번 연속 동일하면 검증 완료로 본다.
- 검증 상태는 메모리뿐 아니라 `trading_config` DB에도 저장한다.
- FireGate 단순 재저장은 예약 검증 리셋 사유로 보지 않는다.
- 예약 검증 시그니처가 실제로 바뀔 때만 `1/3`부터 다시 검증한다.

## 예약 중복 방지 관련 핵심 수정

KIS 예약과 FireGate 동기화 관련해서 특히 중요한 수정은 다음과 같다.

- KIS 예약조회 pagination에서 `tr_cont=N` 누락으로 첫 20건만 읽던 문제를 수정했다.
- 예약조회 거래소를 여러 번 호출하면서 같은 예약이 중복 집계되던 문제를 수정했다.
- KIS 예약 매수, 매도, 취소 POST에 `retries=0`을 적용했다.
- SOXL 로컬 exchange가 `NASD`로 남아도 주문과 예약은 `AMEX`로 보정한다.
- 예약조회 실패를 "예약 없음"으로 처리하지 않는 guard를 추가했다.
- FireGate authoritative mode에서는 로컬 계산 fallback 예약을 만들지 않는다.
- 단타 기능은 봉인 상태를 유지한다.

## 2026-06-30 최신 화면/손익 수정

### 대시보드

`src/app/page.dashboard/api.py`에서 무한매수 손익 집계를 보강했다.

- 완료 사이클뿐 아니라 활성 사이클의 부분 매도 실현손익도 무한매수 실현손익에 포함한다.
- KST 기준 1D 손익에서 미국장 체결일이 전일로 저장되는 경우를 고려해 이전 미국 거래일 범위도 함께 본다.
- 부분 매도 실현손익은 `cycle_trade`의 매도 체결, 수량, 가격, 평균매수가, 수수료를 기준으로 계산한다.
- 대시보드의 무한매수 실현손익과 일별 breakdown에 반영한다.

### 거래이력 로딩

`src/app/page.history/api.py`와 `src/app/page.history/view.ts`에서 거래이력 초기 로딩을 빠르게 만들었다.

- 거래이력 첫 로딩에서 브로커/KIS 강제 동기화를 기본 수행하지 않는다.
- `daytrade_trades`, `cycles`, `cycle_detail`, `trade_logs`는 기본적으로 로컬 DB/런타임 상태를 먼저 보여준다.
- 외부 동기화는 명시적으로 `sync` 또는 `sync_broker`가 true일 때만 수행한다.
- 오래된 기록은 더보기 방식으로 추가 조회한다.

### 거래이력 손익 표시

거래이력 상단 손익 카드를 다음 순서로 정리했다.

1. `실현손익`
2. `보유 평가손익`
3. `현재까지 손익`

각 카드에는 국장과 미장을 분리해 표시한다.

- `실현손익`: 매도 체결 기준 realized P/L
- `보유 평가손익`: 현재 보유 포지션 평가손익
- `현재까지 손익`: 실현손익 + 보유 평가손익
- 이득은 빨강, 손실은 파랑으로 표시한다.
- 국장과 미장의 부호가 다를 수 있으므로 카드 전체 색이 아니라 각 금액 줄에 개별 색상을 적용한다.

### 거래이력 보유 포지션

거래이력 화면은 현재 보유 포지션도 함께 표시한다.

- 단타 보유 포지션과 무한매수 활성 사이클 포지션을 함께 집계한다.
- 종목, 시장, 전략, 보유수량, 평균가, 현재가, 평가손익을 표시한다.
- SOXL/TQQQ 같은 무한매수 종목은 단타 포지션으로 중복 취급하지 않는다.

### 설정 화면

`src/app/page.settings/view.pug`, `view.scss`, `view.html`에서 FireGate 기본 운용 카드의 대비를 수정했다.

- 배경색과 글자색이 비슷해 잘 안 보이던 문제를 고쳤다.
- "FireGate 그대로 운용" 카드가 밝은 테마에서도 읽히도록 별도 색상 변수를 적용했다.
- 고급 LOC 주문 설정은 필요할 때만 펼치는 구조로 유지한다.

## 핵심 파일 설명

### `src/portal/trading/model/struct.py`

트레이딩 모델의 큰 진입점이다.

- 예약 자동화 실행 상태를 관리한다.
- 5분 예약 검증 스케줄을 다룬다.
- 예약 검증 상태를 `trading_config`에 저장한다.
- FireGate 단순 재저장과 실제 예약 변경을 구분한다.

### `src/portal/trading/model/struct/engine.py`

무한매수 엔진이다.

- FireGate 기준 예약 생성과 검증을 담당한다.
- KIS 주문 호출로 실제 예약 매수/매도를 접수한다.
- FireGate authoritative mode에서는 로컬 fallback 예약을 만들지 않아야 한다.

### `src/portal/trading/model/struct/kis_api.py`

KIS 브로커 API 계층이다.

- 예약조회 pagination과 `tr_cont` 처리가 중요하다.
- 예약조회 결과 중복 집계를 막는다.
- 주문 POST 재시도를 하지 않도록 `retries=0`을 유지한다.
- 예약조회 실패는 예약 없음이 아니라 실패로 다룬다.

### `src/portal/trading/model/struct/firegate_bridge.py`

FireGate 포트폴리오 동기화 계층이다.

- FireGate 표를 authoritative state로 읽는다.
- 무한매수 예약의 가격과 수량은 FireGate 표 값을 기준으로 사용한다.
- 로컬 계산값으로 FireGate 예약값을 대체하면 안 된다.

### `src/app/page.dashboard/api.py`

대시보드 API다.

- 총자산, 실현손익, 평가손익, 무한매수/단타 요약을 만든다.
- 2026-06-30 기준 활성 무한매수 사이클의 부분 매도 실현손익을 대시보드에 포함한다.

### `src/app/page.history/api.py`

거래이력 API다.

- 단타 체결, 무한매수 `cycle_trade`, 런타임 로그를 통합 조회한다.
- 초기 로딩에서는 외부 브로커 동기화를 기본 실행하지 않는다.
- 시장별 손익 bucket을 만들고 국장/미장 손익을 분리한다.
- 단타 보유 포지션과 무한매수 활성 사이클 포지션의 평가손익을 계산한다.

### `src/app/page.history/view.ts`

거래이력 화면의 프런트엔드 로직이다.

- API 호출 시 기본 `sync_broker=false`, `sync=false`를 보낸다.
- 손익 표시용 `summaryProfitLines`를 통해 국장/미장 금액 줄을 만든다.
- `summaryProfitValueClass`로 이득은 빨강, 손실은 파랑을 적용한다.
- `profitClass`도 같은 색상 체계를 사용한다.

### `src/app/page.history/view.pug`

거래이력 화면 구조다.

- 상단 카드 순서를 `실현손익 -> 보유 평가손익 -> 현재까지 손익`으로 조정했다.
- 각 손익 금액에 개별 색상 클래스를 적용한다.
- 보유 포지션 카드에 현재가와 평가손익을 표시한다.

### `src/app/page.history/view.scss`

거래이력 화면 스타일이다.

- `--hist-profit-up`은 이득 색상이다.
- `--hist-profit-down`은 손실 색상이다.
- 어두운 테마와 밝은 테마 모두에 빨강/파랑 색상을 정의했다.

### `src/app/page.settings/view.pug`

설정 화면 구조다.

- FireGate 기본 운용 카드를 명확히 보여준다.
- 고급 LOC 주문 설정은 접힌 영역으로 분리한다.

### `src/app/page.settings/view.scss`

설정 화면 스타일이다.

- FireGate 기본 운용 카드의 배경, 텍스트, badge, 버튼 대비를 별도 클래스로 보정했다.

### `tests/test_dashboard_accounting_regressions.py`

대시보드와 거래이력 손익 회귀 테스트다.

- 활성 사이클 부분 매도 실현손익 집계를 검증한다.
- 거래이력의 단타/무한매수 보유 평가손익 집계를 검증한다.
- 국장/미장 bucket과 현재까지 손익 계산을 검증한다.

## 검증한 테스트

2026-06-30 최신 코드 푸시 전 다음 테스트를 통과했다.

```bash
python -m unittest \
  tests.test_dashboard_accounting_regressions \
  tests.test_infinitebuy_loc_schedule_regressions \
  tests.test_kis_api_buying_power \
  tests.test_trading_config_scope \
  tests.test_firegate_bridge
```

결과:

```text
Ran 121 tests
OK
```

서버 재시작 후 다음도 확인했다.

```text
/history   200 OK
/dashboard 200 OK
/tmp/wiz-run.err 오류 없음
```

## GitHub에 넣지 않는 것

다음 파일과 데이터는 복구에는 중요하지만 공개 GitHub에 그대로 넣으면 안 된다.

- `config/`
- `data/*.db`
- `data/db/*.db`
- `.env`
- KIS API 키와 secret
- FireGate 토큰
- DB 접속 비밀번호
- 실계좌 상태가 들어 있는 전체 DB 덤프
- 서버별 생성물인 `build/`, `bundle/`

서버 종료나 머신 교체에 대비하려면 공개 GitHub 외에 private recovery backup이 필요하다.

```bash
cd /mnt/data/wiz/project/main
./scripts/create_private_recovery_backup.sh
```

백업 파일은 `/mnt/data/wiz/private-backups/` 아래에 생성된다. 이 파일은 반드시 비공개 위치에 보관해야 한다.

## 새 서버에서 복구 순서

1. GitHub에서 코드를 clone한다.
2. private recovery backup에서 `config/`, `data/`, `bundle/config/` 등을 복원한다.
3. `/opt/app/project/main`이 `/mnt/data/wiz/project/main`을 가리키도록 맞춘다.
4. `/opt/conda/envs/app/bin/wiz project build main`을 실행한다.
5. `./scripts/rebuild_frontend_bundle.sh`를 실행한다.
6. `/opt/app`에서 `wiz run` 명령으로 서버를 실행한다.
7. `/dashboard`, `/history`가 200인지 확인한다.
8. KIS 예약조회가 정상인지 확인한다.
9. FireGate 표와 KIS 예약이 같은지 3회 연속 검증 완료 상태를 확인한다.

## 복구 후 가장 먼저 확인할 것

- FireGate 표를 읽을 수 있는지
- TQQQ와 SOXL 매수/매도 예약 수량과 단가가 FireGate와 일치하는지
- KIS 예약조회 pagination이 전체 예약을 읽는지
- 예약조회 실패가 예약 없음으로 표시되지 않는지
- 주문 POST 재시도가 꺼져 있는지
- 거래이력 상단 손익 카드가 `실현손익 -> 보유 평가손익 -> 현재까지 손익` 순서인지
- 손익 색상이 이득 빨강, 손실 파랑인지
- 대시보드 무한매수 실현손익에 부분 매도 수익이 포함되는지
