import logging
import os
import re
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from notifications import ScheduleError, create_scheduler, load_notifications


LOGGER = logging.getLogger("billing_notifier")
REQUIRED_ENV_VARIABLES = ("TELEGRAM_BOT_TOKEN", "LKG_TELEGRAM_CHANNEL")


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Configuration:
    telegram_bot_token: str = field(repr=False)
    telegram_channel: str = field(repr=False)
    port: int = 10000
    timezone: str = "Asia/Kuala_Lumpur"
    notification_time: str = "09:00"


def load_configuration(environment: Mapping[str, str] | None = None) -> Configuration:
    environment = os.environ if environment is None else environment
    missing = []
    for name in REQUIRED_ENV_VARIABLES:
        present = bool(environment.get(name, "").strip())
        LOGGER.info("Required ENV %s: %s", name, "present" if present else "missing")
        if not present:
            missing.append(name)

    if missing:
        raise ConfigurationError("Missing required ENV variables: " + ", ".join(missing))

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

    return Configuration(
        telegram_bot_token=environment["TELEGRAM_BOT_TOKEN"].strip(),
        telegram_channel=environment["LKG_TELEGRAM_CHANNEL"].strip(),
        port=port,
        timezone=timezone,
        notification_time=notification_time,
    )


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        body = b'{"status":"ok"}\n'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        configuration = load_configuration()
        notifications = load_notifications(Path(__file__).with_name("schedule.json"), configuration)
    except (ConfigurationError, ScheduleError) as error:
        LOGGER.error("Startup configuration error: %s", error)
        return 1

    scheduler = create_scheduler(configuration, notifications)
    with ThreadingHTTPServer(("0.0.0.0", configuration.port), HealthHandler) as server:
        scheduler.start()
        LOGGER.info("Notifier ready with %d scheduled reminders; health endpoint ready", len(notifications))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            scheduler.shutdown(wait=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())