import os
import time
import subprocess
from flask import Flask, jsonify, request

# Device info
IPHONE_MAC = "aa:a6:dd:e3:d9:75"
IPHONE_IP = "192.168.1.10"
LAPTOP_IP = "192.168.1.7"

app = Flask(__name__)

def ping_ip(ip):
    result = subprocess.run(
        ["ping", "-n", "1", ip],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return result.returncode == 0

def get_arp_table():
    result = subprocess.run(["arp", "-a"], capture_output=True, text=True)
    return result.stdout.lower()

def is_device_present(mac, ip):
    # Ping IP to refresh ARP cache
    subprocess.run(["ping", "-n", "1", ip], stdout=subprocess.DEVNULL)
    arp = get_arp_table()
    return mac.lower() in arp

@app.route('/device-status', methods=['GET'])
def device_status():
    laptop_present = ping_ip(LAPTOP_IP)
    iphone_present = is_device_present(IPHONE_MAC, IPHONE_IP)
    return jsonify({
        "laptop": "Present" if laptop_present else "Absent",
        "iphone": "Present" if iphone_present else "Absent",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    })

@app.route('/api/submit_attendance', methods=['POST'])
def submit_attendance():
    data = request.get_json()
    print("Attendance submitted:", data)
    # TODO: Add actual validation and storage of attendance here
    return jsonify({"message": "Attendance recorded"}), 200

if __name__ == "__main__":
    app.run(host='localhost', port=8080, debug=True)
