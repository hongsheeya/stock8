# Recovery Notes

This repository is intended to restore the application code, tests, user guide,
automation scripts, and non-secret runtime snapshots.

## Restore Code

```bash
git clone git@github.com:hongsheeya/stock8.git
cd stock8
```

The runtime server path used in production was:

```bash
cd /opt/app
setsid /opt/conda/envs/app/bin/wiz run --log /var/log/wiz/app >/tmp/wiz-run.out 2>/tmp/wiz-run.err < /dev/null &
```

## Rebuild Frontend Bundle

Use the project builder, not plain `npm run build`:

```bash
cd /opt/app
/opt/conda/envs/app/bin/wiz project build main
cp -a /mnt/data/wiz/project/main/build/dist/build/. /mnt/data/wiz/project/main/bundle/www/
```

Then restart the server.

## Private Files Not Committed

The GitHub repository is public, so the following are intentionally not tracked:

- `config/`
- `data/*.db`
- `data/db/*.db`
- environment files such as `.env`
- broker credentials, FireGate tokens, scheduler tokens, and database passwords

Back these up through a private channel before a full machine rebuild.

The local `config/database.py` at the time of this note contained a real database
password and must not be published to GitHub.

## Runtime Data Included

The repository may include small JSON snapshots under `data/daytrade/` and repair
backups under `data/backups/` when they do not contain API credentials or tokens.
These are useful for diagnostics and state reconstruction, but secrets must stay
in the private backup channel above.
