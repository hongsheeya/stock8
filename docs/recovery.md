# Recovery Notes

This repository is intended to restore the application code, tests, user guide,
automation scripts, and non-secret runtime snapshots.

For a full service restore after the original server disappears, you need both:

1. this public GitHub repository for code; and
2. a private recovery backup for secrets, database/runtime state, and built
   server artifacts.

## Restore Code

```bash
git clone git@github.com:hongsheeya/stock8.git
cd stock8
```

## Latest Public Recovery Point

As of 2026-06-30, the most detailed public recovery point is documented in:

- [latest-state-2026-06-30.md](latest-state-2026-06-30.md)

Use the latest `main` branch first. The 2026-06-30 recovery tags are:

- `recovery-2026-06-30`: code state after the history profit summary fixes
- `recovery-2026-06-30-detailed`: code plus the detailed latest-state document

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

## Private Recovery Backup

The private backup is created outside the repository:

```bash
cd /mnt/data/wiz/project/main
./scripts/create_private_recovery_backup.sh
```

By default it writes:

```text
/mnt/data/wiz/private-backups/stock8-private-recovery-YYYYMMDDTHHMMSSZ.tar.gz
/mnt/data/wiz/private-backups/stock8-private-recovery-YYYYMMDDTHHMMSSZ.tar.gz.sha256
```

Store that archive somewhere private. It may contain:

- `config/`
- `data/`
- `bundle/config/`
- `bundle/www/`
- `build/dist/build/`
- `build/public/`

To restore those files after cloning GitHub:

```bash
cd /mnt/data/wiz/project/main
tar -xzf /path/to/stock8-private-recovery-YYYYMMDDTHHMMSSZ.tar.gz -C /tmp
mkdir -p config data bundle/config bundle/www build/dist/build
cp -a /tmp/stock8-private-recovery-YYYYMMDDTHHMMSSZ/config/. config/
cp -a /tmp/stock8-private-recovery-YYYYMMDDTHHMMSSZ/data/. data/
cp -a /tmp/stock8-private-recovery-YYYYMMDDTHHMMSSZ/bundle/config/. bundle/config/
cp -a /tmp/stock8-private-recovery-YYYYMMDDTHHMMSSZ/bundle/www/. bundle/www/
cp -a /tmp/stock8-private-recovery-YYYYMMDDTHHMMSSZ/build/dist/build/. build/dist/build/
```

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

The GitHub backup alone can restore the code, but it cannot restore live account
connectivity without the private files above.

## Runtime Data Included

The repository may include small JSON snapshots under `data/daytrade/` and repair
backups under `data/backups/` when they do not contain API credentials or tokens.
These are useful for diagnostics and state reconstruction, but secrets must stay
in the private backup channel above.
