import season

# SQLite 기반 샘플 데이터베이스 설정
# namespace별로 변수를 정의하면 orm.base(namespace)에서 참조됨
# 실제 복구 시에는 private recovery backup의 config/database.py를 사용한다.
post = season.util.stdClass(type="sqlite", path="data/post.db")
base = season.util.stdClass(type="sqlite", path="data/base.db")
trading = season.util.stdClass(type="sqlite", path="data/trading.db")
