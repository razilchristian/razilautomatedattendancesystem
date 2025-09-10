from flask import Flask, jsonify, request
from flask_cors import CORS
import qrcode
import io
import base64
import json
import datetime
import nmap
import time
from threading import Thread
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib
import requests
import mysql.connector  # For MySQL DB access
import os  # Added for environment variables


app = Flask(__name__)
CORS(app)


# --------- DB connection setup ---------
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',  # Add your DB password if any
    'database': 'studentattendance'
}


def get_db_connection():
    return mysql.connector.connect(**db_config)


# --------- Device and Student Info Management ---------


def fetch_mac_student_mapping():
    """Fetch MAC-to-student mapping ONLY for classroom 602 and role=student."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = """
    SELECT mac_address, student_name, roll, classroom, lecture_time, subject, device_name, role
    FROM device_student_mapping
    WHERE classroom = %s AND role = 'student'
    """
    cursor.execute(query, ('602',))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    mapping = {}
    for row in rows:
        mac = row['mac_address'].lower()
        mapping[mac] = {
            "name": row['student_name'],
            "roll": row['roll'],
            "classroom": row['classroom'],
            "lecture_time": row['lecture_time'],
            "subject": row['subject'],
            "device_name": row['device_name'],
            "role": row['role']  # always 'student' here due to query filter
        }
    return mapping


devices = {}
connected_devices = {}
attendance_records = {}

# Heartbeat records store active presence reported by students
heartbeat_records = {}


def scan_network_and_build_devices():
    global devices
    devices = {}
    mac_student_mapping = fetch_mac_student_mapping()

    subnet = "192.168.1.0/24"
    nm = nmap.PortScanner()

    try:
        nm.scan(hosts=subnet, arguments='-sn -T4')
    except Exception as e:
        print(f"Nmap scan error: {e}")
        return {}

    for host in nm.all_hosts():
        addrs = nm[host]['addresses']
        mac_addr = addrs.get('mac', '')
        mac_addr_lower = mac_addr.lower()
        ip_addr = addrs.get('ipv4', '')
        if mac_addr:
            print(f"Found device - IP: {ip_addr}, MAC: {mac_addr_lower}")
        else:
            print(f"Found device - IP: {ip_addr}, MAC: Unknown")

        # Check if MAC is for a registered student in classroom 602 (case-insensitive)
        if mac_addr and mac_addr_lower in mac_student_mapping:
            student_info = mac_student_mapping[mac_addr_lower]
            if student_info.get("role", "") == "student":
                device_name = student_info.get("device_name", mac_addr_lower)
                devices[device_name] = {
                    "ip": ip_addr,
                    "mac": mac_addr_lower,
                    "student": {
                        "name": student_info["name"],
                        "roll": student_info["roll"],
                        "classroom": student_info["classroom"],
                        "lecture_time": student_info["lecture_time"],
                        "subject": student_info["subject"]
                    }
                }
    print(f"Discovered devices matching mapping: {list(devices.keys())}")
    return devices


def update_connected_devices_loop():
    global connected_devices
    while True:
        try:
            scan_network_and_build_devices()
            connected_devices = {device_name: True for device_name in devices.keys()}
            print(f"Connected devices updated: {connected_devices}")
        except Exception as e:
            print(f"Error in device update loop: {e}")
        time.sleep(30)


def generate_qr_code(data_str):
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(data_str)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    encoded_img = base64.b64encode(buf.getvalue()).decode()
    return "data:image/png;base64," + encoded_img


@app.route("/api/device_status", methods=['GET'])
def device_status():
    status_report = {}
    for device_name, device_info in devices.items():
        status_report[device_name] = {
            "connected": connected_devices.get(device_name, False),
            "ip": device_info["ip"],
            "mac": device_info["mac"],
            "student": device_info["student"]
        }
    return jsonify(status_report)


@app.route("/api/heartbeat", methods=['POST'])
def receive_heartbeat():
    data = request.get_json()
    roll = data.get('roll')
    mac = data.get('mac', '').lower()
    device_name = data.get('device_name', '')
    timestamp = datetime.datetime.now(datetime.timezone.utc)

    if not roll:
        return jsonify({'error': 'Missing roll number'}), 400

    heartbeat_records[roll] = {
        'mac': mac,
        'device_name': device_name,
        'last_seen': timestamp
    }

    print(f"Heartbeat received from roll={roll}, mac={mac}, device={device_name}")
    return jsonify({'status': 'ok'}), 200


@app.route("/api/connected_students", methods=['GET'])
def connected_students():
    results = []
    now = datetime.datetime.now(datetime.timezone.utc)
    timeout = datetime.timedelta(minutes=3)

    mac_student_mapping = fetch_mac_student_mapping()

    # Include students detected by network scan
    for device_name, device_info in devices.items():
        if connected_devices.get(device_name, False):
            student = device_info["student"]
            timestamp = now.isoformat()
            qr_payload = {
                "name": student["name"],
                "roll": student["roll"],
                "classroom": student["classroom"],
                "lecture_time": student["lecture_time"],
                "subject": student["subject"],
                "verified_ip": device_info["ip"],
                "verified_mac": device_info["mac"],
                "attendance_time": timestamp,
                "device_type": device_name
            }
            qr_json = json.dumps(qr_payload)
            qr_img = generate_qr_code(qr_json)
            attendance_marked = student["roll"] in attendance_records
            results.append({
                "present": True,
                "student_info": student,
                "device_ip": device_info["ip"],
                "device_mac": device_info["mac"],
                "qr_code": qr_img,
                "qr_data": qr_json,
                "device_type": device_name,
                "attendance_marked": attendance_marked,
                "attendance_time": attendance_records.get(student["roll"], {}).get("timestamp") if attendance_marked else None
            })

    # Include students detected by recent heartbeat (within timeout), matched by roll number
    for roll, info in heartbeat_records.items():
        last_seen = info.get('last_seen')
        if last_seen and (now - last_seen) < timeout:
            # Lookup student by roll instead of mac
            student = None
            for smac, sdata in mac_student_mapping.items():
                if sdata['roll'] == roll:
                    student = sdata
                    break
            if student is not None:
                timestamp = last_seen.isoformat()
                qr_payload = {
                    "name": student["name"],
                    "roll": student["roll"],
                    "classroom": student["classroom"],
                    "lecture_time": student["lecture_time"],
                    "subject": student["subject"],
                    "verified_mac": info.get('mac', ''),
                    "attendance_time": timestamp,
                    "device_type": info.get('device_name', '')
                }
                qr_json = json.dumps(qr_payload)
                qr_img = generate_qr_code(qr_json)
                attendance_marked = student["roll"] in attendance_records
                results.append({
                    "present": True,
                    "student_info": student,
                    "device_mac": info.get('mac', ''),
                    "qr_code": qr_img,
                    "qr_data": qr_json,
                    "device_type": info.get('device_name', ''),
                    "attendance_marked": attendance_marked,
                    "attendance_time": attendance_records.get(student["roll"], {}).get("timestamp") if attendance_marked else None
                })

    # Remove duplicates if any (by roll)
    seen = set()
    filtered_results = []
    for r in results:
        roll = r["student_info"]["roll"]
        if roll not in seen:
            filtered_results.append(r)
            seen.add(roll)

    return jsonify({
        "connected_students": filtered_results,
        "total_connected": len(filtered_results),
        "scan_time": now.isoformat()
    })


@app.route("/api/submit_attendance", methods=['POST'])
def submit_attendance():
    data = request.get_json()
    if not data or 'roll' not in data:
        return jsonify({"error": "Invalid attendance data"}), 400
    roll = data['roll']
    student_info = None
    for device_info in devices.values():
        if device_info["student"]["roll"] == roll and device_info["student"]["classroom"] == "602":
            student_info = device_info["student"]
            break
    if not student_info:
        # Allow attendance if student in heartbeat but not detected passively
        if roll in heartbeat_records:
            student_info = {"roll": roll, "classroom": "602"}  # minimal info
        else:
            return jsonify({"error": "Student not registered in classroom 602 or not connected"}), 403
    attendance_records[roll] = {
        "data": data,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    print(f"Attendance recorded for roll {roll}: {data}")
    try:
        resp = requests.post('http://localhost:5000/attendance/mark', json={
            'enrollment_no': roll,
            'date': datetime.datetime.now().strftime('%Y-%m-%d'),
            'present': True
        })
        if resp.status_code == 200:
            print(f"Attendance stored in MySQL for roll {roll}")
        else:
            print(f"Failed to store attendance in MySQL: {resp.text}")
    except Exception as e:
        print(f"Error posting attendance to backend: {e}")
    return jsonify({"message": "Attendance recorded"}), 200


@app.route("/api/force_scan", methods=['GET'])
def force_scan():
    global connected_devices
    scan_network_and_build_devices()
    connected_devices = {device_name: True for device_name in devices.keys()}
    return jsonify({
        "message": "Network scan completed",
        "status": connected_devices,
        "scan_time": datetime.datetime.now(datetime.timezone.utc).isoformat()
    })


# ML-Based Attendance Alerts Code
def load_attendance_data():
    data = {
        "Name": ["You", "Riddhi", "Hardik", "Kajal", "Jatin", "Astha"],
        "Lectures_Attended": [70, 80, 80, 60, 62, 56],
        "Total_Lectures": [80] * 6,
    }
    df = pd.DataFrame(data)
    df["Attendance_Percentage"] = (df["Lectures_Attended"] / df["Total_Lectures"]) * 100
    return df


def label_risk(df, threshold=75):
    df["Risk"] = (df["Attendance_Percentage"] < threshold).astype(int)
    return df


def train_model(df):
    X = df[["Attendance_Percentage"]]
    y = df["Risk"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.33, random_state=42)
    clf = RandomForestClassifier(random_state=42)
    clf.fit(X_train, y_train)
    y_pred = clf.predict(X_test)
    print("Model evaluation:\n", classification_report(y_test, y_pred))
    return clf


def generate_alerts(df, clf):
    df["Predicted_Risk"] = clf.predict(df[["Attendance_Percentage"]])
    alerts = []
    for _, row in df.iterrows():
        if row["Predicted_Risk"] == 1:
            alerts.append({
                "student_name": row["Name"],
                "attendance_percentage": f"{row['Attendance_Percentage']:.2f}%",
                "alert_type": "predicted_risk",
                "alert_title": "ML-Based Attendance Risk Alert",
                "alert_message": "Predicted risk due to low attendance"
            })
    return alerts


df = load_attendance_data()
df = label_risk(df)
model = train_model(df)
joblib.dump(model, "attendance_risk_model.joblib")
print("Model saved as attendance_risk_model.joblib")


@app.route('/api/attendance-alerts')
def attendance_alerts():
    alerts = generate_alerts(df, model)
    return jsonify(alerts)


@app.route("/", methods=['GET'])
def home():
    return jsonify({
        "message": "🎯 Attendance System API is running",
        "version": "1.0",
        "endpoints": [
            "/api/device_status - Get status of all devices",
            "/api/connected_students - Get QR codes for connected students",
            "/api/submit_attendance - Submit attendance data",
            "/api/force_scan - Force immediate network scan",
            "/api/attendance-alerts - Get ML-based attendance risk alerts"
        ],
        "monitored_devices": list(devices.keys())
    })


def startup():
    print("🚀 Starting Attendance System Server...")
    print("🔍 Performing initial network scan and building devices list...")
    scan_network_and_build_devices()
    print("🌐 Starting background device update thread...")
    Thread(target=update_connected_devices_loop, daemon=True).start()


# Run explicit startup for Waitress compatibility
startup()


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
