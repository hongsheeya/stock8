# Stock8 새 서버 배포

Stock8은 WIZ(Python/Flask + Angular), WebSocket, 내부 스케줄러, 영구 DB와 상태 파일을 함께 사용한다. 정적 호스팅이나 서버리스 대신 Docker를 실행할 수 있는 Linux VPS를 사용한다.

## 복구에 필요한 것

필수:

- 이 GitHub 저장소
- Ubuntu VPS 권장 사양: 2 vCPU, 메모리 4 GB 이상, 디스크 30 GB 이상
- 서버의 22, 80, 443 포트

실계좌와 기존 상태까지 복원하려면 추가로 필요:

- `stock8-private-recovery-*.tar.gz`
- KIS/토스/FireGate 자격 증명
- 기존 `config/database.py` 또는 DB 접속 정보
- 도메인과 DNS 변경 권한

비공개 백업이 없으면 코드와 빈 SQLite DB로 사이트는 다시 시작할 수 있지만, 기존 사용자·거래 이력·설정·실계좌 연결은 자동 복구되지 않는다.

## 1. 서버 준비

Ubuntu 서버에 Docker Engine과 Compose 플러그인을 설치한 뒤 저장소를 받는다.

```bash
git clone git@github.com:hongsheeya/stock8.git
cd stock8
cp .env.example .env
sed -i "s/replace-with-a-random-64-character-value/$(openssl rand -hex 32)/" .env
```

도메인이 있으면 `.env`의 값을 바꾼다. 도메인의 A/AAAA 레코드는 이 서버를 가리켜야 한다.

```dotenv
STOCK8_SITE_ADDRESS=stock.example.com
```

도메인이 아직 없으면 기본값 `:80`으로 서버 IP의 HTTP 접속부터 확인한다.

## 2. 비공개 복구 데이터 넣기

처음에는 자동매매를 켜지 않는다. 기존 DB에 자동매매 ON 상태가 저장돼 있을 수 있으므로, 실계좌 자격 증명을 넣기 전에 상태를 점검한다.

백업이 있으면 별도 임시 디렉터리에서 압축을 풀고 필요한 항목만 복사한다.

```bash
mkdir -p config data
mkdir -p /tmp/stock8-recovery
tar -xzf /private/stock8-private-recovery-YYYYMMDDTHHMMSSZ.tar.gz -C /tmp/stock8-recovery
cp -a /tmp/stock8-recovery/stock8-private-recovery-*/config/. config/
cp -a /tmp/stock8-recovery/stock8-private-recovery-*/data/. data/
```

공개 저장소나 Docker 이미지에 `config/`, `.env`, DB 파일, API 키를 커밋하지 않는다. `.dockerignore`도 이 파일들이 이미지 빌드 컨텍스트에 들어가지 않도록 차단한다.

## 3. 빌드 및 시작

```bash
docker compose config
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=200 stock8
```

첫 빌드는 WIZ와 Angular 의존성을 설치하므로 시간이 걸린다. `config/database.py`가 없으면 진입 스크립트가 빈 SQLite 설정을 설치한다.

## 4. 확인

```bash
curl -I http://127.0.0.1/access
curl -I http://127.0.0.1/dashboard
docker compose ps
docker compose logs --tail=200 stock8
```

도메인을 설정했다면 `https://도메인/access`를 확인한다. Caddy가 인증서 발급과 WebSocket 프록시를 처리한다.

실계좌 자격 증명을 복원한 뒤에는 다음 순서로 확인한다.

1. 자동매매가 OFF인지 확인한다.
2. KIS/토스 계좌 연결과 잔고 조회만 확인한다.
3. FireGate 포트폴리오와 로컬 상태를 비교한다.
4. 기존 예약 주문과 KIS 예약조회 pagination 결과를 확인한다.
5. 중복 주문이 없음을 확인한 후에만 필요한 자동매매를 수동으로 켠다.

## 업데이트

```bash
git pull --ff-only
docker compose build
docker compose up -d
docker compose ps
```

`config/`와 `data/`는 호스트 디렉터리로 마운트되므로 이미지 재빌드 후에도 유지된다. 업데이트 전에는 private recovery backup과 DB 백업을 먼저 만든다.

## 중지와 롤백

```bash
docker compose stop stock8
git tag --list 'recovery-*'
```

코드 롤백은 복구 태그를 별도 브랜치로 체크아웃한 뒤 이미지를 다시 빌드한다. DB/상태 파일은 코드와 별도로 백업에서 복원해야 한다.
