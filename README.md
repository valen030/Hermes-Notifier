# Hermes-Notifier
Notify for bills and loans with simple setup

## Hermes container image

The Dockerfile uses `docker.io/nousresearch/hermes-agent:main` as its base.
Hermes and its dependencies are included in the built image, rather than
installed at startup. The upstream entrypoint is overridden to run `app.py`
directly. Hermes Gateway, its dashboard, and upstream background services are
not started.

Build locally with Docker:

```sh
docker build --pull -t hermes-notifier .
```

For a Render service built from this repository, select the Docker runtime
and the root `Dockerfile`. Leave the Docker command override empty and set the
health check path to `/health`. The application listens on `0.0.0.0:$PORT`.

## Environment configuration

Add these exact required names in Render's Environment settings:

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Secret Telegram bot API token. |
| `LKG_TELEGRAM_CHANNEL` | Destination chat ID (including a negative ID when applicable) or `@channel_username`. The bot must have permission to post there. |

`LKG_TELEGRAM_CHANNEL` is kept as the requested environment name, but is used
as a generic notification destination, with no bill-provider-specific meaning.

Optional: `PORT` is supplied by Render; it defaults to `10000` locally and must
be an integer from 1 to 65535. No credentials have defaults. Missing, empty,
or whitespace-only required values cause startup to exit with code 1 and list
the missing variable names. Startup logs report `present` or `missing` for
each required variable, never its value. Configuration representations also
omit the token and destination.

Optional scheduling settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `TIMEZONE` | `Asia/Kuala_Lumpur` | IANA timezone for all reminders. |
| `NOTIFICATION_TIME` | `09:00` | Daily send time in that timezone, formatted `HH:MM` (24-hour). |

Invalid timezone or time settings fail startup. The notifier installs its small
dependency set into a separate virtual environment; it does not run Hermes.

## Reminder schedules

The supplied schedules are stored in `schedule.json` and baked into the image.
Edit that file and redeploy to change reminders. APScheduler recreates all 13
jobs on each startup, without Hermes Gateway or runtime setup files:

- Every month on day 7: Air Selangor and Unifi.
- Every month on day 16: TNB and PTPTN.
- January and July on day 7: Indah Water (a separate message).
- Ten annual birthday reminders. Birthday `date` values mean `MM:DD`, not
	clock times; for example, `09:30` means September 30.

Messages go to the configured Telegram destination at `NOTIFICATION_TIME`.
These are generic reminders, not bill lookups: the service does not retrieve
balances, verify payment, or use provider account credentials. Bill names are
data, not provider-specific code. Invalid schedule entries fail startup with
the entry's location, without dumping its contents.

Jobs allow up to one hour of lateness while the scheduler is running and
coalesce delayed executions. There is no startup catch-up for reminders missed
while the service was stopped or asleep. Failed Telegram requests are logged
without URLs, tokens, destination IDs, or response bodies; they are not retried
automatically because an ambiguous timeout could already have delivered a
message. There is no durable delivery history or exactly-once guarantee.

The health endpoint confirms that startup succeeded, not that Telegram
credentials are valid or notifications have been delivered. Local tests and
Docker builds cannot verify Render's runtime ENV values. Those values are read
only when the deployed application starts; their presence is not a credential
validity check.

Run the configuration and health tests without Docker:

```sh
python -m pip install -r requirements.txt
python -m unittest test_notifications -v
```

## Free Render limits

- Image contents remain available when Render starts a new container.
- Runtime files are not persistent on the free service. Reminder definitions
  survive restarts because they are baked into the image; any future durable
  delivery history needs external storage. A Docker volume declaration does
  not provide persistent storage on free Render.
- Set credentials through Render environment variables, not in this repository
	or the image.
- The notifier runs only a lightweight scheduler and health server, not Hermes
  or browser tools. Its behavior under Render's 512 MB limit is not verified.
- Free web services can sleep when idle, so they cannot guarantee timely bill
	or loan notifications. Reliable scheduling needs an always-on service or an
	external scheduler.
- The `main` image tag can change. Pin a tested image digest before relying on
	reproducible deployments.
