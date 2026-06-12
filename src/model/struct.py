# =============================================================================
# 프로젝트 루트 Struct (Composite Struct / Singleton)
# =============================================================================
# 호출 예시:
#   struct = wiz.model("struct")
#   struct.user.list()                    # 프로젝트 고유 User Sub-Struct
#   struct.user.authenticate(email, pw)   # 사용자 인증
#   struct.post.post.search()             # portal/post 패키지 Struct → Post Sub-Struct
#   struct.trading.db("etf_watchlist")    # portal/trading 패키지 Struct
# =============================================================================

class Struct:
    def __init__(self):
        self.orm = wiz.model("portal/season/orm")
        self.session = wiz.model("portal/season/session").use()

        # 프로젝트 고유 Sub-Struct 클래스 로드
        self._User = wiz.model("struct/user")

        # 패키지 Struct 캐시
        self._packages = {}

        # 테이블 자동 생성
        self._init_tables()

    def _init_tables(self):
        """DB 테이블이 없으면 자동 생성"""
        tables = ["user"]
        for name in tables:
            try:
                db = self.orm.use(name)
                db.orm.create_table(safe=True)
            except Exception:
                pass

    def db(self, name):
        """ORM Wrapper 반환 (src/model/db/{name}.py)"""
        return self.orm.use(name)

    @property
    def user(self):
        """User Sub-Struct 접근 (호출마다 새 인스턴스)"""
        return self._User(self)

    def __getattr__(self, name):
        """알 수 없는 속성 → 패키지 Struct 동적 로드"""
        if name.startswith('_'):
            raise AttributeError(name)
        if name not in self._packages:
            try:
                self._packages[name] = wiz.model(f"portal/{name}/struct")
            except Exception as e:
                raise AttributeError(f"Package '{name}' load failed: {e}")
        return self._packages[name]

Model = Struct()
