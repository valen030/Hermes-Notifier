import logging
import os
import re
import signal
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from notifications import ScheduledNotification, ScheduleError, load_notifications, seed_jobs


LOGGER = logging.getLogger("billing_notifier")
REQUIRED_ENV_VARIABLES = ("TELEGRAM_BOT_TOKEN", "LKG_TELEGRAM_CHANNEL")
DASHBOARD_ENV_VARIABLES = (
    "HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD",
)


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Configuration:
    telegram_bot_token: str = field(repr=False)
    telegram_channel: str = field(repr=False)
    port: int = 10000
    timezone: str = "Asia/Kuala_Lumpur"
    notification_time: str = "09:00"
    dashboard_username: str = field(default="", repr=False)
    dashboard_password: str = field(default="", repr=False)
    dashboard_public_url: str = ""


def load_configuration(environment: Mapping[str, str] | None = None) -> Configuration:
    environment = os.environ if environment is None else environment
    missing = []
    for name in REQUIRED_ENV_VARIABLES + DASHBOARD_ENV_VARIABLES:
        present = bool(environment.get(name, "").strip())
        LOGGER.info("Required ENV %s: %s", name, "present" if present else "missing")
        if not present:
            missing.append(name)

    if missing:
        raise ConfigurationError("Missing required ENV variables: " + ", ".join(missing))

    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{20,}", environment["TELEGRAM_BOT_TOKEN"].strip()):
        raise ConfigurationError("TELEGRAM_BOT_TOKEN must have the Telegram bot-token format")
    if not re.fullmatch(r"-?[1-9][0-9]*|@[A-Za-z][A-Za-z0-9_]{4,31}",
                        environment["LKG_TELEGRAM_CHANNEL"].strip()):
        raise ConfigurationError("LKG_TELEGRAM_CHANNEL must be a numeric chat ID or @channel username")

    try:
        port = int(environment.get("PORT", "10000"))
    except ValueError:
        raise ConfigurationError("PORT must be an integer between 1 and 65535") from None
    if not 1 <= port <= 65535:
        raise ConfigurationError("PORT must be an integer between 1 and 65535")

    timezone = environment.get("TIMEZONE", "Asia/Kuala_Lumpur").strip()
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigurationError("TIMEZONE must be a valid IANA timezone") from None
    notification_time = environment.get("NOTIFICATION_TIME", "09:00").strip()
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", notification_time):
        raise ConfigurationError("NOTIFICATION_TIME must be HH:MM in 24-hour time")
    public_url = (environment.get("HERMES_DASHBOARD_PUBLIC_URL")
                  or environment.get("RENDER_EXTERNAL_URL", "")).strip()
    if public_url:
        try:
            parsed_url = urlparse(public_url)
            valid_url = (parsed_url.scheme in ("http", "https") and parsed_url.hostname
                         and not parsed_url.username and not parsed_url.password)
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ConfigurationError("Dashboard public URL must be an HTTP(S) URL without credentials")

    return Configuration(
        telegram_bot_token=environment["TELEGRAM_BOT_TOKEN"].strip(),
        telegram_channel=environment["LKG_TELEGRAM_CHANNEL"].strip(),
        port=port,
        timezone=timezone,
        notification_time=notification_time,
        dashboard_username=environment[DASHBOARD_ENV_VARIABLES[0]].strip(),
        dashboard_password=environment[DASHBOARD_ENV_VARIABLES[1]].strip(),
        dashboard_public_url=public_url,
    )


class SecretFormatter(logging.Formatter):
    def __init__(self, secrets: tuple[str, ...]):
        super().__init__("%(levelname)s %(message)s")
        self.secrets = tuple(value for value in secrets if value)

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        for value in self.secrets:
            message = message.replace(value, "[REDACTED]")
        return message


def install_log_redaction(secrets: tuple[str, ...]) -> None:
    previous_factory = logging.getLogRecordFactory()
    formatter = SecretFormatter(secrets)

    def record_factory(*args, **kwargs):
        record = previous_factory(*args, **kwargs)
        message = record.getMessage()
        exception = "".join(traceback.format_exception(*record.exc_info)) if record.exc_info else None
        for value in formatter.secrets:
            message = message.replace(value, "[REDACTED]")
            if exception:
                exception = exception.replace(value, "[REDACTED]")
        record.msg = message
        record.args = ()
        if exception:
            record.exc_text = exception
            record.exc_info = None
        return record

    logging.setLogRecordFactory(record_factory)


