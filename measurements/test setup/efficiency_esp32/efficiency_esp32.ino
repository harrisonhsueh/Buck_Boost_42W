// efficiency_esp32.ino -- Buck-Boost 42 W (V1) efficiency sweep logger
//
// Daughter board: Adafruit ESP32 Feather (HUZZAH32), powered by the PCB's 5 V buck into
// its USB pin. Reads the INA226s with simultaneous triggered conversions, streams one CSV
// row per conversion (~0.29 s) over Serial, and appends ~1.2 s averages to flash (LittleFS)
// so a sweep is kept even with no laptop attached. Drives the 10 fan PWM lines at 25 kHz
// (all at one duty) and can ramp them slowly for fan-load sweeps.
//
// Tests: bench supply fixed (e.g. 5 / 9 / 15 / 20 V) with a slow fan PWM ramp, or bench
// supply ramped slowly with a fixed load (fans at fixed PWM, or power resistors).
//
// USB WARNING: the Feather USB pin is on the micro-USB VBUS net, so a normal cable ties the
// laptop's VBUS to the PCB's 5 V buck. While the PCB is powered, use a cable with VBUS (red)
// cut. Opening the Arduino IDE Serial Monitor resets the ESP32; efficiency_logger.py does not.
//
// Serial commands (newline-terminated):
//   help, info, header, dump, pause, resume, erase
//   ramp <seconds> [max_pct] [iin_limit_A]   0 -> max_pct over <seconds> (same slope back
//                                            down); turns around early if Iin > limit
//   pwm <pct>                                hold a fixed fan duty
//   stop                                     fans to 0 %
//
// CSV columns: run, t_ms, n (samples averaged), flags, pwm_pct, fan1..4_rpm (tach, median
// interval in the same window as the INA226 readings; 0 = too few edges), then per channel <name>_V
// (bus), <name>_uV (shunt), <name>_A (nominal shunt). All voltages are INA226 bus readings.
// Recompute currents from *_uV with calibrated shunt values in analysis; the _A columns are
// for quick looks. The flash log repeats the header at each boot.

#include <Arduino.h>
#include <Wire.h>
#include <LittleFS.h>
#include <Preferences.h>

// --- PIN DEFINITIONS ---
const int I2C_SDA_PIN = 23;        // Feather ESP32 default SDA -- confirm against PCB schematic
const int I2C_SCL_PIN = 22;        // Feather ESP32 default SCL
// Fan PWM labels 1..10 (all driven to the same duty). Assumes PWM label N and INA226 "fanN"
// (0x43 + N) are the same header. GPIO5 and GPIO15 are boot strapping pins; a fan pull-up
// holds them high, which matches their default strap state.
const int FAN_PWM_PINS[] = {13, 27, 33, 15, 32, 14, 26, 25, 4, 5};
const int NUM_FAN_PWM_PINS = sizeof(FAN_PWM_PINS) / sizeof(FAN_PWM_PINS[0]);
const bool FAN_PWM_INVERTED = false; // GPIO drives the fan PWM pins directly
const int TACH_PINS[] = {17, 16, 19, 18};  // tach for fans 1..4 (open-drain from the fan)
const int NUM_TACH = sizeof(TACH_PINS) / sizeof(TACH_PINS[0]);

// --- FAN PWM ---
const uint32_t FAN_PWM_FREQ_HZ = 25000;  // Intel 4-wire fan PWM frequency
const uint8_t FAN_PWM_BITS = 10;
const float RAMP_DEFAULT_S = 120.0;
const float RAMP_IIN_LIMIT_A = 3.0;      // default turn-around current (USB PD 3 A)

