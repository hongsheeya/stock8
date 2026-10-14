import os
import threading
import time


def bootstrap(app, config):
    """Initialize the in-process PAPER worker without requiring a page visit."""

    def write_bootstrap_log(message):
        try:
            log_root = os.path.join(server.path.project, "main", "data", "runtime-logs")
            os.makedirs(log_root, exist_ok=True)
            with open(os.path.join(log_root, "bootstrap.log"), "a", encoding="utf-8") as log_file:
                log_file.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
        except Exception:
            pass

    def warm_paper_worker():
        time.sleep(2)
        try:
            with app.flask.test_request_context("/stock8-paper-bootstrap"):
                trading = server.wiz().model("struct").trading
                # No browser session exists yet: resume the remembered PAPER owner.
                resume = getattr(trading, "resume_paper_worker", None)
                owner = resume() if resume else ""
                resumed = bool(owner)
                if owner:
                    # Report the resumed owner's worker (state is keyed by owner).
                    import flask
                    flask.session["id"] = owner
                status = trading.worker_status()
                message = (
                    "PAPER worker initialized: "
                    f"started={status.get('started', False)} "
                    f"resumed={resumed} "
                    f"interval={status.get('interval_sec', 0)}s"
                )
                print("Stock8 " + message)
                write_bootstrap_log(message)
        except Exception as exc:
            print(f"Stock8 PAPER worker bootstrap failed: {exc}")
            write_bootstrap_log(f"PAPER worker bootstrap failed: {type(exc).__name__}: {exc}")

    threading.Thread(
        target=warm_paper_worker,
        daemon=True,
        name="stock8-paper-bootstrap",
    ).start()


secret_key = os.environ.get("WIZ_SECRET_KEY", "season-wiz-secret").strip()

socketio = {
    "async_mode": "threading",
    "cors_allowed_origins": "*",
    "async_handlers": True,
    "always_connect": False,
    "manage_session": True,
}

run = {
    "allow_unsafe_werkzeug": True,
    "host": "0.0.0.0",
    "port": int(os.environ.get("PORT", "3000")),
    "use_reloader": False,
    "debug": False,
}