def prepare_runtime(configuration: Configuration) -> Path:
    from dotenv import set_key
    from hermes_cli.profiles import get_profile_dir
    import yaml

    home = get_profile_dir("default")
    os.environ["HERMES_HOME"] = str(home)
    home.mkdir(parents=True, exist_ok=True)
    environment = {
        "TELEGRAM_BOT_TOKEN": configuration.telegram_bot_token,
        "TELEGRAM_HOME_CHANNEL": configuration.telegram_channel,
        "HERMES_DASHBOARD_BASIC_AUTH_USERNAME": configuration.dashboard_username,
        "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": configuration.dashboard_password,
        "TZ": configuration.timezone,
        "HERMES_TIMEZONE": configuration.timezone,
    }
    if configuration.dashboard_public_url:
        environment["HERMES_DASHBOARD_PUBLIC_URL"] = configuration.dashboard_public_url
    environment_path = home / ".env"
    descriptor = os.open(environment_path, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(descriptor)
    environment_path.chmod(0o600)
    for name, value in environment.items():
        set_key(str(environment_path), name, value)
    environment_path.chmod(0o600)
    os.environ.update(environment)

    config_path = home / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ConfigurationError("Hermes config.yaml must contain a mapping")
    config["timezone"] = configuration.timezone
    if configuration.dashboard_public_url:
        dashboard = config.setdefault("dashboard", {})
        if not isinstance(dashboard, dict):
            raise ConfigurationError("Hermes dashboard configuration must contain a mapping")
        dashboard["public_url"] = configuration.dashboard_public_url
    cron = config.setdefault("cron", {})
    if not isinstance(cron, dict):
        raise ConfigurationError("Hermes cron configuration must contain a mapping")
    cron.update(provider="builtin", wrap_response=False)
    local_runtime = config.setdefault("local_runtime", {})
    if not isinstance(local_runtime, dict):
        raise ConfigurationError("Hermes local_runtime configuration must contain a mapping")
    local_runtime["enabled"] = False
    temporary_path = config_path.with_suffix(".yaml.tmp")
    temporary_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    temporary_path.chmod(0o600)
    temporary_path.replace(config_path)
    return home


def verify_dashboard_jobs(home: Path, notifications: list[ScheduledNotification]) -> None:
    from hermes_cli.web_server_cron import _call_cron_for_profile, _cron_profile_home

    profile, dashboard_home = _cron_profile_home("default")
    if dashboard_home.resolve() != home.resolve():
        raise ScheduleError("Notifier and dashboard cron stores do not match for the default profile")
    jobs = _call_cron_for_profile(profile, "list_jobs", True)
    expected = {"billing-notifier:" + item.identifier for item in notifications}
    actual = {job.get("name") for job in jobs}
    missing = expected - actual
    if missing:
        raise ScheduleError(f"Dashboard cron reader is missing {len(missing)} notifier jobs")
    LOGGER.info("Dashboard default profile can read %d notifier jobs from %s", len(expected), home / "cron")


def run_runtime(configuration: Configuration, provider, start_dashboard) -> int:
    stop_event = threading.Event()
    ticker_failed = threading.Event()

    def run_native_ticker() -> None:
        try:
            provider.start(stop_event, interval=60)
        except BaseException:
            ticker_failed.set()
        finally:
            if not stop_event.is_set():
                ticker_failed.set()
                LOGGER.error("Hermes native ticker stopped unexpectedly")
                os.kill(os.getpid(), signal.SIGTERM)

    ticker = threading.Thread(target=run_native_ticker, name="hermes-native-cron", daemon=True)
    ticker.start()
    try:
        start_dashboard(host="0.0.0.0", port=configuration.port, open_browser=False,
                initial_profile="default")
    finally:
        stop_event.set()
        provider.stop()
        ticker.join(timeout=5)
    return 1 if ticker_failed.is_set() else 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    secrets = tuple(os.environ.get(name, "").strip() for name in (
        REQUIRED_ENV_VARIABLES + DASHBOARD_ENV_VARIABLES
    ))
    install_log_redaction(secrets)
    try:
        configuration = load_configuration()
        notifications = load_notifications(Path(__file__).with_name("schedule.json"), configuration)
        home = prepare_runtime(configuration)
        from hermes_cli.plugins import discover_plugins
        discover_plugins()
        from cron.scheduler_provider import InProcessCronScheduler
        from hermes_cli.web_server import start_server
        seed_jobs(home, notifications)
        verify_dashboard_jobs(home, notifications)
    except (ConfigurationError, ScheduleError) as error:
        LOGGER.error("Startup configuration error: %s", error)
        return 1
    except Exception:
        LOGGER.exception("Hermes runtime initialization failed after bootstrap")
        return 1
    LOGGER.info("Hermes ready with %d native reminders; Gateway is disabled", len(notifications))
    return run_runtime(configuration, InProcessCronScheduler(), start_server)


if __name__ == "__main__":
    raise SystemExit(main())