// --- FAN TACH ---
// Speed is the median tach edge-to-edge interval inside each INA226 conversion window, so it
// covers the same interval as the power readings. The median ignores the occasional extra
// (noise) or missed edge; the 2026-09-15 captures timed first-to-last edge and ~10-15 % of
// rows jumped >300 rpm. Flash writes happen between windows, so no interval spans one.
const float TACH_PULSES_PER_REV = 2.0;   // standard PC fan tach
const uint32_t TACH_MIN_EDGE_US = 2000;  // glitch filter: 2 ms = 15000 rpm at 2 pulses/rev
const int TACH_MAX_INTERVALS = 64;       // per window; 3000 rpm gives ~28 in 282 ms

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
  {"fan12", 0x41, 0.001, false},  // 12 V fan rail
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
// 14 = system rails + per-fan channels (fans not found at boot log blank columns).
// 4 = system rails only.
const int NUM_CHANNELS = 14;
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
  float pwmPct;
  float rpm[NUM_TACH];
  float busV[MAX_CHANNELS];
  float shuntUV[MAX_CHANNELS];
  bool ok[MAX_CHANNELS];
};

struct Accum {
  double pwmPct;
  double rpm[NUM_TACH];
  double busV[MAX_CHANNELS];
  double shuntUV[MAX_CHANNELS];
  uint16_t nCh[MAX_CHANNELS];
  uint16_t n;
  uint8_t flags;
};

enum FanMode { FAN_HOLD, FAN_RAMP_UP, FAN_RAMP_DOWN };

Preferences prefs;
Accum accum;
uint32_t runNumber = 0;       // 0 until the first sample with the input live
bool flashOk = false;
bool flashPaused = false;
bool flashFull = false;
bool headerWrittenThisBoot = false;
unsigned long lastStatusMs = 0;
String cmdBuf;

FanMode fanMode = FAN_HOLD;
float fanPct = 0.0;
float rampSlopePctPerS = 0.0;
float rampMaxPct = 100.0;
float rampIinLimitA = RAMP_IIN_LIMIT_A;
unsigned long lastFanUpdateMs = 0;
float lastIinA = 0.0;
bool lastIinOk = false;

struct TachState {
  uint32_t prevUs;                          // last accepted edge
  bool havePrev;                            // an edge has been accepted in this window
  uint8_t count;                            // intervals stored in this window
  uint32_t intervalUs[TACH_MAX_INTERVALS];
};
TachState tach[NUM_TACH];
portMUX_TYPE tachMux = portMUX_INITIALIZER_UNLOCKED;

// --- HELPER FUNCTIONS ---
void IRAM_ATTR onTachEdge(void *arg) {
  TachState &s = tach[(intptr_t)arg];
  uint32_t now = (uint32_t)esp_timer_get_time();
  portENTER_CRITICAL_ISR(&tachMux);
  if (!s.havePrev) {
    s.prevUs = now;
    s.havePrev = true;
  } else if (now - s.prevUs >= TACH_MIN_EDGE_US) {
    if (s.count < TACH_MAX_INTERVALS) s.intervalUs[s.count++] = now - s.prevUs;
    s.prevUs = now;
  }
  portEXIT_CRITICAL_ISR(&tachMux);
}

void tachStartWindow() {
  portENTER_CRITICAL(&tachMux);
  for (int k = 0; k < NUM_TACH; k++) {
    tach[k].havePrev = false;
    tach[k].count = 0;
  }
  portEXIT_CRITICAL(&tachMux);
}

// rpm from the median edge interval in the window; 0 if fewer than 2 intervals (below ~200 rpm)
void tachEndWindow(Row &r) {
  static TachState snap[NUM_TACH];  // static: keeps ~1 kB of intervals off the loop stack
  portENTER_CRITICAL(&tachMux);
  for (int k = 0; k < NUM_TACH; k++) snap[k] = tach[k];
  portEXIT_CRITICAL(&tachMux);
  for (int k = 0; k < NUM_TACH; k++) {
    int n = snap[k].count;
    uint32_t *v = snap[k].intervalUs;
    for (int i = 1; i < n; i++) {  // insertion sort, n <= 64
      uint32_t x = v[i];
      int j = i - 1;
      while (j >= 0 && v[j] > x) {
        v[j + 1] = v[j];
        j--;
      }
      v[j + 1] = x;
    }
    r.rpm[k] = 0.0f;
    if (n >= 2) {
      float medianUs = (n % 2) ? v[n / 2] : 0.5f * ((float)v[n / 2 - 1] + v[n / 2]);
      r.rpm[k] = 60.0e6f / (TACH_PULSES_PER_REV * medianUs);
    }
  }
}

