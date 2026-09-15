// efficiency_esp32.ino -- Buck-Boost 42 W (V1) efficiency sweep logger
//
// Daughter board: Adafruit ESP32 Feather (HUZZAH32), powered by the PCB's 5 V buck into
// its USB pin. Reads the four system INA226s with simultaneous triggered conversions,
// streams one CSV row per conversion (~0.29 s) over Serial, and appends ~1.2 s averages
// to flash (LittleFS) so a sweep is kept even with no laptop attached.
//
// Test: power-resistor load on the 12 V fan rail (2 x 8 ohm: series, single, parallel),
// bench supply ramped slowly 4.5 -> 21 V for each load.
//
// USB WARNING: the Feather USB pin is on the micro-USB VBUS net, so a normal cable ties the
// laptop's VBUS to the PCB's 5 V buck. While the PCB is powered, use a cable with VBUS (red)
// cut. Opening the Arduino IDE Serial Monitor resets the ESP32; efficiency_logger.py does not.
//
// Serial commands (newline-terminated):
//   help, info, header, dump, pause, resume, erase
//
// CSV columns: run, t_ms, n (samples averaged), flags, then per channel <name>_V (bus),
// <name>_uV (shunt), <name>_A (nominal shunt). All voltages are INA226 bus readings (no ESP32
// ADC). Recompute currents from *_uV with calibrated shunt values in analysis; the _A columns
// are for quick looks.

#include <Arduino.h>
#include <Wire.h>
#include <LittleFS.h>
#include <Preferences.h>

// --- PIN DEFINITIONS ---
const int I2C_SDA_PIN = 23;        // Feather ESP32 default SDA -- confirm against PCB schematic
const int I2C_SCL_PIN = 22;        // Feather ESP32 default SCL
const int STATUS_LED_PIN = 13;     // Feather red LED, toggles on each flash write; -1 to disable

// --- INA226 CHANNELS ---
#define MAX_CHANNELS 14

struct Channel {
  const char* name;
  uint8_t addr;
  float shuntOhms;   // nominal
  bool present;
};

Channel channels[MAX_CHANNELS] = {
  {"in",    0x40, 0.001, false},  // buck-boost input (bus = Vin)
  {"fan12", 0x41, 0.001, false},  // 12 V fan rail (power-resistor load for this test)
  {"b5in",  0x42, 0.033, false},  // 5 V buck input, 12 V side
  {"b5out", 0x43, 0.010, false},  // 5 V buck output -> Feather USB pin
  {"fan1",  0x44, 0.010, false},
  {"fan2",  0x45, 0.010, false},
  {"fan3",  0x46, 0.010, false},
  {"fan4",  0x47, 0.010, false},
  {"fan5",  0x48, 0.010, false},
  {"fan6",  0x49, 0.010, false},
  {"fan7",  0x4A, 0.010, false},
  {"fan8",  0x4B, 0.010, false},
  {"fan9",  0x4C, 0.010, false},
  {"fan10", 0x4D, 0.010, false},
};
// 4 = system rails only. Set 14 for fan-load tests (the CSV header changes: dump + erase first).
const int NUM_CHANNELS = 4;
const int CH_IN = 0, CH_FAN12 = 1, CH_B5IN = 2, CH_B5OUT = 3;

// --- INA226 REGISTERS & CONFIG ---
const uint8_t REG_CONFIG = 0x00;
const uint8_t REG_SHUNT = 0x01;    // signed, 2.5 uV/LSB
const uint8_t REG_BUS = 0x02;      // 1.25 mV/LSB
const uint8_t REG_MASK = 0x06;     // bit 3 = CVRF (conversion ready), cleared on read
const uint8_t REG_MFG_ID = 0xFE;   // reads 0x5449 ("TI")
const uint16_t CVRF_BIT = 0x0008;

// AVG code: 0=1 1=4 2=16 3=64 4=128 5=256 6=512 7=1024
// CT code:  0=140us 1=204us 2=332us 3=588us 4=1.1ms 5=2.116ms 6=4.156ms 7=8.244ms
const uint16_t AVG_COUNT[] = {1, 4, 16, 64, 128, 256, 512, 1024};
const uint16_t CT_US[] = {140, 204, 332, 588, 1100, 2116, 4156, 8244};
const uint8_t AVG_CODE = 4;        // 128 averages
const uint8_t CT_CODE = 4;         // 1.1 ms bus and shunt -> 128 x 2.2 ms = 282 ms per sample
// Mode 011 = shunt and bus, triggered: every write starts one conversion on all channels
// at once, so input and output powers cover the same time window.
const uint16_t CONFIG_TRIGGERED = 0x4000 | (AVG_CODE << 9) | (CT_CODE << 6) | (CT_CODE << 3) | 0b011;
const unsigned long CONVERSION_MS = (unsigned long)AVG_COUNT[AVG_CODE] * 2 * CT_US[CT_CODE] / 1000;

