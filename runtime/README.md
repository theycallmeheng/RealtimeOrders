# Runtime data

This directory is created by the application for local runtime state, uploads,
logs, certificates, database files, demo credentials, and temporary validation
artifacts. Those machine-specific files are intentionally excluded from Git.

On a fresh installation, create `.env`, run the database migrations, and run
`backend/seed.py`. The seed creates the sample catalog, sample opening stock,
and demo accounts in the local database. Generated account credentials are
written to `runtime/demo-accounts.local.json`; keep that file on the server and
do not share it publicly.

The project root `.gitignore` permits this README while ignoring all other
runtime contents. Store API keys, database passwords, session secrets, TLS
private keys, database files, logs, and user uploads outside Git.