void setFanPct(float pct) {
  fanPct = constrain(pct, 0.0f, 100.0f);
  uint32_t maxDuty = (1UL << FAN_PWM_BITS) - 1;  // ledcWrite treats maxDuty as fully on
  uint32_t duty = (uint32_t)lround(fanPct / 100.0f * maxDuty);
  if (FAN_PWM_INVERTED) duty = maxDuty - duty;
  for (int i = 0; i < NUM_FAN_PWM_PINS; i++) ledcWrite(FAN_PWM_PINS[i], duty);
}

// Called once per sample, before the conversion, so pwm_pct is constant within each row.
void updateFanRamp() {
  unsigned long now = millis();
  float dt = (now - lastFanUpdateMs) / 1000.0f;
  lastFanUpdateMs = now;

  if (fanMode == FAN_RAMP_UP) {
    if (lastIinOk && lastIinA > rampIinLimitA) {
      Serial.printf("# ramp: Iin %.2f A > %.2f A limit at %.1f %%, ramping down\n",
                    lastIinA, rampIinLimitA, fanPct);
      fanMode = FAN_RAMP_DOWN;
      return;
    }
    float next = fanPct + rampSlopePctPerS * dt;
    if (next >= rampMaxPct) {
      setFanPct(rampMaxPct);
      fanMode = FAN_RAMP_DOWN;
      Serial.printf("# ramp: reached %.1f %%, ramping down\n", rampMaxPct);
    } else {
      setFanPct(next);
    }
  } else if (fanMode == FAN_RAMP_DOWN) {
    float next = fanPct - rampSlopePctPerS * dt;
    if (next <= 0.0f) {
      setFanPct(0.0);
      fanMode = FAN_HOLD;
      Serial.println("# ramp: done, fans at 0 %");
    } else {
      setFanPct(next);
    }
  }
}

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
  r.pwmPct = fanPct;

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
  tachStartWindow();

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
  tachEndWindow(r);
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
  accum.pwmPct += r.pwmPct;
  for (int k = 0; k < NUM_TACH; k++) accum.rpm[k] += r.rpm[k];
  accum.n++;
  accum.flags |= r.flags;
}

