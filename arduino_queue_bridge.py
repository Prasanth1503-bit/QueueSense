"""
QueueSense USB serial bridge — sole owner of the Arduino COM port.

Confirmed serial protocol (from QueueSense_RFID.ino, baud 9600):

  Arduino -> Python
  -----------------
  QUEUESENSE_READY                               startup confirmation
  RFID,<uid>,<roll>,<name>,ENTRY                 known card, person entering
  RFID,<uid>,<roll>,<name>,EXIT                  known card, person exiting
  RFID,<uid>,,Unknown,UNKNOWN                    unknown card (roll field empty)

  Python -> Arduino
  -----------------
  BUZZER,ON    activates buzzer + LCD "QUEUE LIMIT ALERT / Please wait..."
  BUZZER,OFF   silences buzzer + LCD resets to "QueueSense RFID / Scan your card"

Notes:
- Arduino debounces 1500 ms per UID.
- Inside/outside state is held in Arduino RAM and resets on power loss;
  SQLite attendance history is always persistent.
- beep() is suppressed while the queue alarm is active so the buzzer
  stays ON continuously until BUZZER,OFF is received.
"""

import os
import threading
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None

from database import save_attendance_event, get_queue_alert_limits, update_hardware_status


class ArduinoQueueBridge:
    """Manages one background thread that owns the Arduino USB serial port."""

    def __init__(self, port=None, baudrate=9600):
        # Port: explicit argument > env var > auto-detect
        self.port_name = (
            port
            or os.getenv("QUEUESENSE_ARDUINO_PORT", "").strip()
            or None
        )
        self.baudrate = baudrate
        self.serial = None
        self.thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.connected = False
        self.arduino_ready = False   # True after QUEUESENSE_READY received
        self.last_error = None
        self.alert_active = False

    # ------------------------------------------------------------------ start
    def start(self):
        """Start the background serial thread. Safe to call more than once."""
        if serial is None:
            self.last_error = "pyserial is not installed"
            return
        if self.thread and self.thread.is_alive():
            return   # already running — do not create a second thread
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    # --------------------------------------------------------------- _connect
    def _connect(self):
        """Try to open the serial port. Return True on success."""
        candidates = (
            [self.port_name]
            if self.port_name
            else [p.device for p in list_ports.comports()]
        )
        for port in candidates:
            try:
                self.serial = serial.Serial(
                    port, self.baudrate, timeout=1, write_timeout=1
                )
                self.port_name = port
                # Arduino resets on serial open; wait for it to boot.
                time.sleep(2)
                self.connected = True
                self.arduino_ready = False   # reset until QUEUESENSE_READY arrives
                self.last_error = None
                print("[Arduino] Connected on", port)
                return True
            except Exception as exc:
                self.last_error = str(exc)
        self.connected = False
        return False

    # ------------------------------------------------------------------ _send
    def _send(self, line):
        """Send one line to the Arduino. Thread-safe. Returns True on success."""
        with self.lock:
            if self.serial and self.serial.is_open:
                try:
                    self.serial.write((line.strip() + "\n").encode("utf-8"))
                    self.serial.flush()
                    return True
                except Exception as exc:
                    self.last_error = str(exc)
        return False

    def _sync_cloud_status(self):
        """Asynchronously sync hardware status to Supabase for cloud dashboards."""
        try:
            update_hardware_status(self.status())
        except Exception:
            pass

    # -------------------------------------------------------------- set_buzzer
    def set_buzzer(self, active):
        """Send BUZZER,ON or BUZZER,OFF only when the state actually changes."""
        active = bool(active)
        if active != self.alert_active:
            self.alert_active = active
            cmd = "BUZZER,ON" if active else "BUZZER,OFF"
            self._send(cmd)
            print("[Arduino] Sent:", cmd)
            self._sync_cloud_status()

    # --------------------------------------------------- update_hardware_alerts
    def update_hardware_alerts(self, statistics):
        """
        Called with the current queue occupancy dict.
        Turns the buzzer ON when any queue EXCEEDS its saved limit,
        OFF only when every queue is AT or BELOW its limit.
        Supports case-insensitive and partial matching (e.g. 'student' matches 'Student Queue').
        Unknown queues default to limit 5.
        """
        try:
            limits = get_queue_alert_limits()
        except Exception as exc:
            self.last_error = str(exc)
            return

        lower_limits = {str(k).strip().lower(): v for k, v in limits.items()}

        active = False
        for name, v in statistics.items():
            occ = int(v.get("occupancy", 0) or 0)
            clean = str(name).strip().lower()

            limit_info = limits.get(name) or lower_limits.get(clean)
            if not limit_info:
                for lk, lv in lower_limits.items():
                    if clean in lk or lk in clean:
                        limit_info = lv
                        break

            limit_val = int(limit_info.get("limit_people", 5)) if limit_info else 5
            if occ > limit_val:
                active = True
                break

        self.set_buzzer(active)

    # ------------------------------------------------------------- _handle_line
    def _handle_line(self, line):
        """
        Parse one line received from the Arduino.

        Handled message types (from QueueSense_RFID.ino):

          QUEUESENSE_READY
          RFID,<uid>,<roll>,<name>,ENTRY|EXIT|UNKNOWN

        The unknown-card message has an empty roll field:
          RFID,07b8bf26,,Unknown,UNKNOWN
        split(",", 4) correctly produces ["RFID","07b8bf26","","Unknown","UNKNOWN"].
        """
        stripped = line.strip()
        if not stripped:
            return

        # ---- Startup confirmation ----------------------------------------
        if stripped == "QUEUESENSE_READY":
            self.arduino_ready = True
            print("[Arduino] QueueSense firmware ready.")
            return

        # ---- RFID attendance event ---------------------------------------
        parts = stripped.split(",", 4)
        if len(parts) >= 5 and parts[0].upper() == "RFID":
            _, uid, roll, name, event = parts
            try:
                save_attendance_event(uid, roll, name, event)
                print("[RFID]", name, "(" + roll + ")" if roll else "(unknown card)",
                      event)
            except Exception as exc:
                self.last_error = str(exc)
                print("[RFID database error]", exc)
            return

        # ---- Any other line: log and ignore ------------------------------
        print("[Arduino] Ignored:", stripped)

    def _run(self):
        """Background thread: connect, read lines, reconnect on error."""
        last_heartbeat = 0
        while not self.stop_event.is_set():
            now_t = time.monotonic()
            if now_t - last_heartbeat >= 3.0:
                last_heartbeat = now_t
                self._sync_cloud_status()

            if not self.serial or not self.serial.is_open:
                self.connected = False
                self.arduino_ready = False
                if not self._connect():
                    self.stop_event.wait(3)
                    continue
                else:
                    self._sync_cloud_status()
            try:
                raw = self.serial.readline()
                if raw:
                    self._handle_line(raw.decode("utf-8", errors="replace"))
                self.connected = bool(self.serial and self.serial.is_open)
            except Exception as exc:
                self.last_error = str(exc)
                self.connected = False
                self.arduino_ready = False
                try:
                    self.serial.close()
                except Exception:
                    pass
                self.serial = None
                self._sync_cloud_status()
                self.stop_event.wait(2)
        self.close()

    # ------------------------------------------------------------------ status
    def status(self):
        return {
            "connected": self.connected,
            "arduino_ready": self.arduino_ready,
            "port": self.port_name,
            "last_error": self.last_error,
            "alert_active": self.alert_active,
        }

    # ------------------------------------------------------------------- close
    def close(self):
        self.stop_event.set()
        try:
            self.set_buzzer(False)   # turn buzzer off before disconnecting
        except Exception:
            pass
        try:
            if self.serial:
                self.serial.close()
        except Exception:
            pass
        self.serial = None
        self.connected = False
        self.arduino_ready = False
        self._sync_cloud_status()


bridge = ArduinoQueueBridge()
