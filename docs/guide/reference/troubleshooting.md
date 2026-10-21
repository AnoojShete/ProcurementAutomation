# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| 502 from the gateway after rebuilding a service | nginx cached the old container address | `docker compose restart nginx` |
| A rebuild removed other containers | `--build` re-ran the one-shot `redpanda-init` | `docker compose up -d`, then check `docker compose ps` |
| 429 "Too many requests" | Gateway rate limit on sign-in endpoints | Wait a minute |
| 429 "Too many failed sign-in attempts" | Account lockout | Wait 15 minutes or reset the password |
| Sign-up returns 503 | Breached-password service unreachable | Check internet access |
| File stays in `./inbox/input` | Worker not running, or the file is still growing | `docker compose ps document-vendor-agent-worker`; the file is taken once its size is stable |
| File in `./inbox/failed` | Rejected or failed in the pipeline | Read `<file>.error.txt`, or Control Panel → Documents |
| Uploads return 503 | ClamAV or MinIO down (ClamAV needs ~1 GB RAM) | Raise Docker's memory; check `docker compose ps` |
| First document is slow (~45 s) | Models loading | Wait; later ones are fast |
| LayoutLMv3 stage "skipped: model not installed" | Model not downloaded | `./scripts/download-models.sh` |
| No email in Mailpit | Template turned off, or consumer stopped | Control Panel → Notifications (status *skipped* / *failed*); `curl localhost:8004/health` |
| A Kafka event never arrived | Consumer gave up after retries | Control Panel → Processing and logs → Failed events |
| Assistant doesn't answer | Ollama not running on the host | `brew services start ollama` |
| Leftover "E2E Test Vendor" rows | Test data from e2e suites | `./scripts/reset-demo.sh` (backs up first) |
