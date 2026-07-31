"""
Weather & Route-Based Forecast
--------------------------------
เวอร์ชันปรับปรุง เพิ่มฟีเจอร์:
  1. เพิ่มจุดแวะระหว่างทางได้ (multi-stop route)
  2. เรดาร์ฝนแบบเรียลไทม์ (RainViewer) แสดงบนแผนที่
  3. ตรวจจับ Time zone ของอุปกรณ์ผู้ใช้อัตโนมัติ (ไม่ล็อกตายตัวเป็นเวลาเซิร์ฟเวอร์)
  4. ลดการรีเฟรช/คำนวณซ้ำซ้อน ด้วย st.cache_data + session_state + st_folium(returned_objects=[])
  5. ปุ่ม "ตำแหน่งของฉัน" อ้างอิงตำแหน่ง GPS จริงของอุปกรณ์ ใช้เป็นจุด A อัตโนมัติ
  6. ปั๊มน้ำมันตามเส้นทาง (Overpass API)
  7. เลี่ยงทางด่วน/เลี่ยงด่านเก็บเงิน (OpenRouteService)
  8. เครื่องคำนวณค่าน้ำมันของทริป
  9. โครงสร้างใหม่: ย้ายอินพุตทั้งหมดไปไว้ที่ sidebar พื้นที่หลักเหลือไว้แสดงผลลัพธ์อย่างเดียว
"""

import html
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import folium
import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation, streamlit_js_eval

st.set_page_config(page_title="Weather & Route-Based Forecast", page_icon="⛅", layout="wide")

# =========================================================================
# PWA: ฝัง manifest / meta tag / service worker เพื่อให้ "ติดตั้งเป็นแอป" บนมือถือได้
# =========================================================================
# หมายเหตุ: ต้องเปิด enableStaticServing=true ใน .streamlit/config.toml
# และวางไฟล์ manifest.json, sw.js, icon-192.png, icon-512.png ไว้ในโฟลเดอร์ static/ ข้าง app.py
# ใช้เทคนิคยิง JS เข้าไปแก้ <head> ของหน้าหลัก เพราะ Streamlit ไม่เปิดให้แก้ head โดยตรง
components.html(
    """
    <script>
    (function () {
        const d = window.parent.document;
        function addTag(tag, attrs) {
            const el = d.createElement(tag);
            Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
            d.head.appendChild(el);
        }
        if (!d.querySelector('link[rel="manifest"]')) {
            addTag('link', {rel: 'manifest', href: '/app/static/manifest.json'});
        }
        if (!d.querySelector('meta[name="theme-color"]')) {
            addTag('meta', {name: 'theme-color', content: '#0e1117'});
        }
        // รองรับ "Add to Home Screen" บน iOS Safari
        addTag('meta', {name: 'apple-mobile-web-app-capable', content: 'yes'});
        addTag('meta', {name: 'apple-mobile-web-app-title', content: 'Weather Route'});

        // Streamlit Cloud ใส่ apple-touch-icon/favicon ของตัวเองไว้ใน <head> อยู่ก่อนแล้ว
        // ต้องลบของเดิมออกก่อน ไม่งั้น Safari จะยังใช้ไอคอนของ Streamlit (โลโก้สีแดง) แทนของเรา
        d.querySelectorAll(
            'link[rel="apple-touch-icon"], link[rel="apple-touch-icon-precomposed"], link[rel~="icon"]'
        ).forEach((el) => el.remove());

        addTag('link', {rel: 'apple-touch-icon', href: '/app/static/icon-192.png'});
        addTag('link', {rel: 'apple-touch-icon', sizes: '192x192', href: '/app/static/icon-192.png'});
        addTag('link', {rel: 'apple-touch-icon', sizes: '512x512', href: '/app/static/icon-512.png'});
        addTag('link', {rel: 'icon', type: 'image/png', sizes: '192x192', href: '/app/static/icon-192.png'});

        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/app/static/sw.js').catch(function (err) {
                console.log('SW registration failed:', err);
            });
        }
    })();
    </script>
    """,
    height=0,
    width=0,
)

