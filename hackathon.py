import os
import time
import subprocess
import nmap

# Add Nmap installation folder to PATH so python-nmap can find it
# Change this path if your Nmap is installed elsewhere
os.environ['PATH'] += r";C:\Program Files (x86)\Nmap"

# Device info
iphone_mac = "aa:a6:dd:e3:d9:75"
iphone_ip = "192.168.1.10"
laptop_ip = "192.168.1.7"
subnet = "192.168.1.0/24"

def scan_network(subnet):
    """
    Scan the subnet with nmap ping scan (-sn), returning the scanner object.
    """
    nm = nmap.PortScanner()
    nm.scan(hosts=subnet, arguments='-sn')
    return nm

def get_mac_from_nmap(nm, host):
    """
    Extract MAC address from a scanned host entry in lowercase.
    """
    return nm[host]['addresses'].get('mac', '').lower()

def is_iphone_present(nm):
    """
    Check if iPhone MAC address exists in nmap scan results.
    """
    for host in nm.all_hosts():
        mac = get_mac_from_nmap(nm, host)
        if mac == iphone_mac:
            return True
    return False

def ping_ip(ip):
    """
    Ping an IP address once silently.
    Returns True if ping is successful, else False.
    """
    result = subprocess.run(
        ["ping", "-n", "1", ip],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return result.returncode == 0

def monitor_devices(iterations=10, delay=10):
    """
    Monitor presence of laptop and iPhone for given iterations.
    Prints status every 'delay' seconds.
    """
    try:
        print("Starting device presence monitoring...")
        for i in range(iterations):
            nm = scan_network(subnet)
            laptop_status = "Present" if ping_ip(laptop_ip) else "Absent"
            iphone_status = "Present" if is_iphone_present(nm) else "Absent"
            timestamp = time.strftime("%d/%m/%Y %H:%M:%S")
            print(f"{timestamp}: Laptop is {laptop_status} | iPhone is {iphone_status}")
            time.sleep(delay)
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.")

if __name__ == "__main__":
    monitor_devices()
