from datetime import datetime, timedelta
import requests
import folium
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="Weather & Route-Based Forecast", page_icon="⛅", layout="wide")

st.title("⛅ Weather & Route-Based Forecast")
st.caption("ระบบเช็กสภาพอากาศ ณ จุดปัจจุบัน และวิเคราะห์สภาพอากาศตามเส้นทางเดินทางจริงแบบเรียลไทม์")

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

def get_location_name(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=10"
    headers = {"User-Agent": "WeatherApp/1.0"}
    try:
        res = requests.get(url, headers=headers, timeout=5).json()
        address = res.get('address', {})
        city = address.get('state') or address.get('province') or address.get('city') or address.get('county') or "จุดระหว่างทาง"
        return city
    except:
        return "จุดระหว่างทาง"

def sample_route_points(path, total_dist_km, avg_speed_kmh):
    num_coords = len(path)
    if num_coords <= 2:
        return []

    if total_dist_km >= 100:
        step_count = min(int(total_dist_km // 150), 5)
        if step_count < 1:
            step_count = 1
    else:
        step_count = 1

    sampled_points = []
    step_size = num_coords // (step_count + 1)

    for i in range(1, step_count + 1):
        idx = i * step_size
        if idx < num_coords:
            pt = path[idx]
            dist_at_pt = round((total_dist_km / (step_count + 1)) * i, 1)
            
            # คำนวณเวลาที่คาดว่าจะไปถึงจุดนี้ (ชั่วโมง)
            travel_hours = dist_at_pt / avg_speed_kmh
            eta_time = datetime.now() + timedelta(hours=travel_hours)
            
            loc_name = get_location_name(pt[0], pt[1])
            sampled_points.append({
                'lat': pt[0],
                'lon': pt[1],
                'km_marker': dist_at_pt,
                'location_name': loc_name,
                'eta_time': eta_time,
                'eta_str': eta_time.strftime("%H:%M น.")
            })

    return sampled_points

def get_route_osrm(lat_a, lon_a, lat_b, lon_b, mode="driving"):
    url = f"http://router.project-osrm.org/route/v1/driving/{lon_a},{lat_a};{lon_b},{lat_b}?overview=full&geometries=geojson&alternatives=true"
    
    try:
        res = requests.get(url, timeout=10).json()
        if "routes" in res and len(res["routes"]) > 0:
            routes_data = []
            
            if mode == "bike":
                dist_factor = 0.95
                avg_speed_kmh = 80
            elif mode == "foot":
                dist_factor = 0.85
                avg_speed_kmh = 3.0
            else: # driving
                dist_factor = 1.0
                avg_speed_kmh = 100

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
                
                label_prefix = "เส้นทางหลัก" if idx == 0 else f"ทางเลือกที่ {idx}"
                
                routes_data.append({
                    'id': idx,
                    'label': f"{label_prefix} - {dist_km} กม. ({time_str})",
                    'path': path,
                    'dist_km': dist_km,
                    'time_str': time_str,
                    'avg_speed_kmh': avg_speed_kmh
                })
            return routes_data
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการเชื่อมต่อ OSRM: {e}")
    return []

def get_weather(lat, lon, target_time=None):
    """ ดึงสภาพอากาศอิงตามเวลาที่ระบุ (ETA) """
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code&hourly=temperature_2m,precipitation_probability,weather_code&timezone=auto"
    try:
        res = requests.get(url, timeout=10).json()
        if target_time and 'hourly' in res:
            hourly_times = res['hourly']['time']
            # หา Index ของชั่วโมงที่ใกล้เคียงเวลา ETA มากที่สุด
            target_str = target_time.strftime("%Y-%m-%dT%H:00")
            if target_str in hourly_times:
                idx = hourly_times.index(target_str)
            else:
                idx = 0
            
            return {
                'temp': res['hourly']['temperature_2m'][idx],
                'prob': res['hourly']['precipitation_probability'][idx],
                'code': res['hourly']['weather_code'][idx]
            }
        else:
            # กรณีดึงเวลาปัจจุบัน
            curr = res.get('current', {})
            prob = res.get('hourly', {}).get('precipitation_probability', [0])[0]
            return {
                'temp': curr.get('temperature_2m'),
                'prob': prob,
                'code': curr.get('weather_code')
            }
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
        place_input = st.text_input("พิมพ์ชื่อเขต/อำเภอ หรือจังหวัด", value="", placeholder="เช่น กรุงเทพมหานคร")
        submit_single = st.form_submit_button("เช็กสภาพอากาศ")
        
    if submit_single:
        if place_input.strip():
            lat, lon, name = get_coordinates(place_input)
            if lat and lon:
                w = get_weather(lat, lon)
                if w:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("🌡️ อุณหภูมิปัจจุบัน", f"{w['temp']} °C")
                    c2.metric("📊 สภาพอากาศ", interpret_weather_code(w['code']))
                    c3.metric("🌧️ โอกาสฝนตก", f"{w['prob']} %")
            else:
                st.error("ไม่พบข้อมูลสถานที่ดังกล่าว")
        else:
            st.warning("กรุณากรอกชื่อสถานที่ที่ต้องการค้นหา")

# --- TAB 2 ---
with tab2:
    st.header("🛣️ พยากรณ์สภาพอากาศตามเส้นทาง (A ➔ B)")
    
    with st.form("route_form"):
        col_a, col_b, col_mode = st.columns([2, 2, 1.5])
        with col_a:
            origin_input = st.text_input("🟢 จุดเริ่มต้น (A)", value="", placeholder="เช่น ธนาคารแห่งประเทศไทย")
        with col_b:
            dest_input = st.text_input("🔴 ปลายทาง (B)", value="", placeholder="เช่น เชียงราย")
        with col_mode:
            mode_options = {
                "🚗 รถยนต์": "driving",
                "🏍️ มอเตอร์ไซค์/จักรยาน": "bike",
                "🚶 เดิน": "foot"
            }
            selected_mode_label = st.selectbox("รูปแบบการเดินทาง", options=list(mode_options.keys()), index=0)
            travel_mode = mode_options[selected_mode_label]
            
        submit_route = st.form_submit_button("🔍 ค้นหาเส้นทาง & สภาพอากาศ")
        
    if submit_route:
        if not origin_input.strip() or not dest_input.strip():
            st.session_state.pop('search_data', None)
            st.warning("⚠️ กรุณากรอกทั้งจุดเริ่มต้น (จุด A) และจุดหมายปลายทาง (จุด B) ให้ครบถ้วนครับ")
        else:
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
                            'w_a': get_weather(lat_a, lon_a)
                        }
                    else:
                        st.session_state.pop('search_data', None)
                        st.error("ไม่สามารถคำนวณเส้นทางระหว่างสองจุดนี้ได้")
                else:
                    st.session_state.pop('search_data', None)
                    st.error("ไม่พบพิกัดของสถานที่ที่ระบุ กรุณาตรวจสอบชื่ออีกครั้ง")

    if 'search_data' in st.session_state and origin_input.strip() and dest_input.strip():
        s_data = st.session_state['search_data']
        
        route_labels = [r['label'] for r in s_data['routes']]
        selected_label = st.radio("เลือกเส้นทาง:", route_labels, index=0)
        selected_route = next(r for r in s_data['routes'] if r['label'] == selected_label)
        
        waypoints = sample_route_points(selected_route['path'], selected_route['dist_km'], selected_route['avg_speed_kmh'])
        
        # คำนวณเวลาปลายทาง (ETA ปลายทาง)
        total_hours = selected_route['dist_km'] / selected_route['avg_speed_kmh']
        dest_eta = datetime.now() + timedelta(hours=total_hours)
        w_b = get_weather(s_data['lat_b'], s_data['lon_b'], target_time=dest_eta)
        
        st.success(f"📍 โหมด: **{s_data['profile_label']}** | ระยะทาง: **{selected_route['dist_km']} กม.** | เวลาเดินทางโดยประมาณ: **{selected_route['time_str']}**")
        
        # --- FEATURE 1: RAIN WARNING BANNER ---
        rain_warnings = []
        for wp in waypoints:
            w_check = get_weather(wp['lat'], wp['lon'], target_time=wp['eta_time'])
            if w_check and (w_check['prob'] >= 50 or w_check['code'] in [61, 63, 65, 80, 81, 82, 95, 96, 99]):
                rain_warnings.append(f"กม.ที่ {wp['km_marker']} ({wp['location_name']}) เวลาประมาณ {wp['eta_str']} [โอกาสฝนตก {w_check['prob']}% - {interpret_weather_code(w_check['code'])}]")
                
        if w_b and (w_b['prob'] >= 50 or w_b['code'] in [61, 63, 65, 80, 81, 82, 95, 96, 99]):
            rain_warnings.append(f"ปลายทาง ({s_data['dest']}) เวลาประมาณ {dest_eta.strftime('%H:%M น.')} [โอกาสฝนตก {w_b['prob']}% - {interpret_weather_code(w_b['code'])}]")

        if rain_warnings:
            warning_msg = "  \n".join([f"• {w}" for w in rain_warnings])
            st.error(f"⚠️ **แจ้งเตือนสภาพอากาศบนเส้นทาง:**  \nพบพื้นที่เสี่ยงฝนตกหนักระหว่างเดินทางตามเวลาที่คาดว่าจะไปถึง:  \n{warning_msg}")

        # --- CARDS SHOWCASE ---
        total_card_cols = 2 + len(waypoints)
        cols = st.columns(total_card_cols)
        
        # 1. การ์ดต้นทาง
        if s_data['w_a']:
            with cols[0]:
                st.info(f"🟢 **ต้นทาง**\n\n"
                        f"📍 {s_data['origin']}\n\n"
                        f"⏰ ออกเดินทางตอนนี้\n\n"
                        f"- สภาพอากาศ: {interpret_weather_code(s_data['w_a']['code'])}\n"
                        f"- อุณหภูมิ: {s_data['w_a']['temp']}°C\n"
                        f"- โอกาสฝนตก: {s_data['w_a']['prob']}%")
                        
        # 2. การ์ดระหว่างทาง (FEATURE 2: WEATHER BY ETA TIME)
        for idx, wp in enumerate(waypoints):
            w_wp = get_weather(wp['lat'], wp['lon'], target_time=wp['eta_time'])
            if w_wp:
                with cols[idx + 1]:
                    st.warning(f"🟡 **กม.ที่ {wp['km_marker']}**\n\n"
                               f"📍 {wp['location_name']}\n\n"
                               f"⏰ ถึงประมาณ {wp['eta_str']}\n\n"
                               f"- สภาพอากาศ: {interpret_weather_code(w_wp['code'])}\n"
                               f"- อุณหภูมิ: {w_wp['temp']}°C\n"
                               f"- โอกาสฝนตก: {w_wp['prob']}%")
                           
        # 3. การ์ดปลายทาง
        if w_b:
            with cols[-1]:
                st.info(f"🏁 **ปลายทาง**\n\n"
                        f"📍 {s_data['dest']}\n\n"
                        f"⏰ ถึงประมาณ {dest_eta.strftime('%H:%M น.')}\n\n"
                        f"- สภาพอากาศ: {interpret_weather_code(w_b['code'])}\n"
                        f"- อุณหภูมิ: {w_b['temp']}°C\n"
                        f"- โอกาสฝนตก: {w_b['prob']}%")
        
        # --- MAP SHOWCASE ---
        st.subheader("🗺️ แผนที่เส้นทาง")
        mid_idx = len(selected_route['path']) // 2
        map_center = selected_route['path'][mid_idx]
        
        m = folium.Map(location=map_center, zoom_start=6 if selected_route['dist_km'] > 300 else 10)
        
        folium.PolyLine(
            locations=selected_route['path'],
            color="#0066FF", weight=6, opacity=0.8,
            popup=selected_route['label']
        ).add_to(m)
        
        folium.Marker([s_data['lat_a'], s_data['lon_a']], popup=f"ต้นทาง: {s_data['origin']}", icon=folium.Icon(color="green", icon="play")).add_to(m)
        folium.Marker([s_data['lat_b'], s_data['lon_b']], popup=f"ปลายทาง: {s_data['dest']} (ถึง ~{dest_eta.strftime('%H:%M น.')})", icon=folium.Icon(color="red", icon="flag")).add_to(m)
        
        for wp in waypoints:
            folium.Marker(
                [wp['lat'], wp['lon']],
                popup=f"กม.ที่ {wp['km_marker']}: {wp['location_name']} (ถึง ~{wp['eta_str']})",
                icon=folium.Icon(color="orange", icon="info-sign")
            ).add_to(m)
        
        st_folium(m, width=1100, height=500, key="osrm_route_map")