# =========================================================================
# STYLE: ธีมทันสมัย + responsive สำหรับ PC และมือถือ
# =========================================================================
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    /* บอกเบราว์เซอร์ตรง ๆ ว่าแอปนี้เป็นธีมมืดที่ออกแบบมาเองแล้ว
       กัน Android Chrome "Force Dark" (บังคับกลับสีเว็บที่ไม่ประกาศ color-scheme)
       ไปกลับสีตัวหนังสือ/พื้นหลังในการ์ดที่เราออกแบบเองจนอ่านไม่ออก (iOS ไม่มีปัญหานี้) */
    :root { color-scheme: dark; }

    html, body, [class*="css"] { font-family: 'Inter', -apple-system, sans-serif; }

    .stButton>button {
        border-radius: 10px;
        font-weight: 600;
        transition: transform .12s ease, box-shadow .12s ease;
        border: 1px solid rgba(255,255,255,.08);
    }
    .stButton>button:hover { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(0,0,0,.28); }

    div[data-testid="stTextInput"] input,
    div[data-baseweb="select"] > div {
        border-radius: 10px !important;
    }

    button[data-testid="stNumberInputStepUp"],
    button[data-testid="stNumberInputStepDown"] { display: none; }
    div[data-testid="stNumberInputContainer"] { border-radius: 10px; }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #12161f, #0b0e14);
        border-right: 1px solid rgba(255,255,255,.06);
    }
    section[data-testid="stSidebar"] .stButton>button { width: 100%; }

    div[role="radiogroup"] label {
        background: rgba(255,255,255,.035);
        border: 1px solid rgba(255,255,255,.09);
        border-radius: 10px;
        padding: 8px 14px;
        margin-bottom: 6px;
        transition: background .12s ease, border-color .12s ease;
    }
    div[role="radiogroup"] label:hover { background: rgba(255,255,255,.07); border-color: rgba(255,255,255,.2); }

    .weather-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
        gap: 14px;
        margin: 6px 0 22px 0;
    }
    .weather-card {
        border-radius: 16px;
        padding: 16px 18px;
        border: 1px solid rgba(255,255,255,.09);
        box-shadow: 0 4px 16px rgba(0,0,0,.22);
        min-width: 0;
    }
    .weather-card.origin { background: linear-gradient(150deg,#12351f,#0e2718); border-left: 4px solid #2ecc71; }
    .weather-card.stop   { background: linear-gradient(150deg,#3a2f12,#2a220e); border-left: 4px solid #f5a623; }
    .weather-card.auto   { background: linear-gradient(150deg,#2a2a3a,#1e1e2a); border-left: 4px solid #7c93f0; }
    .weather-card.dest   { background: linear-gradient(150deg,#2a1414,#1f0f0f); border-left: 4px solid #e74c3c; }

    .weather-card h4 { margin: 0 0 8px 0; font-size: 15px; font-weight: 700; color: #f2f4f8; }
    .weather-card .wc-loc  { font-size: 13px; opacity: .9; margin-bottom: 2px; color: #f2f4f8; }
    .weather-card .wc-eta  { font-size: 12px; opacity: .65; margin-bottom: 10px; color: #f2f4f8; }
    .weather-card .wc-row {
        display: flex; justify-content: space-between; align-items: center;
        font-size: 13px; padding: 5px 0; border-top: 1px dashed rgba(255,255,255,.1);
        color: #f2f4f8;
    }
    .rain-badge {
        display: inline-block; padding: 2px 9px; border-radius: 20px;
        font-size: 11px; font-weight: 700;
    }
    .rain-low  { background: #1e5631; color: #8ef0ae; }
    .rain-mid  { background: #5c4a12; color: #ffd873; }
    .rain-high { background: #5c1a1a; color: #ff9d9d; }

    .route-banner, .rain-alert, .fuel-banner {
        border-radius: 14px;
        padding: 14px 20px;
        margin-bottom: 16px;
        font-size: 14px;
        line-height: 1.6;
        color: #f2f4f8;
    }
    .route-banner { background: linear-gradient(120deg,#12283a,#0d1c2e); border: 1px solid #1f4a6e; }
    .fuel-banner   { background: linear-gradient(120deg,#3a2f12,#2a220e); border: 1px solid #7a5a2e; }
    .rain-alert   { background: linear-gradient(120deg,#2a1414,#1f0f0f); border: 1px solid #7a2e2e; }
    .rain-alert ul { margin: 8px 0 0 0; padding-left: 20px; }
    .rain-alert li { margin: 4px 0; }

    @media (max-width: 640px) {
        .weather-grid { grid-template-columns: 1fr 1fr; gap: 10px; }
        .weather-card { padding: 12px 14px; }
        .weather-card h4 { font-size: 13.5px; }
        .route-banner, .rain-alert, .fuel-banner { padding: 12px 14px; font-size: 13px; }
    }
    @media (max-width: 400px) {
        .weather-grid { grid-template-columns: 1fr; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================================
# 0. TIMEZONE ตามอุปกรณ์ผู้ใช้
# =========================================================================
if "device_tz" not in st.session_state:
    st.session_state["device_tz"] = "Asia/Bangkok"
if "tz_detected_once" not in st.session_state:
    st.session_state["tz_detected_once"] = False

if not st.session_state["tz_detected_once"]:
    _tz = streamlit_js_eval(
        js_expressions="Intl.DateTimeFormat().resolvedOptions().timeZone",
        key="detect_device_tz",
    )
    if _tz:
        st.session_state["device_tz"] = _tz
        st.session_state["tz_detected_once"] = True

try:
    DEVICE_TZ = ZoneInfo(st.session_state["device_tz"])
except Exception:
    DEVICE_TZ = ZoneInfo("Asia/Bangkok")


def now_local() -> datetime:
    return datetime.now(DEVICE_TZ)


# =========================================================================
# 1. HELPER / CACHED FUNCTIONS
# =========================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_coordinates(place_name: str):
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={place_name}"
    headers = {"User-Agent": "WeatherApp/1.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        if res:
            return float(res[0]["lat"]), float(res[0]["lon"]), res[0]["display_name"]
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการดึงพิกัด: {e}")
    return None, None, None


@st.cache_data(ttl=3600, show_spinner=False)
def get_location_name(lat: float, lon: float) -> str:
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=10"
    headers = {"User-Agent": "WeatherApp/1.0"}
    try:
        res = requests.get(url, headers=headers, timeout=8).json()
        address = res.get("address", {})
        return (
            address.get("state")
            or address.get("province")
            or address.get("city")
            or address.get("county")
            or "จุดระหว่างทาง"
        )
    except Exception:
        return "จุดระหว่างทาง"


@st.cache_data(ttl=1800, show_spinner=False)
def _get_weather_raw(lat: float, lon: float):
    """ดึงข้อมูลดิบจาก Open-Meteo (cache 30 นาที ต่อพิกัด) พร้อม retry อัตโนมัติเมื่อโดน 429
    (Open-Meteo ฟรีมี rate limit ร่วมกันทุกผู้ใช้ ถ้ายิงรัวเกินไปในเวลาไล่เลี่ยกันจะโดนจำกัดชั่วคราว)"""
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,weather_code"
        f"&hourly=temperature_2m,precipitation_probability,weather_code"
        f"&timezone=auto"
    )
    last_status = None
    for attempt in range(3):
        res = requests.get(url, timeout=10)
        if res.status_code == 429:
            last_status = 429
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))  # รอแล้วลองใหม่ (1.5s, 3s)
                continue
        res.raise_for_status()
        return res.json()
    res.raise_for_status()  # หมดโควตา retry แล้วยังโดน 429 อยู่ -> โยน error ออกไปตามจริง


def _nearest_hour_index(hourly_times, target_naive_dt):
    target_str = target_naive_dt.strftime("%Y-%m-%dT%H:00")
    if target_str in hourly_times:
        return hourly_times.index(target_str)
    try:
        parsed = [datetime.fromisoformat(t) for t in hourly_times]
        diffs = [abs((p - target_naive_dt).total_seconds()) for p in parsed]
        return diffs.index(min(diffs))
    except Exception:
        return 0


def get_weather(lat: float, lon: float, target_time: datetime | None = None):
    try:
        raw = _get_weather_raw(round(lat, 3), round(lon, 3))
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 429:
            st.caption("⏳ ระบบพยากรณ์อากาศมีคนใช้งานพร้อมกันเยอะในขณะนี้ กรุณาลองค้นหาใหม่อีกครั้งในอีกสักครู่")
        else:
            st.caption(f"⚠️ เกิดข้อผิดพลาดในการดึงสภาพอากาศ (รหัส {status or '?'})")
        return None
    except Exception:
        st.caption("⚠️ เกิดข้อผิดพลาดในการดึงสภาพอากาศ กรุณาลองใหม่อีกครั้ง")
        return None

    if target_time is not None and "hourly" in raw:
        offset_sec = raw.get("utc_offset_seconds", 0)
        target_utc = target_time.astimezone(timezone.utc)
        local_target_naive = (target_utc + timedelta(seconds=offset_sec)).replace(tzinfo=None)

        hourly_times = raw["hourly"]["time"]
        idx = _nearest_hour_index(hourly_times, local_target_naive)
        try:
            return {
                "temp": raw["hourly"]["temperature_2m"][idx],
                "prob": raw["hourly"]["precipitation_probability"][idx],
                "code": raw["hourly"]["weather_code"][idx],
            }
        except IndexError:
            return None
    else:
        curr = raw.get("current", {})
        prob = raw.get("hourly", {}).get("precipitation_probability", [0])[0]
        return {"temp": curr.get("temperature_2m"), "prob": prob, "code": curr.get("weather_code")}


def interpret_weather_code(code):
    if code in [0]:
        return "ท้องฟ้าแจ่มใส ☀️"
    elif code in [1, 2, 3]:
        return "มีเมฆบางส่วน ⛅"
    elif code in [45, 48]:
        return "มีหมอก 🌫️"
    elif code in [51, 53, 55]:
        return "ละอองฝนเบาๆ 🌧️"
    elif code in [61, 63, 65]:
        return "ฝนตก 🌧️"
    elif code in [80, 81, 82]:
        return "ฝนตกหนัก/ฝนซู่ ⛈️"
    elif code in [95, 96, 99]:
        return "พายุฝนฟ้าคะนอง 🌩️"
    return "สภาพอากาศทั่วไป 🌤️"


def _rain_badge_class(prob: int) -> str:
    if prob >= 60:
        return "rain-high"
    if prob >= 30:
        return "rain-mid"
    return "rain-low"


def collapse_sidebar_on_mobile():
    """หุบ sidebar อัตโนมัติหลังกดค้นหาสำเร็จ - เฉพาะจอมือถือ/แท็บเล็ต (ไม่ยุ่งกับจอ PC)
    Streamlit ไม่หุบ sidebar ให้เองเวลากดปุ่มข้างในมัน จึงต้องยิง JS ไปคลิกปุ่มหุบให้แทน
    ลองหลาย selector เพราะ Streamlit แต่ละเวอร์ชันตั้งชื่อ testid ไม่เหมือนกัน"""
    components.html(
        """
        <script>
        (function () {
            const d = window.parent.document;
            const w = window.parent.innerWidth;
            if (w > 768) return;  // จอกว้างพอ (PC/แท็บเล็ตแนวนอน) ไม่ต้องหุบ

            function tryCollapse() {
                let btn = d.querySelector('[data-testid="stSidebarCollapseButton"] button')
                    || d.querySelector('[data-testid="stSidebarCollapseButton"]');
                if (!btn) {
                    const buttons = d.querySelectorAll('button');
                    for (const b of buttons) {
                        const label = (b.getAttribute('aria-label') || '').toLowerCase();
                        if (label.includes('close sidebar') || label.includes('collapse sidebar')) {
                            btn = b;
                            break;
                        }
                    }
                }
                if (btn) btn.click();
            }
            setTimeout(tryCollapse, 250);
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def render_weather_card(kind: str, icon: str, title: str, location: str, eta_label: str, weather: dict) -> str:
    badge_cls = _rain_badge_class(weather["prob"])
    return (
        f'<div class="weather-card {kind}">'
        f'<h4>{icon} {html.escape(str(title))}</h4>'
        f'<div class="wc-loc">📍 {html.escape(str(location))}</div>'
        f'<div class="wc-eta">⏰ {html.escape(str(eta_label))}</div>'
        f'<div class="wc-row"><span>สภาพอากาศ</span><span>{interpret_weather_code(weather["code"])}</span></div>'
        f'<div class="wc-row"><span>อุณหภูมิ</span><span>{weather["temp"]}°C</span></div>'
        f'<div class="wc-row"><span>โอกาสฝนตก</span>'
        f'<span class="rain-badge {badge_cls}">{weather["prob"]}%</span></div>'
        f"</div>"
    )


def downsample_path(path: list, max_points: int = 100) -> list:
    n = len(path)
    if n <= max_points:
        return path
    step = max(n // max_points, 1)
    return path[::step]


def _haversine_km(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, sqrt, atan2

    r = 6371.0
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def _chunk_list(lst, n):
    return [lst[i : i + n] for i in range(0, len(lst), n)]


@st.cache_data(ttl=1800, show_spinner=False)
def get_fuel_stations_along_route(sample_coords: tuple, radius_m: int = 3000):
    pad_deg = radius_m / 111_000
    chunks = _chunk_list(list(sample_coords), 12)

    bbox_clauses = []
    for chunk in chunks:
        lats = [p[0] for p in chunk]
        lons = [p[1] for p in chunk]
        south, north = min(lats) - pad_deg, max(lats) + pad_deg
        west, east = min(lons) - pad_deg, max(lons) + pad_deg
        bbox_clauses.append(f'node["amenity"="fuel"]({south},{west},{north},{east});')

    query = f"[out:json][timeout:20];({''.join(bbox_clauses)});out body;"

    headers = {
        "User-Agent": "WeatherRouteApp/1.0 (streamlit personal project)",
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    mirrors = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
    ]

    data, last_error = None, None
    for url in mirrors:
        try:
            res = requests.post(url, data={"data": query}, headers=headers, timeout=20)
            res.raise_for_status()
            data = res.json()
            break
        except Exception as e:
            last_error = e
            continue

    if data is None:
        st.caption(f"⚠️ ไม่สามารถดึงข้อมูลปั๊มน้ำมันได้ในขณะนี้ ({last_error})")
        return []

    stations = []
    seen_ids = set()
    for el in data.get("elements", []):
        lat, lon = el.get("lat"), el.get("lon")
        if lat is None or lon is None or el.get("id") in seen_ids:
            continue
        min_dist_km = min(_haversine_km(lat, lon, p[0], p[1]) for p in sample_coords)
        if min_dist_km * 1000 <= radius_m:
            seen_ids.add(el.get("id"))
            tags = el.get("tags", {})
            name = tags.get("brand") or tags.get("name") or "ปั๊มน้ำมัน"
            stations.append({"lat": lat, "lon": lon, "name": name})
    return stations


@st.cache_data(ttl=300, show_spinner=False)
def get_rain_radar_tile_url():
    try:
        res = requests.get("https://api.rainviewer.com/public/weather-maps.json", timeout=10).json()
        host = res.get("host", "https://tilecache.rainviewer.com")
        frames = res.get("radar", {}).get("past", [])
        if not frames:
            return None
        latest_path = frames[-1]["path"]
        return f"{host}{latest_path}/256/{{z}}/{{x}}/{{y}}/2/1_1.png"
    except Exception:
        return None


def sample_route_points(path, total_dist_km, avg_speed_kmh):
    num_coords = len(path)
    if num_coords <= 2:
        return []

    if total_dist_km >= 100:
        step_count = min(int(total_dist_km // 150), 5)
        step_count = max(step_count, 1)
    else:
        step_count = 1

    sampled_points = []
    step_size = num_coords // (step_count + 1)

    for i in range(1, step_count + 1):
        idx = i * step_size
        if idx < num_coords:
            pt = path[idx]
            dist_at_pt = round((total_dist_km / (step_count + 1)) * i, 1)
            travel_hours = dist_at_pt / avg_speed_kmh
            eta_time = now_local() + timedelta(hours=travel_hours)
            loc_name = get_location_name(pt[0], pt[1])
            sampled_points.append(
                {
                    "lat": pt[0],
                    "lon": pt[1],
                    "km_marker": dist_at_pt,
                    "location_name": loc_name,
                    "eta_time": eta_time,
                    "eta_str": eta_time.strftime("%H:%M น."),
                }
            )
    return sampled_points


@st.cache_data(ttl=600, show_spinner=False)
def get_route_osrm(coords: tuple, mode: str = "driving"):
    coord_str = ";".join([f"{lon},{lat}" for lat, lon in coords])
    allow_alt = "true" if len(coords) == 2 else "false"
    url = (
        f"http://router.project-osrm.org/route/v1/driving/{coord_str}"
        f"?overview=full&geometries=geojson&alternatives={allow_alt}"
    )

    try:
        res = requests.get(url, timeout=15).json()
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการเชื่อมต่อ OSRM: {e}")
        return []

    if "routes" not in res or not res["routes"]:
        return []

    if mode == "bike":
        dist_factor, avg_speed_kmh = 0.95, 80
    elif mode == "foot":
        dist_factor, avg_speed_kmh = 0.85, 3.0
    else:
        dist_factor, avg_speed_kmh = 1.0, 100

    routes_data = []
    for idx, r in enumerate(res["routes"][:2]):
        coordinates = r["geometry"]["coordinates"]
        path = [[c[1], c[0]] for c in coordinates]

        raw_dist_km = r["distance"] / 1000
        dist_km = round(raw_dist_km * dist_factor, 2)
        duration_hours = dist_km / avg_speed_kmh
        total_minutes = int(duration_hours * 60)

        if total_minutes >= 60:
            time_str = f"{total_minutes // 60} ชม. {total_minutes % 60} นาที"
        else:
            time_str = f"{total_minutes} นาที"

        leg_cum_km, cum = [], 0.0
        for leg in r.get("legs", []):
            cum += (leg["distance"] / 1000) * dist_factor
            leg_cum_km.append(round(cum, 2))

        label_prefix = "เส้นทางหลัก" if idx == 0 else f"ทางเลือกที่ {idx}"
        routes_data.append(
            {
                "id": idx,
                "label": f"{label_prefix} - {dist_km} กม. ({time_str})",
                "path": path,
                "dist_km": dist_km,
                "time_str": time_str,
                "avg_speed_kmh": avg_speed_kmh,
                "leg_cum_km": leg_cum_km,
            }
        )
    return routes_data


@st.cache_data(ttl=600, show_spinner=False)
def get_route_ors(coords: tuple, api_key: str, profile: str = "driving-car", avoid_features: tuple = ()):
    coordinates = [[lon, lat] for lat, lon in coords]
    body = {"coordinates": coordinates, "instructions": False}
    if avoid_features:
        body["options"] = {"avoid_features": list(avoid_features)}

    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    url = f"https://api.openrouteservice.org/v2/directions/{profile}/geojson"

    try:
        res = requests.post(url, json=body, headers=headers, timeout=20)
        if res.status_code in (401, 403):
            st.error("❌ ORS API Key ไม่ถูกต้อง หรือยังไม่ได้เปิดใช้งาน กรุณาตรวจสอบใน Dashboard ของ OpenRouteService")
            return []
        if res.status_code == 404:
            st.error("❌ ไม่พบเส้นทางที่ตรงเงื่อนไข (อาจเป็นเพราะเลี่ยงทางด่วน/ด่านเก็บเงินแล้วไม่มีถนนอื่นเชื่อมได้)")
            return []
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการเชื่อมต่อ OpenRouteService: {e}")
        return []

    features = data.get("features", [])
    if not features:
        return []

    feat = features[0]
    coords_out = feat["geometry"]["coordinates"]
    path = [[c[1], c[0]] for c in coords_out]

    summary = feat["properties"]["summary"]
    dist_km = round(summary["distance"] / 1000, 2)
    duration_sec = summary["duration"]
    total_minutes = int(duration_sec / 60)
    if total_minutes >= 60:
        time_str = f"{total_minutes // 60} ชม. {total_minutes % 60} นาที"
    else:
        time_str = f"{total_minutes} นาที"

    leg_cum_km, cum = [], 0.0
    for seg in feat["properties"].get("segments", []):
        cum += seg["distance"] / 1000
        leg_cum_km.append(round(cum, 2))

    avg_speed_kmh = (dist_km / (duration_sec / 3600)) if duration_sec > 0 else 60

    avoid_th = {"highways": "เลี่ยงทางด่วน", "tollways": "เลี่ยงด่านเก็บเงิน"}
    avoid_label = (
        " (" + ", ".join(avoid_th.get(a, a) for a in avoid_features) + ")" if avoid_features else ""
    )

    return [
        {
            "id": 0,
            "label": f"เส้นทาง ORS{avoid_label} - {dist_km} กม. ({time_str})",
            "path": path,
            "dist_km": dist_km,
            "time_str": time_str,
            "avg_speed_kmh": avg_speed_kmh,
            "leg_cum_km": leg_cum_km,
        }
    ]


# =========================================================================
# 2. SIDEBAR - อินพุตทั้งหมดมารวมที่นี่ พื้นที่หลักเหลือไว้แสดงผลลัพธ์อย่างเดียว
# =========================================================================
with st.sidebar:
    st.markdown("### ⛅ Weather & Route")
    st.caption("พยากรณ์อากาศแบบเรียลไทม์ ทั้งจุดเดียวและตามเส้นทางเดินทาง")

    page = st.radio(
        "โหมดการใช้งาน",
        ["📍 สภาพอากาศจุดเดียว", "🚗 เส้นทาง A → B"],
        label_visibility="collapsed",
        key="page_select",
    )
    st.divider()

    if page == "📍 สภาพอากาศจุดเดียว":
        place_input = st.text_input(
            "พิมพ์ชื่อเขต/อำเภอ หรือจังหวัด", value="", placeholder="เช่น กรุงเทพมหานคร", key="place_input"
        )
        submit_single = st.button("🔍 เช็กสภาพอากาศ", type="primary", use_container_width=True)
        show_radar_t1 = st.checkbox("🌧️ แสดงเรดาร์ฝนบนแผนที่", value=True, key="radar_tab1")

    else:
        st.session_state.setdefault("stop_ids", [])
        st.session_state.setdefault("stop_counter", 0)
        st.session_state.setdefault("awaiting_geo", False)
        st.session_state.setdefault("origin_coords_override", None)
        st.session_state.setdefault("origin_override_label", None)

        geo_status_msg = None
        if st.session_state["awaiting_geo"]:
            geo = get_geolocation()
            if geo and geo.get("coords"):
                lat_g = geo["coords"]["latitude"]
                lon_g = geo["coords"]["longitude"]
                label = get_location_name(lat_g, lon_g)
                st.session_state["origin_input"] = label
                st.session_state["origin_coords_override"] = (lat_g, lon_g)
                st.session_state["origin_override_label"] = label
                st.session_state["awaiting_geo"] = False
                geo_status_msg = ("success", f"📍 ตั้งจุด A เป็นตำแหน่งปัจจุบัน: {label}")
            else:
                geo_status_msg = ("info", "🔄 กำลังขอสิทธิ์เข้าถึงตำแหน่ง กรุณากด **อนุญาต** ที่เบราว์เซอร์")

        origin_input = st.text_input(
            "🟢 จุดเริ่มต้น (A)", key="origin_input", placeholder="เช่น ธนาคารแห่งประเทศไทย"
        )
        locate_clicked = st.button("📍 ใช้ตำแหน่งของฉัน", key="locate_btn", use_container_width=True)
        dest_input = st.text_input("🔴 ปลายทาง (B)", key="dest_input", placeholder="เช่น เชียงราย")

        mode_options = {"🚗 รถยนต์": "driving", "🏍️ มอเตอร์ไซค์/จักรยาน": "bike", "🚶 เดิน": "foot"}
        selected_mode_label = st.selectbox("รูปแบบการเดินทาง", options=list(mode_options.keys()), index=0)
        travel_mode = mode_options[selected_mode_label]

        if geo_status_msg:
            kind, msg = geo_status_msg
            (st.success if kind == "success" else st.info)(msg)

        if locate_clicked:
            st.session_state["awaiting_geo"] = True
            st.rerun()

        default_ors_key = ""
        try:
            default_ors_key = st.secrets.get("ORS_API_KEY", "")
        except Exception:
            default_ors_key = ""

        with st.expander("⚙️ เลี่ยงทางด่วน / เลี่ยงด่านเก็บเงิน"):
            if default_ors_key:
                st.caption("✅ ระบบตั้งค่า OpenRouteService ไว้ให้แล้ว เลือกติ๊กด้านล่างได้เลย")
                ors_api_key = default_ors_key
            else:
                st.caption(
                    "ต้องใช้ [OpenRouteService](https://openrouteservice.org/dev/#/signup) "
                    "(ฟรี 2,000 requests/วัน) ใส่ API key ด้านล่าง"
                )
                ors_api_key = st.text_input(
                    "ORS API Key", value="", type="password", key="ors_api_key_input",
                    placeholder="วาง API key ตรงนี้",
                )
            avoid_highway = st.checkbox("🛣️ เลี่ยงทางด่วน/มอเตอร์เวย์", key="avoid_highway_chk")
            avoid_toll = st.checkbox("💰 เลี่ยงด่านเก็บเงิน", key="avoid_toll_chk")
            use_ors = bool(ors_api_key.strip()) and (avoid_highway or avoid_toll)
            if (avoid_highway or avoid_toll) and not ors_api_key.strip():
                st.warning("⚠️ ยังไม่มี ORS API Key จะใช้เส้นทางปกติแทน")
            st.caption('หมายเหตุ: "เลี่ยงเมือง" ยังไม่มีในบริการฟรีของ ORS')

        st.markdown("**🟠 จุดแวะระหว่างทาง (ถ้ามี)**")
        for sid in list(st.session_state["stop_ids"]):
            scol1, scol2 = st.columns([4, 1])
            with scol1:
                st.text_input(
                    "จุดแวะ", key=f"stop_{sid}", placeholder="เช่น นครสวรรค์", label_visibility="collapsed",
                )
            with scol2:
                if st.button("🗑️", key=f"remove_{sid}"):
                    st.session_state["stop_ids"].remove(sid)
                    st.session_state.pop(f"stop_{sid}", None)
                    st.rerun()

        if st.button("➕ เพิ่มจุดแวะ", use_container_width=True):
            st.session_state["stop_counter"] += 1
            st.session_state["stop_ids"].append(st.session_state["stop_counter"])
            st.rerun()

        st.divider()
        submit_route = st.button("🔍 ค้นหาเส้นทาง & สภาพอากาศ", type="primary", use_container_width=True)

    st.divider()
    st.caption(
        f"🕒 เขตเวลา: **{st.session_state['device_tz']}**  \n"
        f"เวลาขณะนี้ {now_local().strftime('%d/%m/%Y %H:%M')} น."
    )


# =========================================================================
# 3. MAIN AREA - แสดงผลลัพธ์ตามโหมดที่เลือกใน sidebar
# =========================================================================
st.title("⛅ Weather & Route-Based Forecast")

if page == "📍 สภาพอากาศจุดเดียว":
    if submit_single:
        if place_input.strip():
            lat, lon, name = get_coordinates(place_input)
            if lat and lon:
                w = get_weather(lat, lon)
                if w:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("🌡️ อุณหภูมิปัจจุบัน", f"{w['temp']} °C")
                    c2.metric("📊 สภาพอากาศ", interpret_weather_code(w["code"]))
                    c3.metric("🌧️ โอกาสฝนตก", f"{w['prob']} %")
                    st.session_state["tab1_point"] = {"lat": lat, "lon": lon, "name": name}
                    collapse_sidebar_on_mobile()
            else:
                st.session_state.pop("tab1_point", None)
                st.error("ไม่พบข้อมูลสถานที่ดังกล่าว")
        else:
            st.warning("กรุณากรอกชื่อสถานที่ที่ต้องการค้นหา (แถบด้านซ้าย)")

    if "tab1_point" in st.session_state:
        p = st.session_state["tab1_point"]
        m1 = folium.Map(location=[p["lat"], p["lon"]], zoom_start=9)
        folium.Marker([p["lat"], p["lon"]], popup=p["name"], icon=folium.Icon(color="blue")).add_to(m1)
        if show_radar_t1:
            tile_url = get_rain_radar_tile_url()
            if tile_url:
                folium.raster_layers.TileLayer(
                    tiles=tile_url, attr="RainViewer.com", name="เรดาร์ฝน", overlay=True, opacity=0.55
                ).add_to(m1)
            else:
                st.caption("⚠️ ไม่สามารถโหลดข้อมูลเรดาร์ฝนได้ในขณะนี้")
        folium.LayerControl(collapsed=True).add_to(m1)
        st_folium(m1, width=1100, height=450, key="tab1_map", returned_objects=[])
    else:
        st.info('👈 พิมพ์ชื่อสถานที่ในแถบด้านซ้าย แล้วกด "เช็กสภาพอากาศ" เพื่อเริ่มต้น')

else:
    if submit_route:
        if not origin_input.strip() or not dest_input.strip():
            st.session_state.pop("search_data", None)
            st.warning("⚠️ กรุณากรอกทั้งจุดเริ่มต้น (A) และจุดหมายปลายทาง (B) ในแถบด้านซ้ายให้ครบถ้วนครับ")
        else:
            with st.spinner(f"กำลังคำนวณเส้นทาง [{selected_mode_label}] และดึงข้อมูลสภาพอากาศ..."):
                if (
                    st.session_state["origin_coords_override"]
                    and origin_input.strip() == st.session_state["origin_override_label"]
                ):
                    lat_a, lon_a = st.session_state["origin_coords_override"]
                    name_a = origin_input
                else:
                    lat_a, lon_a, name_a = get_coordinates(origin_input)

                lat_b, lon_b, name_b = get_coordinates(dest_input)

                stop_texts = [
                    st.session_state.get(f"stop_{sid}", "").strip() for sid in st.session_state["stop_ids"]
                ]
                stop_texts = [s for s in stop_texts if s]

                stop_coords, stop_failed = [], []
                for s_text in stop_texts:
                    s_lat, s_lon, s_name = get_coordinates(s_text)
                    if s_lat and s_lon:
                        stop_coords.append({"lat": s_lat, "lon": s_lon, "input": s_text, "name": s_name})
                    else:
                        stop_failed.append(s_text)

                if stop_failed:
                    st.error(f"❌ ไม่พบพิกัดของจุดแวะ: {', '.join(stop_failed)} กรุณาตรวจสอบชื่ออีกครั้ง")
                    st.session_state.pop("search_data", None)
                elif lat_a and lat_b:
                    full_coords = (
                        [(lat_a, lon_a)] + [(sc["lat"], sc["lon"]) for sc in stop_coords] + [(lat_b, lon_b)]
                    )

                    if use_ors:
                        ors_profile_map = {
                            "driving": "driving-car",
                            "bike": "cycling-regular",
                            "foot": "foot-walking",
                        }
                        avoid_list = tuple(
                            f for f, on in [("highways", avoid_highway), ("tollways", avoid_toll)] if on
                        )
                        routes = get_route_ors(
                            tuple(full_coords),
                            api_key=ors_api_key.strip(),
                            profile=ors_profile_map[travel_mode],
                            avoid_features=avoid_list,
                        )
                        if not routes:
                            st.warning(
                                "⚠️ ใช้ OpenRouteService ไม่สำเร็จ กำลังลองใช้เส้นทางปกติ (OSRM) แทน "
                                "(จะไม่เลี่ยงทางด่วน/ด่านเก็บเงินในครั้งนี้)"
                            )
                            routes = get_route_osrm(tuple(full_coords), mode=travel_mode)
                    else:
                        routes = get_route_osrm(tuple(full_coords), mode=travel_mode)

                    if routes:
                        st.session_state["search_data"] = {
                            "origin": origin_input,
                            "dest": dest_input,
                            "profile_label": selected_mode_label,
                            "lat_a": lat_a,
                            "lon_a": lon_a,
                            "lat_b": lat_b,
                            "lon_b": lon_b,
                            "routes": routes,
                            "stop_coords": stop_coords,
                            "w_a": get_weather(lat_a, lon_a),
                        }
                        collapse_sidebar_on_mobile()
                    else:
                        st.session_state.pop("search_data", None)
                        st.error("ไม่สามารถคำนวณเส้นทางระหว่างจุดที่กำหนดได้")
                else:
                    st.session_state.pop("search_data", None)
                    st.error("ไม่พบพิกัดของสถานที่ที่ระบุ กรุณาตรวจสอบชื่ออีกครั้ง")

    if "search_data" in st.session_state and origin_input.strip() and dest_input.strip():
        s_data = st.session_state["search_data"]

        route_labels = [r["label"] for r in s_data["routes"]]
        selected_label = st.radio("เลือกเส้นทาง:", route_labels, index=0, key="route_radio")
        selected_route = next(r for r in s_data["routes"] if r["label"] == selected_label)
        stop_coords = s_data["stop_coords"]

        user_waypoints = []
        for i, sc in enumerate(stop_coords):
            cum_km = selected_route["leg_cum_km"][i] if i < len(selected_route["leg_cum_km"]) else 0
            travel_hours = cum_km / selected_route["avg_speed_kmh"]
            eta_time = now_local() + timedelta(hours=travel_hours)
            user_waypoints.append(
                {
                    "lat": sc["lat"],
                    "lon": sc["lon"],
                    "km_marker": round(cum_km, 1),
                    "location_name": sc["input"],
                    "eta_time": eta_time,
                    "eta_str": eta_time.strftime("%H:%M น."),
                    "source": "stop",
                    "icon": "📌",
                }
            )

        auto_waypoints_raw = sample_route_points(
            selected_route["path"], selected_route["dist_km"], selected_route["avg_speed_kmh"]
        )
        for wp in auto_waypoints_raw:
            wp["source"] = "auto"
            wp["icon"] = "🕐"

        waypoints = list(user_waypoints)
        for ap in auto_waypoints_raw:
            if all(abs(ap["km_marker"] - uw["km_marker"]) > 20 for uw in user_waypoints):
                waypoints.append(ap)
        waypoints.sort(key=lambda w: w["km_marker"])

        total_hours = selected_route["dist_km"] / selected_route["avg_speed_kmh"]
        dest_eta = now_local() + timedelta(hours=total_hours)
        w_b = get_weather(s_data["lat_b"], s_data["lon_b"], target_time=dest_eta)

        st.markdown(
            f'<div class="route-banner">'
            f"📍 โหมด: <b>{html.escape(s_data['profile_label'])}</b> &nbsp;|&nbsp; "
            f"ระยะทาง: <b>{selected_route['dist_km']} กม.</b> &nbsp;|&nbsp; "
            f"เวลาเดินทางโดยประมาณ: <b>{selected_route['time_str']}</b>"
            f"</div>",
            unsafe_allow_html=True,
        )

        if travel_mode != "foot":
            with st.expander("⛽ ประมาณการค่าน้ำมันของทริปนี้", expanded=True):
                default_efficiency = 12.0 if travel_mode == "driving" else 30.0
                col_f1, col_f2, col_f3 = st.columns(3)
                with col_f1:
                    fuel_price = st.number_input(
                        "ราคาน้ำมัน (บาท/ลิตร)", min_value=0.0, value=33.0, step=0.5, key="fuel_price_input"
                    )
                with col_f2:
                    fuel_efficiency = st.number_input(
                        "อัตราสิ้นเปลือง (กม./ลิตร)",
                        min_value=0.1, value=default_efficiency, step=0.5, key="fuel_eff_input",
                    )
                with col_f3:
                    st.markdown("&nbsp;")
                    round_trip = st.checkbox("🔁 คำนวณแบบไป-กลับ", key="fuel_roundtrip_chk")

                calc_dist = selected_route["dist_km"] * (2 if round_trip else 1)
                liters = calc_dist / fuel_efficiency if fuel_efficiency > 0 else 0
                cost = liters * fuel_price
                trip_word = "ไป-กลับ" if round_trip else "เที่ยวเดียว"

                st.markdown(
                    f'<div class="fuel-banner">'
                    f"⛽ ระยะทาง{trip_word}: <b>{calc_dist:,.1f} กม.</b> &nbsp;|&nbsp; "
                    f"ใช้น้ำมันประมาณ <b>{liters:,.1f} ลิตร</b> &nbsp;|&nbsp; "
                    f"ค่าน้ำมันโดยประมาณ <b>{cost:,.0f} บาท</b>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                st.caption(
                    "หมายเหตุ: เป็นการประมาณการเบื้องต้นเท่านั้น ไม่รวมค่าทางด่วน/ค่าใช้จ่ายอื่น "
                    "และอัตราสิ้นเปลืองจริงอาจต่างกันตามสภาพจราจร รุ่นรถ และพฤติกรรมการขับขี่"
                )

        # หน่วงเวลาเล็กน้อยระหว่างจุด กัน Open-Meteo จำกัดการยิงรัวเกินไปในเวลาไล่เลี่ยกัน (429)
        waypoint_weather = []
        for i, wp in enumerate(waypoints):
            if i > 0:
                time.sleep(0.2)
            waypoint_weather.append((wp, get_weather(wp["lat"], wp["lon"], target_time=wp["eta_time"])))

        rain_warnings = []
        for wp, w_check in waypoint_weather:
            if w_check and (w_check["prob"] >= 50 or w_check["code"] in [61, 63, 65, 80, 81, 82, 95, 96, 99]):
                rain_warnings.append(
                    f"กม.ที่ {wp['km_marker']} ({wp['location_name']}) เวลาประมาณ {wp['eta_str']} "
                    f"[โอกาสฝนตก {w_check['prob']}% - {interpret_weather_code(w_check['code'])}]"
                )
        if w_b and (w_b["prob"] >= 50 or w_b["code"] in [61, 63, 65, 80, 81, 82, 95, 96, 99]):
            rain_warnings.append(
                f"ปลายทาง ({s_data['dest']}) เวลาประมาณ {dest_eta.strftime('%H:%M น.')} "
                f"[โอกาสฝนตก {w_b['prob']}% - {interpret_weather_code(w_b['code'])}]"
            )

        if rain_warnings:
            warning_items = "".join([f"<li>{html.escape(w)}</li>" for w in rain_warnings])
            st.markdown(
                f'<div class="rain-alert">'
                f"⚠️ <b>แจ้งเตือนสภาพอากาศบนเส้นทาง</b><br>"
                f"พบพื้นที่เสี่ยงฝนตกหนักระหว่างเดินทางตามเวลาที่คาดว่าจะไปถึง:"
                f"<ul>{warning_items}</ul>"
                f"</div>",
                unsafe_allow_html=True,
            )

        cards_html = []
        if s_data["w_a"]:
            cards_html.append(
                render_weather_card(
                    "origin", "🟢", "ต้นทาง", s_data["origin"],
                    f"ออกเดินทางตอนนี้ ({now_local().strftime('%H:%M')} น.)", s_data["w_a"],
                )
            )
        for wp, w_wp in waypoint_weather:
            if w_wp:
                card_kind = "stop" if wp.get("source") == "stop" else "auto"
                title = wp["location_name"] if wp.get("source") == "stop" else f"กม.ที่ {wp['km_marker']}"
                cards_html.append(
                    render_weather_card(
                        card_kind, wp.get("icon", "📌"), title,
                        f"กม.ที่ {wp['km_marker']} • {wp['location_name']}",
                        f"ถึงประมาณ {wp['eta_str']}", w_wp,
                    )
                )
        if w_b:
            cards_html.append(
                render_weather_card(
                    "dest", "🏁", "ปลายทาง", s_data["dest"],
                    f"ถึงประมาณ {dest_eta.strftime('%H:%M น.')}", w_b,
                )
            )
        st.markdown(f'<div class="weather-grid">{"".join(cards_html)}</div>', unsafe_allow_html=True)

        st.subheader("🗺️ แผนที่เส้นทาง")
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            show_radar = st.checkbox("🌧️ แสดงเรดาร์ฝนล่าสุดบนแผนที่ (RainViewer)", value=True, key="radar_tab2")
        with col_r2:
            show_fuel = st.checkbox("⛽ แสดงปั๊มน้ำมันตามเส้นทาง (รัศมี 3 กม.)", value=True, key="fuel_tab2")

        mid_idx = len(selected_route["path"]) // 2
        map_center = selected_route["path"][mid_idx]
        m = folium.Map(location=map_center, zoom_start=6 if selected_route["dist_km"] > 300 else 10)

        folium.PolyLine(
            locations=selected_route["path"], color="#0066FF", weight=6, opacity=0.8, popup=selected_route["label"]
        ).add_to(m)
        folium.Marker(
            [s_data["lat_a"], s_data["lon_a"]],
            popup=f"ต้นทาง: {s_data['origin']}",
            icon=folium.Icon(color="green", icon="play"),
        ).add_to(m)
        folium.Marker(
            [s_data["lat_b"], s_data["lon_b"]],
            popup=f"ปลายทาง: {s_data['dest']} (ถึง ~{dest_eta.strftime('%H:%M น.')})",
            icon=folium.Icon(color="red", icon="flag"),
        ).add_to(m)
        for wp in waypoints:
            folium.Marker(
                [wp["lat"], wp["lon"]],
                popup=f"กม.ที่ {wp['km_marker']}: {wp['location_name']} (ถึง ~{wp['eta_str']})",
                icon=folium.Icon(color="orange", icon="info-sign"),
            ).add_to(m)

        if show_fuel:
            sample_for_fuel = tuple(tuple(p) for p in downsample_path(selected_route["path"], max_points=60))
            fuel_stations = get_fuel_stations_along_route(sample_for_fuel)
            if fuel_stations:
                st.caption(f"⛽ พบปั๊มน้ำมัน {len(fuel_stations)} แห่ง ในระยะ ~3 กม. จากเส้นทาง")
                fuel_group = folium.FeatureGroup(name="ปั๊มน้ำมัน (Fuel Stations)")
                for fs in fuel_stations:
                    folium.Marker(
                        [fs["lat"], fs["lon"]],
                        popup=fs["name"],
                        tooltip=fs["name"],
                        icon=folium.DivIcon(
                            html='<div style="font-size:18px; line-height:1;">⛽</div>',
                            icon_size=(22, 22), icon_anchor=(11, 11),
                        ),
                    ).add_to(fuel_group)
                fuel_group.add_to(m)
            else:
                st.caption("⛽ ไม่พบข้อมูลปั๊มน้ำมันตามเส้นทางนี้ในฐานข้อมูล OpenStreetMap")

        if show_radar:
            tile_url = get_rain_radar_tile_url()
            if tile_url:
                folium.raster_layers.TileLayer(
                    tiles=tile_url, attr="RainViewer.com", name="เรดาร์ฝน (Rain Radar)",
                    overlay=True, opacity=0.55,
                ).add_to(m)
            else:
                st.caption("⚠️ ไม่สามารถโหลดข้อมูลเรดาร์ฝนได้ในขณะนี้")

        folium.LayerControl(collapsed=False).add_to(m)
        st_folium(m, width=1100, height=500, key="osrm_route_map", returned_objects=[])
    else:
        st.info('👈 กรอกจุดเริ่มต้น/ปลายทางในแถบด้านซ้าย แล้วกด "ค้นหาเส้นทาง & สภาพอากาศ" เพื่อเริ่มต้น')