// --- LOGGING ---
const char* LOG_PATH = "/eff_log.csv";
const float LOG_MIN_VIN_V = 3.0;          // flash-log only while the input bus is live
const int FLASH_AVG_SAMPLES = 4;          // ~1.2 s per flash row
const size_t FLASH_RESERVE_BYTES = 16384; // stop logging before the filesystem is full
const unsigned long STATUS_PERIOD_MS = 2000;

// flags column (OR of all samples in the row)
const uint8_t FLAG_I2C_ERR = 0x01;     // a channel read failed; its fields are blank
const uint8_t FLAG_NOT_READY = 0x02;   // CVRF not seen before timeout; data may be one sample old
const uint8_t FLAG_SHUNT_CLIP = 0x04;  // shunt register at full scale (+/-81.9 mV)

// --- STATE VARIABLES ---
struct Row {
  unsigned long tMs;
  uint16_t n;
  uint8_t flags;
  float busV[MAX_CHANNELS];
  float shuntUV[MAX_CHANNELS];
  bool ok[MAX_CHANNELS];
};

struct Accum {
  double busV[MAX_CHANNELS];
  double shuntUV[MAX_CHANNELS];
  uint16_t nCh[MAX_CHANNELS];
  uint16_t n;
  uint8_t flags;
};

Preferences prefs;
Accum accum;
uint32_t runNumber = 0;       // 0 until the first sample with the input live
bool flashOk = false;
bool flashPaused = false;
bool flashFull = false;
bool ledState = false;
unsigned long lastStatusMs = 0;
String cmdBuf;

// --- HELPER FUNCTIONS ---
bool writeReg(uint8_t addr, uint8_t reg, uint16_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write((uint8_t)(val >> 8));
  Wire.write((uint8_t)(val & 0xFF));
  return Wire.endTransmission() == 0;
}

bool readReg(uint8_t addr, uint8_t reg, uint16_t &val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(addr, (uint8_t)2) != 2) return false;
  uint8_t msb = Wire.read();
  uint8_t lsb = Wire.read();
  val = ((uint16_t)msb << 8) | lsb;
  return true;
}

float currentA(const Row &r, int ch) {
  return r.shuntUV[ch] * 1e-6f / channels[ch].shuntOhms;
}

float powerW(const Row &r, int ch) {
  return r.busV[ch] * currentA(r, ch);
}

// Trigger all channels, wait for their conversions, then read the results.
void takeSample(Row &r) {
  r.tMs = millis();
  r.n = 1;
  r.flags = 0;

  bool ready[MAX_CHANNELS];
  int pending = 0;
  for (int i = 0; i < NUM_CHANNELS; i++) {
    ready[i] = true;
    if (channels[i].present) {
      if (writeReg(channels[i].addr, REG_CONFIG, CONFIG_TRIGGERED)) {
        ready[i] = false;
        pending++;
      }
    }
  }

  unsigned long t0 = millis();
  unsigned long timeoutMs = CONVERSION_MS * 3 / 2 + 50;
  // Always wait at least one conversion window so the loop is rate-limited even if no
  // INA226 answered.
  delay(CONVERSION_MS);
  while (pending > 0 && millis() - t0 < timeoutMs) {
    delay(2);
    for (int i = 0; i < NUM_CHANNELS; i++) {
      uint16_t mask;
      if (!ready[i] && readReg(channels[i].addr, REG_MASK, mask) && (mask & CVRF_BIT)) {
        ready[i] = true;
        pending--;
      }
    }
  }
  if (pending > 0) r.flags |= FLAG_NOT_READY;

  for (int i = 0; i < NUM_CHANNELS; i++) {
    r.ok[i] = false;
    if (!channels[i].present) continue;
    uint16_t shuntRaw, busRaw;
    if (readReg(channels[i].addr, REG_SHUNT, shuntRaw) && readReg(channels[i].addr, REG_BUS, busRaw)) {
      int16_t shuntSigned = (int16_t)shuntRaw;
      if (shuntSigned == 32767 || shuntSigned == -32768) r.flags |= FLAG_SHUNT_CLIP;
      r.shuntUV[i] = shuntSigned * 2.5f;
      r.busV[i] = busRaw * 1.25e-3f;
      r.ok[i] = true;
    } else {
      r.flags |= FLAG_I2C_ERR;
    }
  }
}

