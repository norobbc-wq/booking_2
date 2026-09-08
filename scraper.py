import datetime
import json
import os
import time
import zoneinfo
import requests

# ============================================================
# إعدادات
# ============================================================
BASE_URL = "https://www.sundair.com/rest"
AIRPORT_BER = "BER"
AIRPORT_DAM = "DAM"
BERLIN_TZ = zoneinfo.ZoneInfo("Europe/Berlin")

AIRPORT_NAMES = {"BER": "برلين", "DAM": "دمشق"}

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Referer": "https://www.sundair.com/booking/",
    "Origin": "https://www.sundair.com",
    "Apikey": os.environ.get("SUNDAIR_APIKEY", ""),
    "Authorization": os.environ.get("SUNDAIR_AUTHORIZATION", ""),
}

DEBUG = os.environ.get("SCRAPER_DEBUG", "0") == "1"

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
    local_midnight = datetime.datetime.combine(
        date_obj, datetime.time(0, 0, 0), tzinfo=BERLIN_TZ
    )
    utc_dt = local_midnight.astimezone(datetime.timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def extract_time(dt_string):
    """يحاول يطلع الساعة:الدقيقة من أي تنسيق تاريخ/وقت راجع من الـAPI."""
    if not dt_string:
        return "-"
    try:
        # يشتغل مع صيغ زي: 2026-11-24T10:00:00+0100 أو ...Z
        cleaned = dt_string.replace("Z", "+00:00")
        # لو الأوفست من غير ':' زي +0100 نظبطه لـ +01:00
        if len(cleaned) >= 5 and cleaned[-5] in "+-" and ":" not in cleaned[-5:]:
            cleaned = cleaned[:-2] + ":" + cleaned[-2:]
        dt = datetime.datetime.fromisoformat(cleaned)
        return dt.strftime("%H:%M")
    except (ValueError, IndexError):
        # fallback: نلاقي 'T' ونقص الوقت يدوي
        if "T" in dt_string:
            return dt_string.split("T")[1][:5]
        return "-"


def find_flight_number(flt):
    """يدور على رقم الرحلة تحت أكتر من اسم محتمل للحقل."""
    for key in ("flightNo", "flightNumber", "no", "flightNr", "num"):
        if flt.get(key):
            return flt[key]
    return "-"


def fetch_flight_for_date(session, dep_code, des_code, f_date, retries=2):
    payload = {
        "depArprtCode": dep_code,
        "desArprtCode": des_code,
        "noADT": "1",
        "noCHD": "0",
        "noINF": "0",
        "ojArprtCode": "",
        "ojType": "",
        "depAfter": format_dep_after(f_date),
        "rTrip": False,
        "limit": 5,
    }

    resp = None
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
                return {"available": False, "error": str(e)}
            time.sleep(2)

    air41_status = resp.headers.get("air41-status")
    if air41_status != "OK":
        error_msg = resp.headers.get("air41-error", "unknown error")
        return {"available": False, "error": error_msg}

    try:
        data = resp.json()
        flights = data.get("listFlightsRS", {}).get("flts", [])
    except (ValueError, KeyError):
        return {"available": False, "error": "خطأ في قراءة الرد"}

    if DEBUG and flights:
        print("---- DEBUG: أول رحلة راجعة من الـAPI ----")
        print(json.dumps(flights[0], ensure_ascii=False, indent=2))
        print("-------------------------------------------")

    # >>> فلترة: نقبل بس الرحلات اللي فعلاً في نفس التاريخ المطلوب
    # >>> (depAfter بيرجع "من هذا التاريخ فصاعدًا" مش "في هذا التاريخ بالظبط")
    target_date_str = f_date.strftime("%Y-%m-%d")
    matching = [f for f in flights if target_date_str in f.get("depDT", "")]

    if not matching:
        return {"available": False, "error": "NICHT VERFÜGBAR"}

    best_flt = None
    best_price = None
    for flt in matching:
        prcs = flt.get("prcs", [])
        if not prcs:
            continue
        try:
            amnt = float(prcs[0].get("amnt", 0))
            tax = float(prcs[0].get("tax", {}).get("tot", 0))
            total = amnt + tax
        except (TypeError, ValueError):
            continue
        if best_price is None or total < best_price:
            best_price = total
            best_flt = flt

    if best_flt is None:
        return {"available": False, "error": "NICHT VERFÜGBAR"}

    return {
        "available": True,
        "price": best_price,
        "flight_no": find_flight_number(best_flt),
        "dep_time": extract_time(best_flt.get("depDT")),
        "arr_time": extract_time(best_flt.get("desDT")),
    }


def scrape_sundair():
    start = datetime.date(2026, 10, 1)
    end = datetime.date(2027, 3, 31)
    flight_dates = generate_dates(start, end)

    results = []
    with requests.Session() as session:
        for f_date in flight_dates:
            date_str = f_date.strftime("%d.%m.%Y")
            day_name = "الثلاثاء" if f_date.weekday() == 1 else "السبت"

            outbound = fetch_flight_for_date(session, AIRPORT_BER, AIRPORT_DAM, f_date)
            time.sleep(1)
            inbound = fetch_flight_for_date(session, AIRPORT_DAM, AIRPORT_BER, f_date)
            time.sleep(1)

            results.append(
                {
                    "date": date_str,
                    "day": day_name,
                    "outbound": outbound,
                    "inbound": inbound,
                }
            )

            out_txt = (
                f"{outbound['price']:.2f}€ ({outbound['flight_no']})"
                if outbound["available"]
                else "غير متوفر"
            )
            in_txt = (
                f"{inbound['price']:.2f}€ ({inbound['flight_no']})"
                if inbound["available"]
                else "غير متوفر"
            )
            print(f"{date_str} ({day_name}) | ذهاب BER→DAM: {out_txt} | عودة DAM→BER: {in_txt}")

    build_html(results)


def build_html(data):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    cards = ""
    for item in data:
        out = item["outbound"]
        inb = item["inbound"]

        def leg_html(leg, from_code, to_code, icon_class):
            if leg["available"]:
                return f"""
                <div class="leg available">
                    <div class="leg-route">
                        <span class="airport">{AIRPORT_NAMES[from_code]}</span>
                        <span class="arrow">✈</span>
                        <span class="airport">{AIRPORT_NAMES[to_code]}</span>
                    </div>
                    <div class="leg-flightno">رحلة {leg['flight_no']}</div>
                    <div class="leg-times">{leg['dep_time']} ← {leg['arr_time']}</div>
                    <div class="leg-price">{leg['price']:.2f} €</div>
                </div>
                """
            else:
                return f"""
                <div class="leg unavailable">
                    <div class="leg-route">
                        <span class="airport">{AIRPORT_NAMES[from_code]}</span>
                        <span class="arrow">✈</span>
                        <span class="airport">{AIRPORT_NAMES[to_code]}</span>
                    </div>
                    <div class="leg-status">غير متوفر</div>
                </div>
                """

        cards += f"""
        <div class="date-card">
            <div class="date-header">
                <span class="day-name">{item['day']}</span>
                <span class="date-value">{item['date']}</span>
            </div>
            <div class="legs-wrap">
                {leg_html(out, 'BER', 'DAM', 'out')}
                {leg_html(inb, 'DAM', 'BER', 'in')}
            </div>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>أسعار Sundair | برلين ⇄ دمشق</title>
        <style>
            * {{ box-sizing: border-box; }}
            body {{
                font-family: 'Segoe UI', Tahoma, sans-serif;
                background: linear-gradient(180deg, #f4f6f9 0%, #e9edf2 100%);
                margin: 0;
                padding: 24px 12px;
                color: #1a1a2e;
            }}
            .page {{
                max-width: 760px;
                margin: 0 auto;
            }}
            .page-header {{
                text-align: center;
                margin-bottom: 24px;
            }}
            .page-header h1 {{
                font-size: 22px;
                color: #0b3d91;
                margin: 0 0 4px;
            }}
            .page-header .route {{
                font-size: 15px;
                color: #555;
            }}
            .page-header .updated {{
                font-size: 12px;
                color: #999;
                margin-top: 6px;
            }}
            .date-card {{
                background: #fff;
                border-radius: 14px;
                box-shadow: 0 3px 12px rgba(0,0,0,0.07);
                margin-bottom: 16px;
                overflow: hidden;
            }}
            .date-header {{
                background: #ffb400;
                padding: 10px 18px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-weight: 700;
                color: #fff;
            }}
            .date-header .day-name {{
                font-size: 15px;
            }}
            .date-header .date-value {{
                font-size: 15px;
            }}
            .legs-wrap {{
                display: flex;
                flex-wrap: wrap;
            }}
            .leg {{
                flex: 1 1 50%;
                min-width: 220px;
                padding: 14px 18px;
                border-bottom: 1px solid #f0f0f0;
            }}
            .leg:first-child {{
                border-left: 1px solid #f0f0f0;
            }}
            .leg-route {{
                font-size: 13px;
                color: #555;
                margin-bottom: 4px;
            }}
            .leg-route .arrow {{
                color: #ffb400;
                margin: 0 6px;
            }}
            .leg-flightno {{
                font-size: 12px;
                color: #999;
                margin-bottom: 2px;
            }}
            .leg-times {{
                font-size: 13px;
                color: #333;
                margin-bottom: 6px;
            }}
            .leg-price {{
                font-size: 20px;
                font-weight: 800;
                color: #28a745;
            }}
            .leg.unavailable .leg-status {{
                font-size: 15px;
                font-weight: 700;
                color: #dc3545;
                margin-top: 8px;
            }}
            .leg.unavailable {{
                opacity: 0.75;
            }}
            @media (max-width: 480px) {{
                .legs-wrap {{ flex-direction: column; }}
                .leg:first-child {{ border-left: none; border-bottom: 1px solid #f0f0f0; }}
            }}
        </style>
    </head>
    <body>
        <div class="page">
            <div class="page-header">
                <h1>✈ أسعار Sundair الحية</h1>
                <div class="route">برلين براندنبورج (BER) ⇄ دمشق (DAM)</div>
                <div class="updated">آخر تحديث تلقائي: {now}</div>
            </div>
            {cards}
        </div>
    </body>
    </html>
    """
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)


if __name__ == "__main__":
    scrape_sundair()
