import datetime
import time
import zoneinfo
import requests
import datetime
import os
import time
import zoneinfo
import requests

# ============================================================
# إعدادات
# ============================================================
BASE_URL = "https://www.sundair.com/rest"
ORIGIN_AIRPORT = "BER"       # TODO: عدّل حسب المطار اللي عايزه
DEST_AIRPORT = "HRG"         # TODO: عدّل حسب المطار اللي عايزه
BERLIN_TZ = zoneinfo.ZoneInfo("Europe/Berlin")

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Referer": "https://www.sundair.com/booking/",
    "Origin": "https://www.sundair.com",
    # >>> بتيجي من GitHub Secrets (لتجربة محلية: عرّفهم كمتغيرات بيئة
    # >>> قبل التشغيل، مش تكتبهم هنا في الكود مباشرة).
    "Apikey": os.environ.get("SUNDAIR_APIKEY", ""),
    "Authorization": os.environ.get("SUNDAIR_AUTHORIZATION", ""),
}

if not HEADERS["Apikey"] or not HEADERS["Authorization"]:
    raise SystemExit(
        "خطأ: لازم تحدد SUNDAIR_APIKEY و SUNDAIR_AUTHORIZATION "
        "كمتغيرات بيئة (Environment Variables) قبل تشغيل السكربت."
    )


def generate_dates(start_date, end_date):
    dates = []
    curr = start_date
    while curr <= end_date:
        if curr.weekday() in [1, 5]:  # 1 = الثلاثاء, 5 = السبت
            dates.append(curr)
        curr += datetime.timedelta(days=1)
    return dates


def format_dep_after(date_obj):
    """
    بيحول منتصف ليل التاريخ بتوقيت برلين لـUTC، بنفس منطق
    moment(date).startOf('day').utc().format('YYYY-MM-DDTHH:mm:ss[Z]')
    في كود الموقع الأصلي.
    """
    local_midnight = datetime.datetime.combine(
        date_obj, datetime.time(0, 0, 0), tzinfo=BERLIN_TZ
    )
    utc_dt = local_midnight.astimezone(datetime.timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_price_for_date(session, f_date, retries=2):
    payload = {
        "depArprtCode": ORIGIN_AIRPORT,
        "desArprtCode": DEST_AIRPORT,
        "noADT": "1",
        "noCHD": "0",
        "noINF": "0",
        "ojArprtCode": "",
        "ojType": "",
        "depAfter": format_dep_after(f_date),
        "rTrip": False,
        "limit": 5,
    }

    for attempt in range(retries + 1):
        try:
            resp = session.put(
                f"{BASE_URL}/booking/listflights/",
                json=payload,
                headers=HEADERS,
                timeout=20,
            )
            break
        except requests.RequestException as e:
            if attempt == retries:
                return {"price": None, "status": f"ERROR: {e}"}
            time.sleep(2)

    air41_status = resp.headers.get("air41-status")
    if air41_status != "OK":
        error_msg = resp.headers.get("air41-error", "unknown error")
        return {"price": None, "status": f"NICHT VERFÜGBAR ({error_msg})"}

    try:
        data = resp.json()
        flights = data.get("listFlightsRS", {}).get("flts", [])
    except (ValueError, KeyError):
        return {"price": None, "status": "خطأ في قراءة الرد"}

    if not flights:
        return {"price": None, "status": "NICHT VERFÜGBAR"}

    # السعر النهائي لكل رحلة = amnt (سعر الكبير) + tax.tot (الضرائب)
    prices = []
    for flt in flights:
        prcs = flt.get("prcs", [])
        if not prcs:
            continue
        try:
            amnt = float(prcs[0].get("amnt", 0))
            tax = float(prcs[0].get("tax", {}).get("tot", 0))
            prices.append(amnt + tax)
        except (TypeError, ValueError):
            continue

    if not prices:
        return {"price": None, "status": "NICHT VERFÜGBAR"}

    return {"price": min(prices), "status": "متاح"}


def scrape_sundair():
    start = datetime.date(2026, 9, 6)
    end = datetime.date(2026, 12, 31)
    flight_dates = generate_dates(start, end)

    results = []
    with requests.Session() as session:
        for f_date in flight_dates:
            date_str = f_date.strftime("%d.%m.%Y")
            day_name = "الثلاثاء" if f_date.weekday() == 1 else "السبت"

            result = fetch_price_for_date(session, f_date)

            if result["price"] is not None:
                price_str = f"{result['price']:.2f} €"
            else:
                price_str = "غير متوفر"

            results.append(
                {
                    "date": date_str,
                    "day": day_name,
                    "price": price_str,
                    "status": result["status"],
                }
            )
            print(f"{date_str}: {price_str} ({result['status']})")

            time.sleep(1)  # احترام الموقع، عدم القصف بطلبات متتالية سريعة

    build_html(results)


def build_html(data):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = ""
    for item in data:
        color = "#28a745" if "€" in item["price"] else "#dc3545"
        rows += f"""
        <tr>
            <td><b>{item['day']}</b> {item['date']}</td>
            <td><span style="color: {color}; font-weight: bold;">{item['price']}</span></td>
            <td>{item['status']}</td>
        </tr>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>أسعار Sundair الحية</title>
        <style>
            body {{ font-family: system-ui, sans-serif; padding: 15px; background: #f4f6f9; }}
            .card {{ background: white; padding: 20px; border-radius: 12px; max-width: 600px; margin: auto; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
            th, td {{ padding: 10px; border-bottom: 1px solid #eee; text-align: right; }}
            .updated {{ font-size: 0.8em; color: #666; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2 style="text-align:center; color:#0056b3;">جدول أسعار Sundair الحية</h2>
            <p class="updated">آخر تحديث تلقائي: {now}</p>
            <table>
                <thead>
                    <tr><th>التاريخ</th><th>السعر</th><th>الحالة</th></tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </body>
    </html>
    """
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)


