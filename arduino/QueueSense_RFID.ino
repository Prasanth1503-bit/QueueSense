/*
 * QueueSense – Smart Queue Intelligence System
 * Arduino Uno Firmware: RFID Attendance & Hardware Queue Alarm
 *
 * Hardware Wiring:
 * ----------------
 * RC522 RFID Reader:
 *   - VCC    -> 3.3V (Do NOT connect to 5V!)
 *   - RST    -> Pin 9
 *   - GND    -> GND
 *   - MISO   -> Pin 12
 *   - MOSI   -> Pin 11
 *   - SCK    -> Pin 13
 *   - SDA/SS -> Pin 10
 *
 * I2C 16x2 LCD (PCF8574):
 *   - VCC    -> 5V
 *   - GND    -> GND
 *   - SDA    -> A4 (or dedicated SDA pin)
 *   - SCL    -> A5 (or dedicated SCL pin)
 *   * Note: Default I2C address is 0x27 (or 0x3F). If blank, adjust the contrast trimmer potentiometer.
 *
 * Actuators & Indicators:
 *   - Buzzer (+) -> Pin 2 (Active buzzer, GND to Arduino GND)
 *   - LED (+)    -> Pin 3 (through 220-330 ohm resistor to GND)
 *
 * Serial Protocol (9600 Baud):
 * ----------------------------
 * Arduino -> Python:
 *   QUEUESENSE_READY
 *   RFID,<card_uid>,<roll_number>,<student_name>,ENTRY
 *   RFID,<card_uid>,<roll_number>,<student_name>,EXIT
 *   RFID,<card_uid>,,Unknown,UNKNOWN
 *
 * Python -> Arduino:
 *   BUZZER,ON   (Queue limit exceeded -> continuous buzzer + LCD alert)
 *   BUZZER,OFF  (All queues normal -> buzzer off + LCD idle screen)
 */

#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

#define SS_PIN 10
#define RST_PIN 9
#define BUZZER_PIN 2
#define LED_PIN 3

MFRC522 rfid(SS_PIN, RST_PIN);
LiquidCrystal_I2C lcd(0x27, 16, 2); // If blank, verify address (often 0x3F) and contrast trimmer.

struct Student {
  const char* uid;
  const char* roll;
  const char* name;
  bool inside;
};

Student students[] = {
  {"7b8bf206", "24BCE8221", "G.Prasanth Paul", false},
  {"c1a9f868", "24BCE8253", "G.Prem Sasank", false},
  {"d1157768", "24BCA7344", "T.Mani Sankar", false},
  {"c1784968", "24BCE8263", "D.Dinesh", false},
  {"c189f968", "24BCA7285", "Pardha", false},
  {"d1b3d568", "24BES7016", "G.Aditya", false}
};
const int STUDENT_COUNT = sizeof(students) / sizeof(students[0]);

bool queueAlarm = false;
unsigned long lastCardMs = 0;
String lastUID = "";

String uidString() {
  String s = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) s += "0";
    s += String(rfid.uid.uidByte[i], HEX);
  }
  s.toLowerCase();
  return s;
}

void beep(unsigned int ms) {
  if (!queueAlarm) {
    digitalWrite(BUZZER_PIN, HIGH);
    delay(ms);
    digitalWrite(BUZZER_PIN, LOW);
  }
}

void setAlarm(bool on) {
  queueAlarm = on;
  digitalWrite(BUZZER_PIN, on ? HIGH : LOW);
  if (on) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("QUEUE LIMIT ALERT");
    lcd.setCursor(0, 1);
    lcd.print("Please wait...");
  }
}

void setup() {
  Serial.begin(9600);
  SPI.begin();
  rfid.PCD_Init();
  Wire.begin();
  lcd.init();
  lcd.backlight();

  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(LED_PIN, LOW);

  lcd.setCursor(0, 0);
  lcd.print("QueueSense RFID");
  lcd.setCursor(0, 1);
  lcd.print("Scan your card");

  Serial.println("QUEUESENSE_READY");
}

void loop() {
  // 1. Process incoming commands from Python (Flask QueueSense bridge)
  while (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "BUZZER,ON") {
      setAlarm(true);
    } else if (cmd == "BUZZER,OFF") {
      setAlarm(false);
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("QueueSense RFID");
      lcd.setCursor(0, 1);
      lcd.print("Scan your card");
    }
  }

  // 2. Check for RFID card presence
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) {
    return;
  }

  String uid = uidString();
  unsigned long now = millis();

  // 1500 ms debounce for the same card
  if (uid == lastUID && (now - lastCardMs < 1500)) {
    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
    return;
  }
  lastUID = uid;
  lastCardMs = now;

  // 3. Search student in registered list
  int found = -1;
  for (int i = 0; i < STUDENT_COUNT; i++) {
    String expected = students[i].uid;
    expected.toLowerCase();
    if (uid == expected) {
      found = i;
      break;
    }
  }

  digitalWrite(LED_PIN, HIGH);

  if (found >= 0) {
    Student &s = students[found];
    s.inside = !s.inside; // Toggle ENTRY / EXIT state
    const char* event = s.inside ? "ENTRY" : "EXIT";

    // Transmit CSV line over Serial to Python
    Serial.print("RFID,");
    Serial.print(uid);
    Serial.print(',');
    Serial.print(s.roll);
    Serial.print(',');
    Serial.print(s.name);
    Serial.print(',');
    Serial.println(event);

    // Display on LCD
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print(s.name);
    lcd.setCursor(0, 1);
    lcd.print(s.roll);
    lcd.print(s.inside ? " IN" : " OUT");

    beep(120);
  } else {
    // Unregistered card
    Serial.print("RFID,");
    Serial.print(uid);
    Serial.println(",,Unknown,UNKNOWN");

    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Unknown card");
    lcd.setCursor(0, 1);
    lcd.print(uid.substring(0, 16));

    beep(500);
  }

  digitalWrite(LED_PIN, LOW);
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}
