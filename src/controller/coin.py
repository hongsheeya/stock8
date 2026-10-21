import season


class Controller(wiz.controller("user")):
    def __init__(self):
        super().__init__()
        # 10-22: coin automation is admin only. A controller runs before any
        # /wiz/api/page.coin/* function is looked up, so it covers every
        # module-level name in page.coin/api.py (helpers included).
        uid = wiz.session.get("id")
        user = wiz.model("struct").user.get(id=uid) if uid else None
        role = str((user or {}).get("role", "") or "").lower()
        email = str((user or {}).get("email", "") or "").strip().lower()
        if not (role == "admin" or email == "gigukbyun@gmail.com"):
            wiz.response.status(403, message="코인 자동매매는 관리자 전용 기능입니다.")
