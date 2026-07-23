import streamlit as st
import requests
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Weather & Route-Based Forecast", page_icon="⛅", layout="wide")

st.title("⛅ Weather & Route-Based Forecast")
st.caption("ระบบเช็กสภาพอากาศ ณ จุดปัจจุบัน และวิเคราะห์สภาพอากาศตามเส้นทางเดินทางจริง")

tab1, tab2 = st.tabs(["📍 สภาพอากาศ ณ จุดที่อยู่/ค้นหา", "🚗 เช็กสภาพอากาศระหว่างทาง (A ➔ B)"])

def get_coordinates(place_name):
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={place_name}"
    headers = {"User-Agent": "WeatherApp/1.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        if res:
            return float(res[0]['lat']), float(res[0]['lon']), res[0]['display_name']
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการดึงพิกัด: {e}")
    return None, None, None

def get_route_osrm(lat_a, lon_a, lat_b, lon_b, mode="driving"):
    url = f"http://router.project-osrm.org/route/v1/driving/{lon_a},{lat_a};{lon_b},{lat_b}?overview=full&geometries=geojson&alternatives=true"
    
    try:
        res = requests.get(url, timeout=10).json()
        if "routes" in res and len(res["routes"]) > 0:
            routes_data = []
            
            if mode == "bike":
                dist_factor = 0.95   # สั้นลง 5%
                avg_speed_kmh = 80  # 80 กม./ชม.
            elif mode == "foot":
                dist_factor = 0.85   # สั้นลง 15%
                avg_speed_kmh = 3.0 # 3 กม./ชม.
            else: # driving
                dist_factor = 1.0
                avg_speed_kmh = 100 # 100 กม./ชม.

            for idx, r in enumerate(res["routes"][:2]):
                coordinates = r["geometry"]["coordinates"]
                path = [[coord[1], coord[0]] for coord in coordinates]
                
                raw_dist_km = r["distance"] / 1000
                dist_km = round(raw_dist_km * dist_factor, 2)
                
                duration_hours = dist_km / avg_speed_kmh
                total_minutes = int(duration_hours * 60)
                
                if total_minutes >= 60:
                    hrs = total_minutes // 60
                    mins = total_minutes % 60
                    time_str = f"{hrs} ชม. {mins} นาที"
                else:
                    time_str = f"{total_minutes} นาที"
                
                mid_idx = len(path) // 2
                mid_point = path[mid_idx]
                
                label_prefix = "เส้นทางหลัก" if idx == 0 else f"ทางเลือกที่ {idx}"
                
                routes_data.append({
                    'id': idx,
                    'label': f"{label_prefix} - {dist_km} กม. ({time_str})",
                    'path': path,
                    'mid_point': mid_point,
                    'dist_km': dist_km,
                    'time_str': time_str
                })
            return routes_data
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการเชื่อมต่อ OSRM: {e}")
    return []

def get_weather(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,precipitation,weather_code&hourly=precipitation_probability"
    try:
        res = requests.get(url, timeout=10).json()
        return res
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการดึงสภาพอากาศ: {e}")
        return None

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

# --- TAB 1 ---
with tab1:
    st.header("🔍 ค้นหาสภาพอากาศตามพื้นที่")
    with st.form("single_form"):
        place_input = st.text_input("พิมพ์ชื่อเขต/อำเภอ หรือจังหวัด", value="กรุงเทพมหานคร")
        submit_single = st.form_submit_button("เช็กสภาพอากาศ")
        
    if submit_single:
        lat, lon, name = get_coordinates(place_input)
        if lat and lon:
            w = get_weather(lat, lon)
            if w:
                curr = w.get('current', {})
                prob = w.get('hourly', {}).get('precipitation_probability', [0])[0]
                c1, c2, c3 = st.columns(3)
                c1.metric("🌡️ อุณหภูมิปัจจุบัน", f"{curr.get('temperature_2m')} °C")
                c2.metric("📊 สภาพอากาศ", interpret_weather_code(curr.get('weather_code')))
                c3.metric("🌧️ โอกาสฝนตก", f"{prob} %")

# --- TAB 2 ---
with tab2:
    st.header("🚗 วิเคราะห์สภาพอากาศตามเส้นทางเดินทางจริง")
    
    with st.form("route_form"):
        col_a, col_b, col_mode = st.columns([2, 2, 1.5])
        with col_a:
            origin_input = st.text_input("จุดเริ่มต้น (จุด A)", value="ธนาคารแห่งประเทศไทย")
        with col_b:
            dest_input = st.text_input("จุดหมายปลายทาง (จุด B)", value="ซอย วัดไพรฟ้า")
        with col_mode:
            mode_options = {
                "🚗 รถยนต์": "driving",
                "🏍️ มอเตอร์ไซค์/จักรยาน": "bike",
                "🚶 เดิน": "foot"
            }
            selected_mode_label = st.selectbox(
                "รูปแบบการเดินทาง",
                options=list(mode_options.keys()),
                index=0
            )
            travel_mode = mode_options[selected_mode_label]
            
        submit_route = st.form_submit_button("วิเคราะห์เส้นทางและสภาพอากาศ")
        
    if submit_route:
        with st.spinner(f"กำลังคำนวณเส้นทาง [{selected_mode_label}] และดึงข้อมูลสภาพอากาศ..."):
            lat_a, lon_a, name_a = get_coordinates(origin_input)
            lat_b, lon_b, name_b = get_coordinates(dest_input)
            
            if lat_a and lat_b:
                routes = get_route_osrm(lat_a, lon_a, lat_b, lon_b, mode=travel_mode)
                
                if routes:
                    st.session_state['search_data'] = {
                        'origin': origin_input,
                        'dest': dest_input,
                        'profile_label': selected_mode_label,
                        'lat_a': lat_a, 'lon_a': lon_a,
                        'lat_b': lat_b, 'lon_b': lon_b,
                        'routes': routes,
                        'w_a': get_weather(lat_a, lon_a),
                        'w_b': get_weather(lat_b, lon_b)
                    }
            else:
                st.error("ไม่พบพิกัดของสถานที่ที่ระบุ กรุณาตรวจสอบชื่ออีกครั้ง")

    if 'search_data' in st.session_state:
        s_data = st.session_state['search_data']
        
        route_labels = [r['label'] for r in s_data['routes']]
        selected_label = st.radio("เลือกเส้นทาง:", route_labels, index=0)
        selected_route = next(r for r in s_data['routes'] if r['label'] == selected_label)
        
        mid_lat, mid_lon = selected_route['mid_point']
        w_mid = get_weather(mid_lat, mid_lon)
        
        st.success(f"📍 โหมด: **{s_data['profile_label']}** | ระยะทาง: **{selected_route['dist_km']} กม.** | เวลาเดินทางโดยประมาณ: **{selected_route['time_str']}**")
        
        c1, c2, c3 = st.columns(3)
        if s_data['w_a']:
            curr_a = s_data['w_a'].get('current', {})
            prob_a = s_data['w_a'].get('hourly', {}).get('precipitation_probability', [0])[0]
            with c1:
                st.info(f"🟢 **ต้นทาง ({s_data['origin']})**\n\n"
                        f"- สภาพอากาศ: {interpret_weather_code(curr_a.get('weather_code'))}\n"
                        f"- อุณหภูมิ: {curr_a.get('temperature_2m')}°C\n"
                        f"- โอกาสฝนตก: {prob_a}%")
                        
        if w_mid:
            curr_mid = w_mid.get('current', {})
            prob_mid = w_mid.get('hourly', {}).get('precipitation_probability', [0])[0]
            with c2:
                st.warning(f"🟡 **จุดระหว่างทาง**\n\n"
                           f"- สภาพอากาศ: {interpret_weather_code(curr_mid.get('weather_code'))}\n"
                           f"- อุณหภูมิ: {curr_mid.get('temperature_2m')}°C\n"
                           f"- โอกาสฝนตก: {prob_mid}%")
                           
        if s_data['w_b']:
            curr_b = s_data['w_b'].get('current', {})
            prob_b = s_data['w_b'].get('hourly', {}).get('precipitation_probability', [0])[0]
            with c3:
                st.info(f"🏁 **ปลายทาง ({s_data['dest']})**\n\n"
                        f"- สภาพอากาศ: {interpret_weather_code(curr_b.get('weather_code'))}\n"
                        f"- อุณหภูมิ: {curr_b.get('temperature_2m')}°C\n"
                        f"- โอกาสฝนตก: {prob_b}%")
        
        st.subheader("🗺️ แผนที่เส้นทาง")
        m = folium.Map(location=[mid_lat, mid_lon], zoom_start=11)
        
        folium.PolyLine(
            locations=selected_route['path'],
            color="#0066FF", weight=6, opacity=0.8,
            popup=selected_route['label']
        ).add_to(m)
        
        folium.Marker([s_data['lat_a'], s_data['lon_a']], popup=f"ต้นทาง: {s_data['origin']}", icon=folium.Icon(color="green", icon="play")).add_to(m)
        folium.Marker([mid_lat, mid_lon], popup="จุดระหว่างทาง", icon=folium.Icon(color="orange", icon="info-sign")).add_to(m)
        folium.Marker([s_data['lat_b'], s_data['lon_b']], popup=f"ปลายทาง: {s_data['dest']}", icon=folium.Icon(color="red", icon="flag")).add_to(m)
        
        st_folium(m, width=1100, height=480, key="osrm_route_map")