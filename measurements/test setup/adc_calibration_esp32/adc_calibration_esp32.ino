#include <Arduino.h>

// --- HARDWARE CONFIG ---
const int CAL_PIN = 32;
const float DIVIDER_RATIO = 5.0; // 40k/10k divider

// --- CALIBRATION DATA ---
// Update these two arrays with your manual measurements.
// They MUST be the same length and in ascending order.
float actualVolts[] = { 0.0, 0.5, 1.1, 1.5, 2.0, 2.5, 3.0, 3.3 };
int rawADCValues[]  = { 120, 640, 1380, 1890, 2520, 3150, 3850, 4095 };
const int NUM_POINTS = sizeof(actualVolts) / sizeof(actualVolts[0]);

// --- LINEAR INTERPOLATION FUNCTION ---
float getCalibratedVoltage(int raw) {
  if (raw <= rawADCValues[0]) return actualVolts[0];
  if (raw >= rawADCValues[NUM_POINTS - 1]) return actualVolts[NUM_POINTS - 1];

  for (int i = 0; i < NUM_POINTS - 1; i++) {
    if (raw >= rawADCValues[i] && raw <= rawADCValues[i+1]) {
      // Linear Interpolation formula
      return actualVolts[i] + (float)(raw - rawADCValues[i]) * 
             (actualVolts[i+1] - actualVolts[i]) / 
             (rawADCValues[i+1] - rawADCValues[i]);
    }
  }
  return 0.0;
}

void setup() {
  Serial.begin(115200);
  
  // Set 11dB attenuation for 0-3.3V range
  analogSetAttenuation(ADC_11db);
  pinMode(CAL_PIN, INPUT);

  Serial.println("\n==============================================");
  Serial.println("ESP32 ADC LIVE CALIBRATION TOOL");
  Serial.println("1. Apply known voltage to GPIO 32");
  Serial.println("2. Note 'Raw' value to update your arrays");
  Serial.println("3. Compare 'Source V' to your Multimeter");
  Serial.println("==============================================\n");
}

void loop() {
  // Average readings for stability
  long sum = 0;
  const int samples = 64;
  for(int i = 0; i < samples; i++) {
    sum += analogRead(CAL_PIN);
  }
  int rawAverage = sum / samples;

  // Calculate using standard linear math (idealized)
  float idealPinVolts = (rawAverage * 3.3) / 4095.0;

  // Calculate using your custom Lookup Table (Interpolated)
  float calPinVolts = getCalibratedVoltage(rawAverage);
  float calSourceVolts = calPinVolts * DIVIDER_RATIO;

  // Output to Serial
  Serial.print("RAW: ");
  Serial.print(rawAverage);
  
  Serial.print(" | Ideal Pin V: ");
  Serial.print(idealPinVolts, 3);
  
  Serial.print(" | CALIBRATED Pin V: ");
  Serial.print(calPinVolts, 3);
  
  Serial.print(" | CALIBRATED Source V: ");
  Serial.print(calSourceVolts, 2);
  Serial.println("V");

  delay(800); // Slower update for easier reading
}
