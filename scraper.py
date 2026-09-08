import calendar
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


def add_months(d, months):
    """يضيف عدد شهور لتاريخ، مع مراعاة اختلاف عدد أيام الشهور."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


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
    if not dt_string:
        return "-"
    try:
        cleaned = dt_string.replace("Z", "+00:00")
        if len(cleaned) >= 5 and cleaned[-5] in "+-" and ":" not in cleaned[-5:]:
            cleaned = cleaned[:-2] + ":" + cleaned[-2:]
        dt = datetime.datetime.fromisoformat(cleaned)
        return dt.strftime("%H:%M")
    except (ValueError, IndexError):
        if "T" in dt_string:
            return dt_string.split("T")[1][:5]
        return "-"


def find_flight_number(flt):
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
    start = datetime.date.today()
    end = add_months(start, 6)
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
                    "date_iso": f_date.isoformat(),
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

    build_outputs(results)


def build_outputs(results):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # ------------------------------------------------------------
    # 1) data.json — بيانات خام يستخدمها الرسم البياني
    # ------------------------------------------------------------
    chart_data = {
        "generated_at": now,
        "outbound": [
            {
                "date": r["date_iso"],
                "date_display": r["date"],
                "day": r["day"],
                "price": r["outbound"]["price"] if r["outbound"]["available"] else None,
                "flight_no": r["outbound"].get("flight_no") if r["outbound"]["available"] else None,
            }
            for r in results
        ],
        "inbound": [
            {
                "date": r["date_iso"],
                "date_display": r["date"],
                "day": r["day"],
                "price": r["inbound"]["price"] if r["inbound"]["available"] else None,
                "flight_no": r["inbound"].get("flight_no") if r["inbound"]["available"] else None,
            }
            for r in results
        ],
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(chart_data, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------
    # 2) index.html — جدولين (ذهاب / عودة)
    # ------------------------------------------------------------
    def build_table_rows(leg_key, from_code, to_code):
        rows = ""
        for r in results:
            leg = r[leg_key]
            if leg["available"]:
                price_html = f'<span class="price-ok">{leg["price"]:.2f} €</span>'
                flight_html = leg.get("flight_no", "-")
                status_html = '<span class="status-ok">متاح</span>'
            else:
                price_html = "-"
                flight_html = "-"
                status_html = '<span class="status-bad">غير متوفر</span>'
            rows += f"""
            <tr>
                <td>{r['date']}</td>
                <td>{r['day']}</td>
                <td>{flight_html}</td>
                <td>{price_html}</td>
                <td>{status_html}</td>
            </tr>
            """
        return rows

    outbound_rows = build_table_rows("outbound", "BER", "DAM")
    inbound_rows = build_table_rows("inbound", "DAM", "BER")

    index_html = f"""
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
                max-width: 900px;
                margin: 0 auto;
            }}
            .page-header {{
                text-align: center;
                margin-bottom: 20px;
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
            .chart-btn-wrap {{
                text-align: center;
                margin-bottom: 28px;
            }}
            .chart-btn {{
                display: inline-block;
                background: #0b3d91;
                color: #fff;
                text-decoration: none;
                padding: 10px 24px;
                border-radius: 24px;
                font-weight: 700;
                font-size: 14px;
                box-shadow: 0 3px 10px rgba(11,61,145,0.3);
            }}
            .section {{
                background: #fff;
                border-radius: 14px;
                box-shadow: 0 3px 12px rgba(0,0,0,0.07);
                margin-bottom: 24px;
                overflow: hidden;
            }}
            .section-header {{
                background: #ffb400;
                padding: 12px 18px;
                font-weight: 700;
                color: #fff;
                font-size: 16px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
            }}
            th, td {{
                padding: 10px 14px;
                text-align: center;
                border-bottom: 1px solid #f0f0f0;
                font-size: 14px;
            }}
            th {{
                background: #f8f9fb;
                color: #555;
                font-weight: 600;
            }}
            tr:hover td {{ background: #fafcff; }}
            .price-ok {{ color: #28a745; font-weight: 800; }}
            .status-ok {{ color: #28a745; font-weight: 600; }}
            .status-bad {{ color: #dc3545; font-weight: 600; }}
        </style>
    </head>
    <body>
        <div class="page">
            <div class="page-header">
                <h1>✈ أسعار Sundair الحية</h1>
                <div class="route">برلين براندنبورج (BER) ⇄ دمشق (DAM)</div>
                <div class="updated">آخر تحديث تلقائي: {now}</div>
            </div>

            <div class="chart-btn-wrap">
                <a class="chart-btn" href="chart.html">📈 عرض الرسم البياني للأسعار</a>
            </div>

            <div class="section">
                <div class="section-header">🛫 رحلات الذهاب (برلين ← دمشق)</div>
                <table>
                    <thead>
                        <tr>
                            <th>التاريخ</th><th>اليوم</th><th>رقم الرحلة</th><th>السعر</th><th>الحالة</th>
                        </tr>
                    </thead>
                    <tbody>{outbound_rows}</tbody>
                </table>
            </div>

            <div class="section">
                <div class="section-header">🛬 رحلات العودة (دمشق ← برلين)</div>
                <table>
                    <thead>
                        <tr>
                            <th>التاريخ</th><th>اليوم</th><th>رقم الرحلة</th><th>السعر</th><th>الحالة</th>
                        </tr>
                    </thead>
                    <tbody>{inbound_rows}</tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(index_html)

    # ------------------------------------------------------------
    # 3) chart.html — رسم بياني (خط) للأسعار عبر التواريخ
    # ------------------------------------------------------------
    chart_html = f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>الرسم البياني للأسعار | Sundair برلين ⇄ دمشق</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
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
                max-width: 950px;
                margin: 0 auto;
            }}
            .page-header {{
                text-align: center;
                margin-bottom: 20px;
            }}
            .page-header h1 {{
                font-size: 22px;
                color: #0b3d91;
                margin: 0 0 4px;
            }}
            .back-btn {{
                display: inline-block;
                margin-bottom: 16px;
                color: #0b3d91;
                text-decoration: none;
                font-weight: 600;
                font-size: 14px;
            }}
            .chart-card {{
                background: #fff;
                border-radius: 14px;
                box-shadow: 0 3px 12px rgba(0,0,0,0.07);
                padding: 18px;
                margin-bottom: 20px;
            }}
            .chart-card h2 {{
                font-size: 16px;
                color: #333;
                margin-top: 0;
            }}
            .note {{
                font-size: 12px;
                color: #999;
                text-align: center;
                margin-top: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="page">
            <a class="back-btn" href="index.html">→ رجوع للجداول</a>
            <div class="page-header">
                <h1>📈 الرسم البياني للأسعار</h1>
                <div>برلين براندنبورج (BER) ⇄ دمشق (DAM)</div>
            </div>

            <div class="chart-card">
                <h2>🛫 أسعار رحلات الذهاب (برلين ← دمشق)</h2>
                <canvas id="outboundChart" height="110"></canvas>
            </div>

            <div class="chart-card">
                <h2>🛬 أسعار رحلات العودة (دمشق ← برلين)</h2>
                <canvas id="inboundChart" height="110"></canvas>
            </div>

            <div class="note">الفجوات في الخط تعني إن الرحلة غير متوفرة في هذا التاريخ</div>
        </div>

        <script>
            fetch('data.json')
                .then(res => res.json())
                .then(data => {{
                    function makeChart(canvasId, series, label, color) {{
                        const labels = series.map(item => item.date_display);
                        const prices = series.map(item => item.price);

                        new Chart(document.getElementById(canvasId), {{
                            type: 'line',
                            data: {{
                                labels: labels,
                                datasets: [{{
                                    label: label,
                                    data: prices,
                                    borderColor: color,
                                    backgroundColor: color + '33',
                                    tension: 0.25,
                                    spanGaps: false,
                                    pointRadius: 3,
                                    fill: true,
                                }}]
                            }},
                            options: {{
                                responsive: true,
                                plugins: {{
                                    legend: {{ display: false }},
                                    tooltip: {{
                                        callbacks: {{
                                            label: function(ctx) {{
                                                const item = series[ctx.dataIndex];
                                                if (item.price === null) return 'غير متوفر';
                                                return item.price.toFixed(2) + ' € — رحلة ' + (item.flight_no || '-');
                                            }}
                                        }}
                                    }}
                                }},
                                scales: {{
                                    y: {{
                                        title: {{ display: true, text: 'السعر (€)' }},
                                        beginAtZero: false,
                                    }},
                                    x: {{
                                        ticks: {{ maxRotation: 60, minRotation: 45 }}
                                    }}
                                }}
                            }}
                        }});
                    }}

                    makeChart('outboundChart', data.outbound, 'ذهاب', '#0b3d91');
                    makeChart('inboundChart', data.inbound, 'عودة', '#28a745');
                }})
                .catch(err => {{
                    document.querySelector('.page').innerHTML +=
                        '<p style="color:red; text-align:center;">تعذر تحميل بيانات الرسم البياني.</p>';
                    console.error(err);
                }});
        </script>
    </body>
    </html>
    """
    with open("chart.html", "w", encoding="utf-8") as f:
        f.write(chart_html)


if __name__ == "__main__":
    scrape_sundair()