void resetAccum() {
  memset(&accum, 0, sizeof(accum));
}

void addToAccum(const Row &r) {
  for (int i = 0; i < NUM_CHANNELS; i++) {
    if (!r.ok[i]) continue;
    accum.busV[i] += r.busV[i];
    accum.shuntUV[i] += r.shuntUV[i];
    accum.nCh[i]++;
  }
  accum.n++;
  accum.flags |= r.flags;
}

void accumToRow(Row &r) {
  r.tMs = millis();
  r.n = accum.n;
  r.flags = accum.flags;
  for (int i = 0; i < NUM_CHANNELS; i++) {
    r.ok[i] = accum.nCh[i] > 0;
    if (r.ok[i]) {
      r.busV[i] = accum.busV[i] / accum.nCh[i];
      r.shuntUV[i] = accum.shuntUV[i] / accum.nCh[i];
    }
    if (channels[i].present && accum.nCh[i] < accum.n) r.flags |= FLAG_I2C_ERR;
  }
}

String csvHeader() {
  String h = "run,t_ms,n,flags";
  for (int i = 0; i < NUM_CHANNELS; i++) {
    h += ","; h += channels[i].name; h += "_V";
    h += ","; h += channels[i].name; h += "_uV";
    h += ","; h += channels[i].name; h += "_A";
  }
  return h;
}

String rowToCsv(const Row &r) {
  String s;
  s.reserve(64 + NUM_CHANNELS * 32);
  s += String(runNumber); s += ',';
  s += String(r.tMs); s += ',';
  s += String(r.n); s += ',';
  s += String(r.flags);
  for (int i = 0; i < NUM_CHANNELS; i++) {
    if (r.ok[i]) {
      s += ','; s += String(r.busV[i], 4);
      s += ','; s += String(r.shuntUV[i], 1);
      s += ','; s += String(currentA(r, i), 5);
    } else {
      s += ",,,";
    }
  }
  return s;
}

void flashAppend(const String &line) {
  if (!flashOk || flashPaused || flashFull) return;
  if (LittleFS.totalBytes() - LittleFS.usedBytes() < FLASH_RESERVE_BYTES) {
    flashFull = true;
    Serial.println("# FLASH FULL: flash logging stopped. dump, then erase.");
    return;
  }
  bool isNew = !LittleFS.exists(LOG_PATH);
  // Open/append/close per row: a power cut loses at most the row being written.
  File f = LittleFS.open(LOG_PATH, FILE_APPEND);
  if (!f) {
    Serial.println("# FLASH ERROR: could not open log file");
    return;
  }
  if (isNew) {
    f.print(csvHeader());
    f.print('\n');
  }
  f.print(line);
  f.print('\n');
  f.close();
  ledState = !ledState;
  if (STATUS_LED_PIN >= 0) digitalWrite(STATUS_LED_PIN, ledState ? HIGH : LOW);
}

void startRun() {
  runNumber = prefs.getUInt("run", 0) + 1;
  prefs.putUInt("run", runNumber);
  Serial.printf("# run %u started (input live)\n", runNumber);
}

void printStatus(const Row &r) {
  if (!(r.ok[CH_IN] && r.ok[CH_FAN12] && r.ok[CH_B5IN] && r.ok[CH_B5OUT])) {
    Serial.println("# status: a system channel is missing or failed to read");
    return;
  }
  float pIn = powerW(r, CH_IN);
  float pFan = powerW(r, CH_FAN12);
  float pB5in = powerW(r, CH_B5IN);
  float pB5out = powerW(r, CH_B5OUT);
  Serial.printf("# in %.3f V %.3f A %.2f W | fan12 %.3f V %.3f A %.2f W | 5V buck in %.3f W out %.3f W | "
                "eta_bb %.3f  fan/in %.3f  eta_5v %.3f | run %u flags 0x%02X\n",
                r.busV[CH_IN], currentA(r, CH_IN), pIn,
                r.busV[CH_FAN12], currentA(r, CH_FAN12), pFan,
                pB5in, pB5out,
                pIn > 0.05 ? (pFan + pB5in) / pIn : 0.0,
                pIn > 0.05 ? pFan / pIn : 0.0,
                pB5in > 0.01 ? pB5out / pB5in : 0.0,
                runNumber, r.flags);
}

