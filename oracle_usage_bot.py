import os
import oci
import requests
import datetime
import time
from dotenv import load_dotenv
from croniter import croniter
import threading

load_dotenv()

config = {
    "user": os.getenv("OCI_USER_OCID"),
    "key_file": "./key.pem",
    "fingerprint": os.getenv("OCI_FINGERPRINT"),
    "tenancy": os.getenv("OCI_TENANCY_OCID"),
    "region": os.getenv("OCI_REGION"),
}

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
MIN_DAILY_USAGE = float(os.getenv("MIN_DAILY_USAGE", 0))
MAX_DAILY_USAGE = float(os.getenv("MAX_DAILY_USAGE", 0))
CURRENCY = os.getenv("CURRENCY", "$")

SUMMARY_SCHEDULE = os.getenv("SUMMARY_SCHEDULE")
DAILY_LIMIT_SCHEDULE = os.getenv("DAILY_LIMIT_SCHEDULE")

def get_cron_schedules():
    default_summary_cron = "0 0 * * 0"
    default_alert_cron = "0 0 * * *"
    summary = SUMMARY_SCHEDULE or default_summary_cron
    daily_limit = DAILY_LIMIT_SCHEDULE or default_alert_cron
    return summary, daily_limit

def check_oracle_credentials():
    try:
        usage_client = oci.usage_api.UsageapiClient(config)
        now = datetime.datetime.utcnow()
        start = (now - datetime.timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = (now - datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        request = oci.usage_api.models.RequestSummarizedUsagesDetails(
            tenant_id=config["tenancy"],
            time_usage_started=start,
            time_usage_ended=end,
            granularity="DAILY"
        )
        usage_client.request_summarized_usages(request)
        print("[INFO] Oracle Cloud API credentials: SUCCESS")
    except Exception as e:
        print(f"[ERROR] Oracle Cloud API credentials: FAILURE - {e}")
        exit(1)


def get_usage(start_time, end_time, granularity):
    print(f"[DEBUG] get_usage called with start_time={start_time}, end_time={end_time}, granularity={granularity}")
    usage_client = oci.usage_api.UsageapiClient(config)
    request = oci.usage_api.models.RequestSummarizedUsagesDetails(
        tenant_id=config["tenancy"],
        time_usage_started=start_time,
        time_usage_ended=end_time,
        granularity=granularity
    )
    print(f"[DEBUG] Request object: {request}")
    try:
        response = usage_client.request_summarized_usages(request)
        print(f"[DEBUG] API response: {response}")
    except Exception as e:
        print(f"[ERROR] Exception during API call: {e}")
        raise
    usage = 0.0
    if hasattr(response.data, 'items') and response.data.items:
        for idx, item in enumerate(response.data.items):
            value = getattr(item, 'computed_amount', None)
            print(f"[DEBUG] Item {idx}: {item}, computed_amount={value}, type={type(value)}")
            if value is None:
                value = 0.0
            try:
                usage += float(value)
            except Exception as e:
                print(f"[ERROR] Failed to add value for item {idx}: {value} ({type(value)}): {e}")
    else:
        print(f"[DEBUG] No items in response.data.items or items is empty: {getattr(response.data, 'items', None)}")
    print(f"[DEBUG] Final usage sum: {usage}")
    return usage


def send_webhook_embed(daily, weekly, monthly, yearly, alert=False, limit=None):
    if alert:
        color = 0xe74c3c
        title = "🚨 Oracle Cloud Usage Limit Exceeded!"
        description = f"Your daily usage is higher than your limit **{CURRENCY}{limit:.2f}** !"
        fields = [
            {"name": "Daily Usage", "value": f"```ansi\n\u001b[31m{CURRENCY}{daily:.2f}\n```", "inline": False},
        ]
    else:
        color = 0x3498db
        title = "Oracle Cloud Usage Report"
        description = "Here is your Oracle Cloud usage summary."
        fields = [
            {"name": "Daily Usage", "value": f"```{CURRENCY}{daily:.2f}```", "inline": False},
            {"name": "Weekly", "value": f"```{CURRENCY}{weekly:.2f}```", "inline": True},
            {"name": "Monthly", "value": f"```{CURRENCY}{monthly:.2f}```", "inline": True},
            {"name": "Annually", "value": f"```{CURRENCY}{yearly:.2f}```", "inline": True},
        ]
    embed = {
        "title": title,
        "description": description,
        "color": color,
        "fields": fields,
        "timestamp": datetime.datetime.utcnow().isoformat()
    }
    data = {"embeds": [embed]}
    response = requests.post(WEBHOOK_URL, json=data)
    if response.status_code not in (200, 204):
        print(f"Failed to send webhook: {response.status_code} {response.text}")


def send_summary_notification():
    try:
        now = datetime.datetime.utcnow()
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_tomorrow = start_of_today + datetime.timedelta(days=1)
        start_of_week = (start_of_today - datetime.timedelta(days=start_of_today.weekday()))
        start_of_next_week = start_of_week + datetime.timedelta(days=7)
        start_of_month = start_of_today.replace(day=1)
        if start_of_month.month == 12:
            start_of_next_month = start_of_month.replace(year=start_of_month.year + 1, month=1)
        else:
            start_of_next_month = start_of_month.replace(month=start_of_month.month + 1)
        start_of_year = start_of_today.replace(month=1, day=1)
        start_of_next_year = start_of_year.replace(year=start_of_year.year + 1)

        daily = get_usage(start_of_today, start_of_tomorrow, "DAILY")
        weekly = get_usage(start_of_week, start_of_next_week, "DAILY")
        monthly = get_usage(start_of_month, start_of_next_month, "MONTHLY")
        yearly = get_usage(start_of_year, start_of_next_year, "MONTHLY")

        send_webhook_embed(daily, weekly, monthly, yearly)
    except Exception as e:
        print(f"[ERROR] [SUMMARY] Exception: {e}")
        data = {"content": f"Error fetching Oracle Cloud usage (summary): {e}"}
        requests.post(WEBHOOK_URL, json=data)

def send_daily_limit_alert():
    try:
        now = datetime.datetime.utcnow()
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_tomorrow = start_of_today + datetime.timedelta(days=1)
        daily = get_usage(start_of_today, start_of_tomorrow, "DAILY")
        if daily >= MIN_DAILY_USAGE:
            send_webhook_embed(daily, None, None, None, alert=True, limit=MIN_DAILY_USAGE)
    except Exception as e:
        print(f"[ERROR] [ALERT] Exception: {e}")
        data = {"content": f"Error fetching Oracle Cloud usage (alert): {e}"}
        requests.post(WEBHOOK_URL, json=data)

def cron_loop():
    check_oracle_credentials()
    summary_cron, alert_cron = get_cron_schedules()
    print(f"[INFO] Using SUMMARY_SCHEDULE: {summary_cron}")
    print(f"[INFO] Using DAILY_LIMIT_SCHEDULE: {alert_cron}")

    def run_cron(cron_expr, func, label):
        now = datetime.datetime.now()
        cron = croniter(cron_expr, now)
        while True:
            next_run = cron.get_next(datetime.datetime)
            sleep_seconds = (next_run - datetime.datetime.now()).total_seconds()
            print(f"[INFO] Next {label} check at {next_run} (in {sleep_seconds:.0f} seconds)")
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            func()

    threading.Thread(target=run_cron, args=(summary_cron, send_summary_notification, "SUMMARY"), daemon=True).start()
    threading.Thread(target=run_cron, args=(alert_cron, send_daily_limit_alert, "ALERT"), daemon=True).start()

    while True:
        time.sleep(3600)

if __name__ == "__main__":
    cron_loop() 