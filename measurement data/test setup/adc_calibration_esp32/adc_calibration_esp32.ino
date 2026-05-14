#include <Arduino.h>

// --- HARDWARE CONFIG ---
const int CAL_PIN = 32;
const float DIVIDER_RATIO = 5.0; // 40k/10k divider

// --- CALIBRATION DATA ---
// Update these two arrays with your manual measurements.
// They MUST be the same length and in ascending order.
//float actualVolts[] = { 0.0, 0.5, 1.1, 1.5, 2.0, 2.5, 3.0, 3.3 };
//int rawADCValues[]  = { 120, 640, 1380, 1890, 2520, 3150, 3850, 4095 };
float actualVolts[] = { 0, 0.06, 0.078, 0.1, 0.12, 0.126, 0.13, 0.132, 0.135, 0.14, 0.145, 0.15, 0.16, 0.18, 0.2, 0.5, 1.004, 2.007, 2.516, 2.60, 2.711, 2.801, 2.902, 3.001, 3.11, 3.15, 3.165, 3.172, 3.189, 3.208, 3.232};
float rawADCValues[]  = { 0, 0.01, 0.05, 0.2, 0.480, 0.70, 1.6, 2.7, 6.7, 13.6, 17.5, 22.9, 36.9, 60.6, 83, 444.1, 1060.1, 2304.8, 2925.2, 3039.9, 3211.7, 3364.8, 3567, 3727.1, 3968, 4070.1, 4093.4, 4094.5, 4094.8, 4094.99, 4095};
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
  const int samples = 102800;
  for(int i = 0; i < samples; i++) {
    sum += analogRead(CAL_PIN);
  }
  float rawAverage = (float) sum / samples;

  // Calculate using standard linear math (idealized)
  float idealPinVolts = (rawAverage * 3.3) / 4095.0;

  // Calculate using your custom Lookup Table (Interpolated)
  float calPinVolts = getCalibratedVoltage(rawAverage);
  float calSourceVolts = calPinVolts * DIVIDER_RATIO;

  // Output to Serial
  Serial.print("RAW: ");
  Serial.print(rawAverage,3);
  
  Serial.print(" | Ideal Pin V: ");
  Serial.print(idealPinVolts, 3);
  
  Serial.print(" | CALIBRATED Pin V: ");
  Serial.print(calPinVolts, 3);
  
  Serial.print(" | CALIBRATED Source V: ");
  Serial.print(calSourceVolts, 2);
  Serial.println("V");

  delay(800); // Slower update for easier reading
}
