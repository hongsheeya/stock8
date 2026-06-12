# =============================================================================
# Comment Sub-Struct (댓글 비즈니스 로직)
# =============================================================================
# 사용 패턴:
#   struct = wiz.model("portal/post/struct")
#
#   comments = struct.comment.list("post_id_123")
#   count = struct.comment.count("post_id_123")
#   comment_id = struct.comment.create({"post_id": "post_id_123", "content": "댓글 내용"})
#   struct.comment.delete("comment_id_456")
# =============================================================================

import datetime

_TIME = wiz.model("portal/trading/kst")

class Comment:
    def __init__(self, core):
        """
        Args:
            core: Struct 인스턴스 (DB, 세션 접근용)
        """
        self.core = core
        self.db = core.db("comment")

    def list(self, post_id):
        """게시물의 댓글 목록 조회 (오래된 순)

        Args:
            post_id: 게시물 ID

        Returns:
            list[dict]
        """
        return self.db.rows(
            post_id=post_id,
            orderby="created", order="ASC"
        )

    def create(self, data):
        """댓글 생성

        Args:
            data: {"post_id", "content"} dict

        Returns:
            생성된 댓글 ID (str)
        """
        data['created'] = _TIME.normalize(_TIME.now())
        data['author_id'] = self.core.getUserId()
        data['author_name'] = self.core.getUserName()
        return self.db.insert(data)

    def delete(self, id):
        """댓글 삭제

        Args:
            id: 댓글 ID
        """
        self.db.delete(id=id)

    def count(self, post_id):
        """게시물의 댓글 수

        Args:
            post_id: 게시물 ID

        Returns:
            int
        """
        return self.db.count(post_id=post_id) or 0

Model = Comment
