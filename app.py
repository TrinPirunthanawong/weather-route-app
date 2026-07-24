"""
Weather & Route-Based Forecast
--------------------------------
เวอร์ชันปรับปรุง เพิ่มฟีเจอร์:
  1. เพิ่มจุดแวะระหว่างทางได้ (multi-stop route)
  2. เรดาร์ฝนแบบเรียลไทม์ (RainViewer) แสดงบนแผนที่
  3. ตรวจจับ Time zone ของอุปกรณ์ผู้ใช้อัตโนมัติ (ไม่ล็อกตายตัวเป็นเวลาเซิร์ฟเวอร์)
  4. ลดการรีเฟรช/คำนวณซ้ำซ้อน ด้วย st.cache_data + session_state + st_folium(returned_objects=[])
  5. ปุ่ม "ตำแหน่งของฉัน" อ้างอิงตำแหน่ง GPS จริงของอุปกรณ์ ใช้เป็นจุด A อัตโนมัติ
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import folium
import requests
import streamlit as st
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation, streamlit_js_eval

st.set_page_config(page_title="Weather & Route-Based Forecast", page_icon="⛅", layout="wide")

# =========================================================================
# 0. TIMEZONE ตามอุปกรณ์ผู้ใช้ (ฟีเจอร์ 3)
# =========================================================================
# ตรวจจับแค่ครั้งเดียวต่อ session เพื่อไม่ให้ JS call ยิงซ้ำทุครั้งที่มีการ rerun
# (เป็นส่วนหนึ่งของฟีเจอร์ 4 - ลดงานที่ไม่จำเป็น)
if "device_tz" not in st.session_state:
    st.session_state["device_tz"] = "Asia/Bangkok"  # ค่าเริ่มต้นระหว่างรอผลจากเบราว์เซอร์
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
    """เวลาปัจจุบัน ตาม Time zone ของอุปกรณ์ผู้ใช้งาน (ไม่ใช่เวลาเซิร์ฟเวอร์)"""
    return datetime.now(DEVICE_TZ)


st.title("⛅ Weather & Route-Based Forecast")
st.caption(
    "ระบบเช็กสภาพอากาศ ณ จุดปัจจุบัน และวิเคราะห์สภาพอากาศตามเส้นทางเดินทางจริงแบบเรียลไทม์  \n"
    f"🕒 เขตเวลาอ้างอิง: **{st.session_state['device_tz']}** "
    f"(เวลาขณะนี้ {now_local().strftime('%d/%m/%Y %H:%M')} น.)"
)

tab1, tab2 = st.tabs(["📍 สภาพอากาศ ณ จุดที่อยู่/ค้นหา", "🚗 เช็กสภาพอากาศระหว่างทาง (A ➔ B)"])


# =========================================================================
# 1. HELPER / CACHED FUNCTIONS  (ฟีเจอร์ 4 - cache ตัดการเรียก API ซ้ำ)
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


@st.cache_data(ttl=600, show_spinner=False)
def _get_weather_raw(lat: float, lon: float):
    """ดึงข้อมูลดิบจาก Open-Meteo (cache 10 นาที ต่อพิกัด ลดการยิง API ซ้ำ)"""
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,weather_code"
        f"&hourly=temperature_2m,precipitation_probability,weather_code"
        f"&timezone=auto"
    )
    res = requests.get(url, timeout=10)
    res.raise_for_status()
    return res.json()


def _nearest_hour_index(hourly_times, target_naive_dt):
    """หา index ของเวลาใน hourly_times ที่ใกล้เคียง target มากที่สุด (กันเคส exact-match ไม่เจอ)"""
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
    """
    ดึงสภาพอากาศ ณ พิกัดที่ระบุ
    target_time: datetime แบบ timezone-aware (เช่นจาก now_local()) หรือ None = เอาค่าปัจจุบัน
    ภายในจะแปลงเวลาเป็น local-time ของพิกัดนั้น ๆ เอง (ใช้ utc_offset_seconds จาก Open-Meteo)
    เพื่อความแม่นยำ แม้ผู้ใช้และจุดหมายจะอยู่คนละ time zone กัน
    """
    try:
        raw = _get_weather_raw(round(lat, 3), round(lon, 3))
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการดึงสภาพอากาศ: {e}")
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


@st.cache_data(ttl=300, show_spinner=False)
def get_rain_radar_tile_url():
    """ดึง URL เทมเพลตของเฟรมเรดาร์ฝนล่าสุดจาก RainViewer (ฟีเจอร์ 2)"""
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
    """สุ่มจุดตรวจอากาศอัตโนมัติระหว่างทาง (ใช้เมื่อผู้ใช้ไม่ได้กำหนดจุดแวะเอง)"""
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
    """
    coords: tuple ของ (lat, lon) เรียงจาก ต้นทาง -> จุดแวะ(0..n) -> ปลายทาง (>= 2 จุด)
    หมายเหตุ: OSRM demo server สาธารณะรองรับเฉพาะโปรไฟล์ถนนสำหรับรถยนต์ในการหาเส้นทางจริง
    ระบบจึงคำนวณ "ระยะทาง/เวลา" ที่แสดงผลใหม่ตามโหมดที่ผู้ใช้เลือกภายหลังจากได้เส้นทางมาแล้ว
    """
    coord_str = ";".join([f"{lon},{lat}" for lat, lon in coords])
    allow_alt = "true" if len(coords) == 2 else "false"  # alternatives ใช้ได้แค่กรณี A->B ตรง ๆ
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
    else:  # driving
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

        # ระยะสะสม (กม.) ณ แต่ละจุดแวะ - ใช้คำนวณ ETA ของจุดแวะที่ผู้ใช้กำหนดเองอย่างแม่นยำ
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


# =========================================================================
# 2. TAB 1 - จุดเดียว
# =========================================================================
with tab1:
    st.header("🔍 ค้นหาสภาพอากาศตามพื้นที่")
    with st.form("single_form"):
        place_input = st.text_input(
            "พิมพ์ชื่อเขต/อำเภอ หรือจังหวัด", value="", placeholder="เช่น กรุงเทพมหานคร"
        )
        submit_single = st.form_submit_button("เช็กสภาพอากาศ")

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
            else:
                st.session_state.pop("tab1_point", None)
                st.error("ไม่พบข้อมูลสถานที่ดังกล่าว")
        else:
            st.warning("กรุณากรอกชื่อสถานที่ที่ต้องการค้นหา")

    # แผนที่ขนาดเล็ก + เรดาร์ฝน สำหรับจุดที่ค้นหาล่าสุด
    if "tab1_point" in st.session_state:
        p = st.session_state["tab1_point"]
        show_radar_t1 = st.checkbox("🌧️ แสดงเรดาร์ฝนล่าสุดบนแผนที่", value=True, key="radar_tab1")
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
        st_folium(m1, width=1100, height=400, key="tab1_map", returned_objects=[])


# =========================================================================
# 3. TAB 2 - เส้นทาง A -> (จุดแวะ) -> B
# =========================================================================
with tab2:
    st.header("🛣️ พยากรณ์สภาพอากาศตามเส้นทาง (A ➔ B)")

    # --- session state defaults ---
    st.session_state.setdefault("stop_ids", [])
    st.session_state.setdefault("stop_counter", 0)
    st.session_state.setdefault("awaiting_geo", False)
    st.session_state.setdefault("origin_coords_override", None)
    st.session_state.setdefault("origin_override_label", None)

    # --- ปุ่ม "ตำแหน่งของฉัน" (ฟีเจอร์ 5) ---
    # สำคัญ: ต้องประมวลผลผลลัพธ์ GPS และตั้งค่า session_state["origin_input"] ให้เสร็จ
    # ก่อนที่จะสร้าง widget text_input(key="origin_input") ด้านล่าง มิฉะนั้น Streamlit
    # จะโยน StreamlitAPIException เพราะห้ามแก้ค่า session_state ของ widget ที่ instantiate ไปแล้ว
    geo_status_msg = None
    if st.session_state["awaiting_geo"]:
        geo = get_geolocation()
        if geo and geo.get("coords"):
            lat_g = geo["coords"]["latitude"]
            lon_g = geo["coords"]["longitude"]
            label = get_location_name(lat_g, lon_g)
            st.session_state["origin_input"] = label  # ตั้งค่าได้ เพราะยังไม่มี widget key นี้ในรันนี้
            st.session_state["origin_coords_override"] = (lat_g, lon_g)
            st.session_state["origin_override_label"] = label
            st.session_state["awaiting_geo"] = False
            geo_status_msg = ("success", f"📍 ตั้งจุดเริ่มต้น (A) เป็นตำแหน่งปัจจุบัน: {label}")
        else:
            geo_status_msg = (
                "info",
                "🔄 กำลังขอสิทธิ์เข้าถึงตำแหน่งจากเบราว์เซอร์ กรุณากด **อนุญาต (Allow)** ที่แถบแจ้งเตือนของเบราว์เซอร์",
            )

    col_a, col_b, col_mode = st.columns([2, 2, 1.5])
    with col_a:
        sub_a1, sub_a2 = st.columns([3, 1.4])
        with sub_a1:
            origin_input = st.text_input(
                "🟢 จุดเริ่มต้น (A)", key="origin_input", placeholder="เช่น ธนาคารแห่งประเทศไทย"
            )
        with sub_a2:
            st.markdown("&nbsp;")
            locate_clicked = st.button("📍 ตำแหน่งของฉัน", key="locate_btn", use_container_width=True)
    with col_b:
        dest_input = st.text_input("🔴 ปลายทาง (B)", key="dest_input", placeholder="เช่น เชียงราย")
    with col_mode:
        mode_options = {"🚗 รถยนต์": "driving", "🏍️ มอเตอร์ไซค์/จักรยาน": "bike", "🚶 เดิน": "foot"}
        selected_mode_label = st.selectbox("รูปแบบการเดินทาง", options=list(mode_options.keys()), index=0)
        travel_mode = mode_options[selected_mode_label]

    # แสดงสถานะการขอตำแหน่ง (ใต้แถวช่องกรอก เพื่อไม่ต้องรีรันซ้ำเหมือนโค้ดเดิม)
    if geo_status_msg:
        kind, msg = geo_status_msg
        (st.success if kind == "success" else st.info)(msg)

    # ปุ่มถูกกดในรันนี้ -> ตั้งสถานะรอผล แล้วรีรันหนึ่งครั้งเพื่อให้ get_geolocation() เริ่มทำงาน
    if locate_clicked:
        st.session_state["awaiting_geo"] = True
        st.rerun()

    # --- จุดแวะระหว่างทาง (ฟีเจอร์ 1) ---
    st.markdown("**🟠 จุดแวะระหว่างทาง (ถ้ามี)**")
    for sid in list(st.session_state["stop_ids"]):
        scol1, scol2 = st.columns([6, 1])
        with scol1:
            st.text_input(
                "จุดแวะ",
                key=f"stop_{sid}",
                placeholder="เช่น นครสวรรค์",
                label_visibility="collapsed",
            )
        with scol2:
            if st.button("🗑️ ลบ", key=f"remove_{sid}"):
                st.session_state["stop_ids"].remove(sid)
                st.session_state.pop(f"stop_{sid}", None)
                st.rerun()

    if st.button("➕ เพิ่มจุดแวะ"):
        st.session_state["stop_counter"] += 1
        st.session_state["stop_ids"].append(st.session_state["stop_counter"])
        st.rerun()

    submit_route = st.button("🔍 ค้นหาเส้นทาง & สภาพอากาศ", type="primary")

    if submit_route:
        if not origin_input.strip() or not dest_input.strip():
            st.session_state.pop("search_data", None)
            st.warning("⚠️ กรุณากรอกทั้งจุดเริ่มต้น (จุด A) และจุดหมายปลายทาง (จุด B) ให้ครบถ้วนครับ")
        else:
            with st.spinner(f"กำลังคำนวณเส้นทาง [{selected_mode_label}] และดึงข้อมูลสภาพอากาศ..."):
                # จุด A: ใช้พิกัด GPS จริงถ้าเพิ่งกดปุ่ม "ตำแหน่งของฉัน" มา และข้อความยังตรงกับตอนตั้งค่า
                if (
                    st.session_state["origin_coords_override"]
                    and origin_input.strip() == st.session_state["origin_override_label"]
                ):
                    lat_a, lon_a = st.session_state["origin_coords_override"]
                    name_a = origin_input
                else:
                    lat_a, lon_a, name_a = get_coordinates(origin_input)

                lat_b, lon_b, name_b = get_coordinates(dest_input)

                # จุดแวะ: geocode ทุกจุดที่ผู้ใช้กรอก (ข้ามช่องว่าง)
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
                    else:
                        st.session_state.pop("search_data", None)
                        st.error("ไม่สามารถคำนวณเส้นทางระหว่างจุดที่กำหนดได้")
                else:
                    st.session_state.pop("search_data", None)
                    st.error("ไม่พบพิกัดของสถานที่ที่ระบุ กรุณาตรวจสอบชื่ออีกครั้ง")

    # --- แสดงผล ---
    if "search_data" in st.session_state and origin_input.strip() and dest_input.strip():
        s_data = st.session_state["search_data"]

        route_labels = [r["label"] for r in s_data["routes"]]
        selected_label = st.radio("เลือกเส้นทาง:", route_labels, index=0, key="route_radio")
        selected_route = next(r for r in s_data["routes"] if r["label"] == selected_label)
        stop_coords = s_data["stop_coords"]

        # --- คำนวณ ETA ของแต่ละจุดแวะที่ผู้ใช้กำหนดเอง (แม่นยำกว่า sampling เพราะอิงระยะสะสมจริงจาก OSRM) ---
        waypoints = []
        if stop_coords:
            for i, sc in enumerate(stop_coords):
                cum_km = selected_route["leg_cum_km"][i] if i < len(selected_route["leg_cum_km"]) else 0
                travel_hours = cum_km / selected_route["avg_speed_kmh"]
                eta_time = now_local() + timedelta(hours=travel_hours)
                waypoints.append(
                    {
                        "lat": sc["lat"],
                        "lon": sc["lon"],
                        "km_marker": round(cum_km, 1),
                        "location_name": sc["input"],
                        "eta_time": eta_time,
                        "eta_str": eta_time.strftime("%H:%M น."),
                    }
                )
        else:
            # ไม่มีจุดแวะที่ผู้ใช้กำหนด -> ใช้การสุ่มจุดตรวจอากาศอัตโนมัติแบบเดิม
            waypoints = sample_route_points(
                selected_route["path"], selected_route["dist_km"], selected_route["avg_speed_kmh"]
            )

        total_hours = selected_route["dist_km"] / selected_route["avg_speed_kmh"]
        dest_eta = now_local() + timedelta(hours=total_hours)
        w_b = get_weather(s_data["lat_b"], s_data["lon_b"], target_time=dest_eta)

        st.success(
            f"📍 โหมด: **{s_data['profile_label']}** | ระยะทาง: **{selected_route['dist_km']} กม.** | "
            f"เวลาเดินทางโดยประมาณ: **{selected_route['time_str']}**"
        )

        # ดึงอากาศของทุกจุดแวะ "ครั้งเดียว" แล้วใช้ซ้ำทั้งส่วนแจ้งเตือนและการ์ด (ฟีเจอร์ 4 - ลดการยิง API ซ้ำ)
        waypoint_weather = [
            (wp, get_weather(wp["lat"], wp["lon"], target_time=wp["eta_time"])) for wp in waypoints
        ]

        # --- แจ้งเตือนฝนตกหนักระหว่างทาง ---
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
            warning_msg = "  \n".join([f"• {w}" for w in rain_warnings])
            st.error(
                "⚠️ **แจ้งเตือนสภาพอากาศบนเส้นทาง:**  \n"
                f"พบพื้นที่เสี่ยงฝนตกหนักระหว่างเดินทางตามเวลาที่คาดว่าจะไปถึง:  \n{warning_msg}"
            )

        # --- การ์ดแสดงผล ---
        total_card_cols = 2 + len(waypoints)
        cols = st.columns(total_card_cols)

        if s_data["w_a"]:
            with cols[0]:
                st.info(
                    f"🟢 **ต้นทาง**\n\n📍 {s_data['origin']}\n\n⏰ ออกเดินทางตอนนี้ "
                    f"({now_local().strftime('%H:%M')} น.)\n\n"
                    f"- สภาพอากาศ: {interpret_weather_code(s_data['w_a']['code'])}\n"
                    f"- อุณหภูมิ: {s_data['w_a']['temp']}°C\n"
                    f"- โอกาสฝนตก: {s_data['w_a']['prob']}%"
                )

        for idx, (wp, w_wp) in enumerate(waypoint_weather):
            if w_wp:
                with cols[idx + 1]:
                    st.warning(
                        f"🟡 **กม.ที่ {wp['km_marker']}**\n\n📍 {wp['location_name']}\n\n"
                        f"⏰ ถึงประมาณ {wp['eta_str']}\n\n"
                        f"- สภาพอากาศ: {interpret_weather_code(w_wp['code'])}\n"
                        f"- อุณหภูมิ: {w_wp['temp']}°C\n"
                        f"- โอกาสฝนตก: {w_wp['prob']}%"
                    )

        if w_b:
            with cols[-1]:
                st.info(
                    f"🏁 **ปลายทาง**\n\n📍 {s_data['dest']}\n\n"
                    f"⏰ ถึงประมาณ {dest_eta.strftime('%H:%M น.')}\n\n"
                    f"- สภาพอากาศ: {interpret_weather_code(w_b['code'])}\n"
                    f"- อุณหภูมิ: {w_b['temp']}°C\n"
                    f"- โอกาสฝนตก: {w_b['prob']}%"
                )

        # --- แผนที่ ---
        st.subheader("🗺️ แผนที่เส้นทาง")
        show_radar = st.checkbox("🌧️ แสดงเรดาร์ฝนล่าสุดบนแผนที่ (RainViewer)", value=True, key="radar_tab2")

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

        if show_radar:
            tile_url = get_rain_radar_tile_url()
            if tile_url:
                folium.raster_layers.TileLayer(
                    tiles=tile_url,
                    attr="RainViewer.com",
                    name="เรดาร์ฝน (Rain Radar)",
                    overlay=True,
                    opacity=0.55,
                ).add_to(m)
            else:
                st.caption("⚠️ ไม่สามารถโหลดข้อมูลเรดาร์ฝนได้ในขณะนี้")

        folium.LayerControl(collapsed=False).add_to(m)

        # returned_objects=[] : ไม่ส่งค่ากลับจากแผนที่ (เช่น last_clicked) กลับมาที่ Python
        # ทำให้การ hover/คลิกแผนที่ไม่ trigger การ rerun ทั้งหน้าโดยไม่จำเป็น (ฟีเจอร์ 4)
        st_folium(m, width=1100, height=500, key="osrm_route_map", returned_objects=[])