if __name__ == "__main__":
    scrape_sundair()
# ============================================================
# إعدادات
# ============================================================
BASE_URL = "https://www.sundair.com/rest"
ORIGIN_AIRPORT = "BER"       # TODO: عدّل حسب المطار اللي عايزه
DEST_AIRPORT = "HRG"         # TODO: عدّل حسب المطار اللي عايزه
BERLIN_TZ = zoneinfo.ZoneInfo("Europe/Berlin")

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Referer": "https://www.sundair.com/booking/",
    "Origin": "https://www.sundair.com",
}


def generate_dates(start_date, end_date):
    dates = []
    curr = start_date
    while curr <= end_date:
        if curr.weekday() in [1, 5]:  # 1 = الثلاثاء, 5 = السبت
            dates.append(curr)
        curr += datetime.timedelta(days=1)
    return dates


def format_dep_after(date_obj):
    """
    بيحول منتصف ليل التاريخ بتوقيت برلين لـUTC، بنفس منطق
    moment(date).startOf('day').utc().format('YYYY-MM-DDTHH:mm:ss[Z]')
    في كود الموقع الأصلي.
    """
    local_midnight = datetime.datetime.combine(
        date_obj, datetime.time(0, 0, 0), tzinfo=BERLIN_TZ
    )
    utc_dt = local_midnight.astimezone(datetime.timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_price_for_date(session, f_date, retries=2):
    payload = {
        "depArprtCode": ORIGIN_AIRPORT,
        "desArprtCode": DEST_AIRPORT,
        "noADT": "1",
        "noCHD": "0",
        "noINF": "0",
        "ojArprtCode": "",
        "ojType": "",
        "depAfter": format_dep_after(f_date),
        "rTrip": False,
        "limit": 5,
    }

    for attempt in range(retries + 1):
        try:
            resp = session.put(
                f"{BASE_URL}/booking/listflights/",
                json=payload,
                headers=HEADERS,
                timeout=20,
            )
            break
        except requests.RequestException as e:
            if attempt == retries:
                return {"price": None, "status": f"ERROR: {e}"}
            time.sleep(2)

    air41_status = resp.headers.get("air41-status")
    if air41_status != "OK":
        error_msg = resp.headers.get("air41-error", "unknown error")
        return {"price": None, "status": f"NICHT VERFÜGBAR ({error_msg})"}

    try:
        data = resp.json()
        flights = data.get("listFlightsRS", {}).get("flts", [])
    except (ValueError, KeyError):
        return {"price": None, "status": "خطأ في قراءة الرد"}

    if not flights:
        return {"price": None, "status": "NICHT VERFÜGBAR"}

    # السعر النهائي لكل رحلة = amnt (سعر الكبير) + tax.tot (الضرائب)
    prices = []
    for flt in flights:
        prcs = flt.get("prcs", [])
        if not prcs:
            continue
        try:
            amnt = float(prcs[0].get("amnt", 0))
            tax = float(prcs[0].get("tax", {}).get("tot", 0))
            prices.append(amnt + tax)
        except (TypeError, ValueError):
            continue

    if not prices:
        return {"price": None, "status": "NICHT VERFÜGBAR"}

    return {"price": min(prices), "status": "متاح"}


def scrape_sundair():
    start = datetime.date(2026, 9, 6)
    end = datetime.date(2026, 12, 31)
    flight_dates = generate_dates(start, end)

    results = []
    with requests.Session() as session:
        for f_date in flight_dates:
            date_str = f_date.strftime("%d.%m.%Y")
            day_name = "الثلاثاء" if f_date.weekday() == 1 else "السبت"

            result = fetch_price_for_date(session, f_date)

            if result["price"] is not None:
                price_str = f"{result['price']:.2f} €"
            else:
                price_str = "غير متوفر"

            results.append(
                {
                    "date": date_str,
                    "day": day_name,
                    "price": price_str,
                    "status": result["status"],
                }
            )
            print(f"{date_str}: {price_str} ({result['status']})")

            time.sleep(1)  # احترام الموقع، عدم القصف بطلبات متتالية سريعة

    build_html(results)


def build_html(data):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = ""
    for item in data:
        color = "#28a745" if "€" in item["price"] else "#dc3545"
        rows += f"""
        <tr>
            <td><b>{item['day']}</b> {item['date']}</td>
            <td><span style="color: {color}; font-weight: bold;">{item['price']}</span></td>
            <td>{item['status']}</td>
        </tr>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>أسعار Sundair الحية</title>
        <style>
            body {{ font-family: system-ui, sans-serif; padding: 15px; background: #f4f6f9; }}
            .card {{ background: white; padding: 20px; border-radius: 12px; max-width: 600px; margin: auto; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
            th, td {{ padding: 10px; border-bottom: 1px solid #eee; text-align: right; }}
            .updated {{ font-size: 0.8em; color: #666; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2 style="text-align:center; color:#0056b3;">جدول أسعار Sundair الحية</h2>
            <p class="updated">آخر تحديث تلقائي: {now}</p>
            <table>
                <thead>
                    <tr><th>التاريخ</th><th>السعر</th><th>الحالة</th></tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </body>
    </html>
    """
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)


if __name__ == "__main__":
    scrape_sundair()