void printInfo() {
  Serial.printf("# INA226: AVG %u, CT %u us, %lu ms per sample, triggered\n",
                AVG_COUNT[AVG_CODE], CT_US[CT_CODE], CONVERSION_MS);
  for (int i = 0; i < NUM_CHANNELS; i++) {
    Serial.printf("#   %-6s 0x%02X  %5.1f mOhm  %s\n", channels[i].name, channels[i].addr,
                  channels[i].shuntOhms * 1000.0, channels[i].present ? "OK" : "NOT FOUND");
  }
  if (flashOk) {
    size_t logBytes = 0;
    if (LittleFS.exists(LOG_PATH)) {
      File f = LittleFS.open(LOG_PATH, FILE_READ);
      logBytes = f.size();
      f.close();
    }
    Serial.printf("# flash: log %u bytes, fs used %u / %u bytes%s%s\n", logBytes,
                  LittleFS.usedBytes(), LittleFS.totalBytes(),
                  flashPaused ? ", PAUSED" : "", flashFull ? ", FULL" : "");
  } else {
    Serial.println("# flash: NOT MOUNTED (check partition scheme has a spiffs partition)");
  }
  Serial.printf("# run %u (next boot/run: %u)\n", runNumber, prefs.getUInt("run", 0) + 1);
}

void dumpLog() {
  flashPaused = true;
  if (!flashOk || !LittleFS.exists(LOG_PATH)) {
    Serial.println("#BEGIN_DUMP bytes=0");
    Serial.println("#END_DUMP");
    return;
  }
  File f = LittleFS.open(LOG_PATH, FILE_READ);
  Serial.printf("#BEGIN_DUMP bytes=%u\n", f.size());
  uint8_t buf[512];
  while (f.available()) {
    size_t n = f.read(buf, sizeof(buf));
    Serial.write(buf, n);
  }
  f.close();
  Serial.println("#END_DUMP");
  Serial.println("# flash logging paused; send 'resume' or reboot to log again");
}

void handleCommand(String cmd) {
  cmd.trim();
  cmd.toLowerCase();
  if (cmd == "help") {
    Serial.println("# commands: help, info, header, dump, pause, resume, erase");
  } else if (cmd == "info") {
    printInfo();
  } else if (cmd == "header") {
    Serial.println(csvHeader());
  } else if (cmd == "dump") {
    dumpLog();
  } else if (cmd == "pause") {
    flashPaused = true;
    Serial.println("# flash logging paused");
  } else if (cmd == "resume") {
    flashPaused = false;
    Serial.println("# flash logging resumed");
  } else if (cmd == "erase") {
    if (flashOk) LittleFS.remove(LOG_PATH);
    prefs.putUInt("run", 0);
    runNumber = 0;
    flashFull = false;
    resetAccum();
    Serial.println("# flash log erased, run counter reset");
  } else {
    Serial.printf("# unknown command '%s' (try help)\n", cmd.c_str());
  }
}

void pollSerialCommands() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdBuf.length() > 0) handleCommand(cmdBuf);
      cmdBuf = "";
    } else if (cmdBuf.length() < 32) {
      cmdBuf += c;
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n# ==== efficiency_esp32 boot ====");

  if (STATUS_LED_PIN >= 0) {
    pinMode(STATUS_LED_PIN, OUTPUT);
    digitalWrite(STATUS_LED_PIN, LOW);
  }

  prefs.begin("efflog", false);
  flashOk = LittleFS.begin(true);  // formats on first use
  resetAccum();

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, 100000);
  Wire.setTimeOut(50);

  Serial.print("# I2C scan:");
  for (uint8_t addr = 0x08; addr < 0x78; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) Serial.printf(" 0x%02X", addr);
  }
  Serial.println();

  for (int i = 0; i < NUM_CHANNELS; i++) {
    uint16_t id = 0;
    channels[i].present = readReg(channels[i].addr, REG_MFG_ID, id) && id == 0x5449;
  }
  printInfo();
  Serial.println("# commands: help, info, header, dump, pause, resume, erase");
  Serial.println(csvHeader());
}

void loop() {
  pollSerialCommands();

  Row r;
  takeSample(r);

  bool inputLive = r.ok[CH_IN] && r.busV[CH_IN] > LOG_MIN_VIN_V;
  if (inputLive && runNumber == 0) startRun();

  Serial.println(rowToCsv(r));

  if (inputLive) {
    addToAccum(r);
    if (accum.n >= FLASH_AVG_SAMPLES) {
      Row avg;
      accumToRow(avg);
      flashAppend(rowToCsv(avg));
      resetAccum();
    }
  } else {
    resetAccum();
  }

  if (millis() - lastStatusMs >= STATUS_PERIOD_MS) {
    lastStatusMs = millis();
    printStatus(r);
  }
}
