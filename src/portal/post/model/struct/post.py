# =============================================================================
# Post Sub-Struct (게시물 비즈니스 로직)
# =============================================================================
# 사용 패턴:
#   struct = wiz.model("portal/post/struct")
#
#   # 목록 검색
#   rows, total = struct.post.search(text="검색어", category="공지사항", page=1, dump=20)
#
#   # 카테고리 목록
#   cats = struct.post.categories()
#
#   # 인스턴스화 (개별 게시물 접근)
#   post = struct.post("post_id_123")
#   post.data           # 게시물 데이터 dict
#   post.update(data)   # 수정
#   post.delete()       # 삭제
#
#   # 생성
#   post_id = struct.post.create({"title": "제목", "content": "내용", "category": "공지사항"})
# =============================================================================

import datetime

_TIME = wiz.model("portal/trading/kst")

class Post:
    def __init__(self, core):
        """
        Args:
            core: Struct 인스턴스 (DB, 세션 접근용)
        """
        self.core = core
        self.db = core.db("post")
        self.id = None
        self.data = None

    def __call__(self, id):
        """게시물 인스턴스 생성 (ID로 데이터 로드)

        Args:
            id: 게시물 ID

        Returns:
            Post 인스턴스 (self.id, self.data 설정됨)
        """
        inst = Post(self.core)
        inst.id = id
        inst.data = self.db.get(id=id)
        return inst

    def get(self, id=None):
        """게시물 단건 조회

        Args:
            id: 게시물 ID (생략 시 self.id 사용)

        Returns:
            dict 또는 None
        """
        if id is None:
            id = self.id
        return self.db.get(id=id)

    def create(self, data):
        """게시물 생성

        Args:
            data: {"title", "content", "category", "status"} dict

        Returns:
            생성된 게시물 ID (str)
        """
        now = _TIME.normalize(_TIME.now())
        data['created'] = now
        data['updated'] = now
        data['author_id'] = self.core.getUserId()
        data['author_name'] = self.core.getUserName()
        if not data.get('status'):
            data['status'] = 'draft'
        post_id = self.db.insert(data)
        return post_id

    def update(self, data, id=None):
        """게시물 수정

        Args:
            data: 업데이트할 필드 dict
            id: 게시물 ID (생략 시 self.id 사용)
        """
        if id is None:
            id = self.id
        data['updated'] = _TIME.normalize(_TIME.now())
        self.db.update(data, id=id)

    def delete(self, id=None):
        """게시물 삭제 (연관 댓글도 함께 삭제)

        Args:
            id: 게시물 ID (생략 시 self.id 사용)
        """
        if id is None:
            id = self.id
        # 연관 댓글 먼저 삭제
        comment_db = self.core.db("comment")
        comment_db.delete(post_id=id)
        # 게시물 삭제
        self.db.delete(id=id)

    def search(self, text="", category="", status="", page=1, dump=20):
        """게시물 목록 검색 (페이징 지원)

        Args:
            text: 제목 검색어 (LIKE)
            category: 카테고리 필터
            status: 상태 필터 (draft/published/archived)
            page: 페이지 번호 (1부터)
            dump: 페이지당 항목 수

        Returns:
            (rows: list[dict], total: int) 튜플
        """
        kwargs = dict()
        like = None

        if category:
            kwargs['category'] = category
        if status:
            kwargs['status'] = status
        if text:
            kwargs['title'] = text
            like = "title"

        rows = self.db.rows(
            page=page, dump=dump,
            orderby="created", order="DESC",
            like=like,
            **kwargs
        )
        total = self.db.count(like=like, **kwargs) or 0

        return rows, total

    def categories(self):
        """등록된 카테고리 목록 반환 (중복 제거, 정렬)

        Returns:
            list[str]
        """
        rows = self.db.rows(fields="category")
        cats = sorted(set(r['category'] for r in rows if r.get('category')))
        return cats

Model = Post
