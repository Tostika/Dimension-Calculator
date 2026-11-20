"""Talks to the ESP32 over USB serial (115200 baud), one text line per command:
  PING -> PONG        LED <0-100> -> OK        HOME -> OK HOME
  Z <mm> -> OK Z <mm> Z? -> Z <mm>           (Z = camera lens height above the base, in mm)
If no board is connected, a demo board answers so the app still works."""
import threading
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:          # pyserial not installed: demo board only
    serial = None


def list_ports():
    if serial is None:
        return []
    out = []
    for p in serial.tools.list_ports.comports():
        out.append((p.device, p.description or p.device))
    return out


class Esp32:
    def __init__(self):
        self._ser = None
        self._lock = threading.Lock()
        self.port = ""
        self.demo = True
        self.z_mm = 370.0
        self.led = 0

    @property
    def connected(self):
        return self._ser is not None

    def connect(self, port=None):
        """Opens `port`, or tries every port until one answers PONG. Returns True on success."""
        self.close()
        if serial is None:
            return False
        candidates = [port] if port else [p for p, _ in list_ports()]
        for dev in candidates:
            try:
                s = serial.Serial(dev, 115200, timeout=0.5, write_timeout=1)
                time.sleep(2.0)                       # opening the port resets the ESP32: wait for it to boot
                s.reset_input_buffer()
                s.write(b"PING\n")
                if s.readline().decode(errors="ignore").strip() == "PONG":
                    self._ser, self.port, self.demo = s, dev, False
                    return True
                s.close()
            except (serial.SerialException, OSError):
                continue
        return False

    def close(self):
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser, self.demo = None, True

    def _cmd(self, line, timeout=1.0, expect="OK"):
        if self._ser is None:
            return self._demo(line)
        with self._lock:
            self._ser.reset_input_buffer()
            self._ser.write((line + "\n").encode())
            t0 = time.time()
            while time.time() - t0 < timeout:
                reply = self._ser.readline().decode(errors="ignore").strip()
                if reply.startswith(expect) or reply.startswith("ERR"):
                    return reply
        return ""

    def _demo(self, line):
        parts = line.split()
        if parts[0] == "PING":
            return "PONG"
        if parts[0] == "LED":
            self.led = int(parts[1])
            return "OK"
        if parts[0] == "HOME":
            time.sleep(0.5)
            return "OK HOME"
        if parts[0] == "Z?":
            return f"Z {self.z_mm:.1f}"
        if parts[0] == "Z":
            time.sleep(min(2.0, abs(float(parts[1]) - self.z_mm) / 50.0))
            self.z_mm = float(parts[1])
            return f"OK Z {self.z_mm:.1f}"
        return "ERR"

    # ---------- commands ----------
    def set_led(self, percent):
        percent = max(0, min(100, int(percent)))
        self.led = percent
        return self._cmd(f"LED {percent}").startswith("OK")

    def home(self):
        return self._cmd("HOME", timeout=60.0, expect="OK HOME").startswith("OK")

    def move_to(self, z_mm):
        ok = self._cmd(f"Z {float(z_mm):.1f}", timeout=60.0, expect="OK Z").startswith("OK")
        if ok:
            self.z_mm = float(z_mm)
        return ok

    def get_z(self):
        reply = self._cmd("Z?", expect="Z ")
        try:
            return float(reply.split()[1])
        except (IndexError, ValueError):
            return None
