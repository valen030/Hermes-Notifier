from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from app import Configuration


LOGGER = logging.getLogger("billing_notifier")
MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)


class ScheduleError(ValueError):
    pass


@dataclass(frozen=True)
class ScheduledNotification:
    identifier: str
    text: str = field(repr=False)
    trigger: CronTrigger


def load_notifications(path: Path, configuration: Configuration) -> list[ScheduledNotification]:
    try:
        schedule = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ScheduleError("schedule.json must be a readable JSON file") from None
    if not isinstance(schedule, dict) or any(
        not isinstance(schedule.get(key), list) for key in ("bill_cron", "birthday_cron")
    ):
        raise ScheduleError("schedule.json requires bill_cron and birthday_cron arrays")

    hour, minute = map(int, configuration.notification_time.split(":"))
    timezone = ZoneInfo(configuration.timezone)
    notifications = []
    for kind in ("bill_cron", "birthday_cron"):
        for index, entry in enumerate(schedule[kind]):
            try:
                if kind == "bill_cron":
                    day = entry["day"]
                    if type(day) is not int or not 1 <= day <= 31:
                        raise ValueError
                    month_text = entry["month"].strip().lower()
                    if month_text == "monthly":
                        month = "*"
                    else:
                        month_numbers = [MONTHS.index(name.strip()) + 1 for name in month_text.split(",")]
                        for month_number in month_numbers:
                            date(2000, month_number, day)
                        month = ",".join(str(number) for number in month_numbers)
                    bills = entry["bills"]
                    if not isinstance(bills, list) or not bills or any(
                        not isinstance(bill, str) or not bill.strip() for bill in bills
                    ):
                        raise ValueError
                    text = "Bill reminder:\n" + "\n".join("- " + bill.strip() for bill in bills)
                else:
                    birthday = entry["date"]
                    if not isinstance(birthday, str) or not re.fullmatch(r"[0-9]{2}:[0-9]{2}", birthday):
                        raise ValueError
                    month, day = map(int, birthday.split(":"))
                    date(2000, month, day)
                    name = entry["name"]
                    if not isinstance(name, str) or not name.strip():
                        raise ValueError
                    text = "Birthday reminder: " + name.strip()
                if len(text) > 4096:
                    raise ValueError
                trigger = CronTrigger(month=month, day=day, hour=hour, minute=minute, timezone=timezone)
            except (KeyError, TypeError, ValueError, AttributeError):
                raise ScheduleError(f"Invalid schedule.json entry: {kind}[{index}]") from None
            notifications.append(ScheduledNotification(f"{kind}-{index}", text, trigger))
    return notifications


def deliver_notification(configuration: Configuration, text: str) -> bool:
    request = Request(
        "https://api.telegram.org/bot" + configuration.telegram_bot_token + "/sendMessage",
        data=json.dumps({"chat_id": configuration.telegram_channel, "text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise ValueError
    except Exception:
        LOGGER.error("Telegram notification failed; no automatic retry")
        return False
    LOGGER.info("Telegram notification sent")
    return True


def create_scheduler(
    configuration: Configuration, notifications: list[ScheduledNotification]
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        timezone=ZoneInfo(configuration.timezone),
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
    )
    for notification in notifications:
        scheduler.add_job(
            deliver_notification,
            trigger=notification.trigger,
            id=notification.identifier,
            args=(configuration, notification.text),
        )
    return scheduler