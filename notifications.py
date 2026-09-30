from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app import Configuration


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
    schedule: str


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
                expression = f"{minute} {hour} {day} {month} *"
            except (KeyError, TypeError, ValueError, AttributeError):
                raise ScheduleError(f"Invalid schedule.json entry: {kind}[{index}]") from None
            notifications.append(ScheduledNotification(f"{kind}-{index}", text, expression))
    return notifications


def seed_jobs(home: Path, notifications: list[ScheduledNotification]) -> None:
    from cron.jobs import list_jobs, remove_job, update_job, use_cron_store
    from cron.scheduler import create_job_with_scheduler_registration

    scripts = home / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    with use_cron_store(home):
        existing = list_jobs(include_disabled=True)
        desired_names = {"billing-notifier:" + item.identifier for item in notifications}
        for notification in notifications:
            name = "billing-notifier:" + notification.identifier
            script = scripts / ("billing-notifier-" + notification.identifier + ".py")
            temporary = script.with_suffix(".py.tmp")
            temporary.write_text(f"print({notification.text!r})\n", encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(script)
            matches = [job for job in existing if job.get("name") == name]
            if len(matches) > 1:
                raise ScheduleError("Duplicate Hermes notifier job: " + notification.identifier)
            definition = dict(
                prompt="", schedule=notification.schedule, name=name,
                script=script.name, no_agent=True, deliver="telegram",
            )
            if not matches:
                existing.append(create_job_with_scheduler_registration(**definition))
            else:
                current = matches[0]
                updates = {key: value for key, value in definition.items() if key != "schedule"
                           and current.get(key) != value}
                if (current.get("schedule") or {}).get("expr") != notification.schedule:
                    updates["schedule"] = notification.schedule
                if updates:
                    update_job(current["id"], updates)
        for job in existing:
            name = job.get("name") or ""
            if name.startswith("billing-notifier:") and name not in desired_names:
                remove_job(job["id"])
