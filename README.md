# Hermes-Notifier
Generic bill, loan and birthday reminders using Hermes-native cron and Telegram.

## Runtime

The base image is `docker.io/nousresearch/hermes-agent:main`. Its normal
entrypoint, bootstrap and user handling are inherited, not overridden.
The container command uses the installed Hermes Python environment to validate
configuration, reconcile native jobs, and run the native dashboard alongside
`cron.scheduler_provider.InProcessCronScheduler.start`. This is Hermes's built-in
continuous ticker, not APScheduler, a polling implementation or repeated CLI ticks.

Hermes Gateway is not launched. Automatic profile-Gateway boot reconciliation is
disabled in the image so retained Gateway state cannot start it on redeployment.
The image's separate supervised dashboard is disabled to avoid duplicate servers;
the launcher runs the native dashboard directly, including on platforms where the
upstream entrypoint cannot use s6 because it is not PID 1. Dashboard exit stops
the ticker; unexpected ticker exit terminates the service.

All reminder jobs use `no_agent=True` and a script, equivalent to
`hermes cron create ... --no-agent --script ... --deliver telegram`.
Scripts only print the reminder text. Hermes performs execution and Telegram
delivery using its standalone sender; no Gateway or model is needed. Managed
local-model startup is disabled. The dashboard includes broader Hermes tools;
Gateway and interactive agent workflows are not part of this notifier service.

## Render Deployment

Select a Docker web service using the repository-root `Dockerfile`. Leave the
Docker command override empty. Set the health check path to `/api/status`.
The authenticated Hermes dashboard is at the service's root URL and listens on
`0.0.0.0:$PORT`. Render's `RENDER_EXTERNAL_URL` is mapped to Hermes's public URL
for browser and WebSocket authentication; set `HERMES_DASHBOARD_PUBLIC_URL` to
override it, for example when using a custom domain.

Build locally:

```sh
docker build --pull -t hermes-notifier .
```

The build checks the installed native APIs and runs tests with temporary state
and dummy credentials, without contacting Telegram. An incompatible moving
`main` image fails those checks rather than falling back to another scheduler.
Build tests do not validate Render's runtime ENV values or prove a successful
Render launch.

## Environment Configuration

Set these required names in Render's Environment settings, not in source:

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Secret Telegram bot API token. |
| `LKG_TELEGRAM_CHANNEL` | Numeric chat ID or `@channel_username`; the bot needs posting permission. |
| `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` | Dashboard login username. |
| `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD` | Strong secret dashboard login password. |

The original Telegram variable names are preserved. `LKG_TELEGRAM_CHANNEL` is
mapped to Hermes's `TELEGRAM_HOME_CHANNEL`, with no provider-specific meaning.
Required names and presence are logged, never values. Missing values, malformed
Telegram settings, invalid ports, timezones and send times fail startup clearly.
Format validation does not prove Telegram credentials or permissions work.
Runtime logging redacts the configured credentials and destination, including
exception text. Native secrets are seeded into the private runtime `.env` so
Hermes's scoped secret lookup sees the deployment settings.

Optional settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `10000` | Supplied by Render; valid range 1-65535. |
| `TIMEZONE` | `Asia/Kuala_Lumpur` | IANA timezone mapped to `HERMES_TIMEZONE` and native config. |
| `NOTIFICATION_TIME` | `09:00` | Send time in that timezone, `HH:MM` (24-hour). |
| `HERMES_DASHBOARD_PUBLIC_URL` | Render external URL | Public dashboard URL for a custom domain. |

## Reminders And Manual Runs

`schedule.json` is baked into the image and remains the reminder source of
truth. Edit it and redeploy to add or change generic bills, loans or birthdays.
All 13 supplied reminders and their configured send time are preserved:

- Every month on day 7: Air Selangor and Unifi.
- Every month on day 16: TNB and PTPTN.
- January and July on day 7: Indah Water, as a separate message.
- Ten annual birthdays. Dates are `MM:DD`, not clock times.

Monthly schedules use `minute hour day * *`; named months become numeric cron
month lists; birthdays use `minute hour day month *`. Stable
`billing-notifier:` names identify owned jobs. Seeding creates missing jobs,
updates changed fields only, and removes obsolete owned jobs. Existing IDs,
paused state, history and unchanged next-run times are retained when state
survives; unrelated jobs are untouched. Dashboard edits to owned definitions
are reconciled from repository configuration on the next boot.

Use the dashboard's Cron view to inspect, pause, resume or manually run a job.
Native CLI commands in the container provide the same controls:

```sh
hermes cron list
hermes cron status
hermes cron run "billing-notifier:bill_cron-0"
hermes cron history
```

Messages are reminders, not account lookups or payment verification. Native
Hermes owns scheduling, missed-run handling, claims, execution history and
delivery errors. `/api/status` is a health probe, not evidence of a successful
Telegram send. Check native Cron history and delivery status separately.

Run local configuration, conversion, reconciliation and lifecycle tests:

```sh
python -m pip install -r requirements.txt
python -m unittest test_notifications -v
```

The native integration test skips outside the Hermes runtime and runs during
Docker builds. No model or real Telegram credentials are used in tests.

## Free Render Limits

- Sleep prevents the native ticker from running. Timely delivery is not
	guaranteed; lost runtime state also means missed reminders cannot reliably
	be reconstructed. Reliable delivery requires an always-on deployment.
- Native jobs and history live under `$HERMES_HOME/cron`, scripts under
	`$HERMES_HOME/scripts`. Free Render storage is ephemeral. Image definitions
	are reseeded after replacement, but runtime history and pause changes can be
	lost. There is no durable exactly-once guarantee or external scheduler.
- The full Hermes runtime and dashboard remain present. Actual startup,
	Telegram delivery and operation within 512 MB have not been verified here.
	No model is loaded for reminder execution; disabling agent work does not
	prove the entire dashboard will remain within the memory limit.
- The `main` tag can change. Pin a tested digest for reproducible deployment.