void accumToRow(Row &r) {
  r.tMs = millis();
  r.n = accum.n;
  r.flags = accum.flags;
  r.pwmPct = accum.n > 0 ? accum.pwmPct / accum.n : 0.0;
  for (int k = 0; k < NUM_TACH; k++) r.rpm[k] = accum.n > 0 ? accum.rpm[k] / accum.n : 0.0;
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
  String h = "run,t_ms,n,flags,pwm_pct";
  for (int k = 0; k < NUM_TACH; k++) {
    h += ",fan"; h += String(k + 1); h += "_rpm";
  }
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
  s += String(r.flags); s += ',';
  s += String(r.pwmPct, 2);
  for (int k = 0; k < NUM_TACH; k++) {
    s += ','; s += String(r.rpm[k], 1);
  }
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
  // Open/append/close per row: a power cut loses at most the row being written.
  File f = LittleFS.open(LOG_PATH, FILE_APPEND);
  if (!f) {
    Serial.println("# FLASH ERROR: could not open log file");
    return;
  }
  if (!headerWrittenThisBoot) {  // a header per boot, so a column change never corrupts the log
    f.print(csvHeader());
    f.print('\n');
    headerWrittenThisBoot = true;
  }
  f.print(line);
  f.print('\n');
  f.close();
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
  Serial.printf("# rpm");
  for (int k = 0; k < NUM_TACH; k++) Serial.printf(" %.0f", r.rpm[k]);
  Serial.printf(" | pwm %.1f %% | in %.3f V %.3f A %.2f W | fan12 %.3f V %.3f A %.2f W | 5V buck in %.3f W out %.3f W | "
                "eta_bb %.3f  fan/in %.3f  eta_5v %.3f | run %u flags 0x%02X\n",
                r.pwmPct,
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
  Serial.printf("# fan PWM: GPIO");
  for (int i = 0; i < NUM_FAN_PWM_PINS; i++) Serial.printf(" %d", FAN_PWM_PINS[i]);
  Serial.printf(", %lu Hz%s, now %.1f %%\n", (unsigned long)FAN_PWM_FREQ_HZ,
                FAN_PWM_INVERTED ? ", inverted" : "", fanPct);
  Serial.printf("# fan tach (fans 1..%d): GPIO", NUM_TACH);
  for (int k = 0; k < NUM_TACH; k++) Serial.printf(" %d", TACH_PINS[k]);
  Serial.printf(", %.0f pulses/rev\n", TACH_PULSES_PER_REV);
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

void printHelp() {
  Serial.println("# commands: help, info, header, dump, pause, resume, erase,");
  Serial.println("#   ramp <seconds> [max_pct] [iin_limit_A], pwm <pct>, stop");
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
  float a = 0.0, b = 0.0, c = 0.0;
  if (cmd == "help") {
    printHelp();
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
    headerWrittenThisBoot = false;
    resetAccum();
    Serial.println("# flash log erased, run counter reset");
  } else if (cmd == "stop") {
    fanMode = FAN_HOLD;
    setFanPct(0.0);
    Serial.println("# fans stopped (0 %)");
  } else if (sscanf(cmd.c_str(), "pwm %f", &a) == 1) {
    fanMode = FAN_HOLD;
    setFanPct(a);
    Serial.printf("# fans held at %.1f %%\n", fanPct);
  } else if (cmd.startsWith("ramp")) {
    int got = sscanf(cmd.c_str(), "ramp %f %f %f", &a, &b, &c);
    float seconds = got >= 1 ? a : RAMP_DEFAULT_S;
    float maxPct = got >= 2 ? b : 100.0;
    float limitA = got >= 3 ? c : RAMP_IIN_LIMIT_A;
    if (!channels[CH_IN].present) {
      Serial.println("# ramp refused: input INA226 not found, so the Iin limit cannot work");
    } else if (seconds < 1.0 || maxPct <= 0.0) {
      Serial.println("# ramp refused: need seconds >= 1 and max_pct > 0");
    } else {
      rampMaxPct = constrain(maxPct, 0.0f, 100.0f);
      rampSlopePctPerS = 100.0 / seconds;
      rampIinLimitA = limitA;
      lastFanUpdateMs = millis();
      fanMode = FAN_RAMP_UP;
      Serial.printf("# ramp: %.1f -> %.1f %% at %.3f %%/s (100 %% per %.0f s), Iin limit %.2f A\n",
                    fanPct, rampMaxPct, rampSlopePctPerS, seconds, rampIinLimitA);
    }
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
    } else if (cmdBuf.length() < 40) {
      cmdBuf += c;
    }
  }
}

void setup() {
  // Fan PWM first. From reset until this runs the pin is an undriven input, and a 4-wire
  // fan's own pull-up reads that as full speed; firmware can shorten that window, not remove it.
  bool pwmAttachOk[NUM_FAN_PWM_PINS];
  for (int i = 0; i < NUM_FAN_PWM_PINS; i++) {
    pwmAttachOk[i] = ledcAttach(FAN_PWM_PINS[i], FAN_PWM_FREQ_HZ, FAN_PWM_BITS);
  }
  setFanPct(0.0);

  // Internal pull-ups (~45 k) as a fallback; fine alongside a board pull-up to 3.3 V.
  for (int k = 0; k < NUM_TACH; k++) {
    pinMode(TACH_PINS[k], INPUT_PULLUP);
    attachInterruptArg(digitalPinToInterrupt(TACH_PINS[k]), onTachEdge, (void *)(intptr_t)k, FALLING);
  }

  Serial.begin(115200);
  delay(200);
  Serial.println("\n# ==== efficiency_esp32 boot ====");
  for (int i = 0; i < NUM_FAN_PWM_PINS; i++) {
    if (!pwmAttachOk[i]) Serial.printf("# FAN PWM ERROR: GPIO %d (fan %d) did not attach; that fan is undriven (full speed)\n",
                                       FAN_PWM_PINS[i], i + 1);
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
  printHelp();
  Serial.println(csvHeader());
}

void loop() {
  pollSerialCommands();
  updateFanRamp();

  Row r;
  takeSample(r);
  lastIinOk = r.ok[CH_IN];
  if (lastIinOk) lastIinA = currentA(r, CH_IN);

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
