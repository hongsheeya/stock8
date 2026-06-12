config = wiz.model("portal/season/config")
BASEURI = config.auth_baseuri
LOGOUT_URI = config.auth_logout_uri
LOGIN_URL = config.auth_login_uri

if wiz.request.match(f"{BASEURI}/check") is not None:
    status = False if wiz.session.user_id() is None else True
    data = wiz.session.get()
    try:
        if status and isinstance(data, dict):
            user = None
            struct = wiz.model("struct")
            user_id = data.get("id")
            email = data.get("email")
            if user_id:
                user = struct.user.get(id=user_id)
            if user is None and email:
                user = struct.user.get_by_email(email=email)
            if user is not None:
                session_data = {
                    "id": user.get("id", data.get("id")),
                    "email": user.get("email", data.get("email")),
                    "name": user.get("name", data.get("name")),
                    "role": user.get("role", data.get("role", "user")),
                }
                wiz.session.set(**session_data)
                data.update(session_data)
    except Exception:
        pass
    wiz.response.status(200, status=status, session=data)

if wiz.request.match(f"{BASEURI}/logout") is not None:
    returnTo = wiz.request.query("returnTo", "/")
    wiz.session.set(returnTo=returnTo)

    if LOGOUT_URI is not None and LOGOUT_URI != f"{BASEURI}/logout":
        wiz.response.redirect(LOGOUT_URI)

    wiz.session.clear()
    wiz.response.redirect(returnTo)

if wiz.request.match(f"{BASEURI}/login") is not None:
    if LOGIN_URL is not None and LOGIN_URL != f"{BASEURI}/login":
        wiz.response.redirect(LOGIN_URL)

if config.auth_saml_use:
    wiz.model("portal/season/auth/saml").proceed()

wiz.response.redirect("/")
