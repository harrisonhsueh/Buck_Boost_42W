#include <Arduino.h>

// --- PIN DEFINITIONS ---
const int SWITCH_PIN = 27;        
const int GATE_DRIVE_PIN = 21;    
const int VOLTAGE_SENSE_PIN = 32; 
const int STATUS_LED_PIN = 13;    

// --- CALIBRATION & MATH ---
const float DIVIDER_RATIO = 5.0; 
const float TARGET_SOURCE_VOLTAGE = 6; 

// Replace with your measured values
float actualVolts[] = { 0, 0.06, 0.078, 0.1, 0.12, 0.126, 0.13, 0.132, 0.135, 0.14, 0.145, 0.15, 0.16, 0.18, 0.2, 0.5, 1.004, 2.007, 2.516, 2.60, 2.711, 2.801, 2.902, 3.001, 3.11, 3.15, 3.165, 3.172, 3.189, 3.208, 3.232};
float rawADCValues[]  = { 0, 0.01, 0.05, 0.2, 0.480, 0.70, 1.6, 2.7, 6.7, 13.6, 17.5, 22.9, 36.9, 60.6, 83, 444.1, 1060.1, 2304.8, 2925.2, 3039.9, 3211.7, 3364.8, 3567, 3727.1, 3968, 4070.1, 4093.4, 4094.5, 4094.8, 4094.99, 4095};
const int NUM_POINTS = sizeof(actualVolts) / sizeof(actualVolts[0]);

// --- STATE VARIABLES ---
bool systemOn = false;        // Always boot to OFF
bool pulseArmed = false;      // Arms only after system was ON
int lastPhysicalState;        // Stores the state the switch was in at boot or last loop
unsigned long lastDebounceTime = 0;
const unsigned long debounceDelay = 50; 

// --- HELPER FUNCTIONS ---
float getCalibratedVoltage(int raw) {
  if (raw <= rawADCValues[0]) return actualVolts[0];
  if (raw >= rawADCValues[NUM_POINTS - 1]) return actualVolts[NUM_POINTS - 1];
  for (int i = 0; i < NUM_POINTS - 1; i++) {
    if (raw >= rawADCValues[i] && raw <= rawADCValues[i+1]) {
      return actualVolts[i] + (float)(raw - rawADCValues[i]) * 
             (actualVolts[i+1] - actualVolts[i]) / 
             (rawADCValues[i+1] - rawADCValues[i]);
    }
  }
  return 0.0;
}

void applySystemState() {
  if (systemOn) {
    digitalWrite(GATE_DRIVE_PIN, HIGH);
    digitalWrite(STATUS_LED_PIN, LOW);
    pulseArmed = true; // Arm the trigger when we go high
    Serial.println("Action: System turned ON");
  } else {
    digitalWrite(GATE_DRIVE_PIN, LOW);
    digitalWrite(STATUS_LED_PIN, HIGH);
    Serial.println("Action: System turned OFF (Pulse Monitoring Active)");
  }
}

void setup() {
  Serial.begin(115200);
  analogSetAttenuation(ADC_11db);

  pinMode(SWITCH_PIN, INPUT_PULLUP);
  pinMode(GATE_DRIVE_PIN, OUTPUT);
  pinMode(STATUS_LED_PIN, OUTPUT);
  pinMode(VOLTAGE_SENSE_PIN, INPUT);

  // 1. Force the system to start LOW/OFF
  systemOn = false;
  pulseArmed = false;
  digitalWrite(GATE_DRIVE_PIN, LOW);
  digitalWrite(STATUS_LED_PIN, HIGH);

  // 2. Capture the switch position at boot so we know what "no change" looks like
  lastPhysicalState = digitalRead(SWITCH_PIN);
  
  Serial.println("Boot: System OFF. Waiting for first switch toggle...");
}

void loop() {
  int currentReading = digitalRead(SWITCH_PIN);

  // 3. Detect any CHANGE in the physical switch position
  if (currentReading != lastPhysicalState) {
    // Basic debounce check
    delay(debounceDelay); 
    currentReading = digitalRead(SWITCH_PIN); // Re-read to confirm
    
    if (currentReading != lastPhysicalState) {
      // The switch was clicked/toggled. Flip the logic state.
      systemOn = !systemOn; 
      lastPhysicalState = currentReading; // Sync physical state
      applySystemState();
    }
    delay(10000);
    systemOn = false; 
    lastPhysicalState = currentReading; // Sync physical state
    applySystemState();
  }

  // 4. One-Time Pulse Logic
  // Only fires if system is OFF and we have previously transitioned from ON
  if (!systemOn && pulseArmed) { //0 disable single pulse
    long sum = 0;
    for(int i = 0; i < 4; i++) sum += analogRead(VOLTAGE_SENSE_PIN);
    int rawAvg = sum / 4;

    float sourceV = getCalibratedVoltage(rawAvg) * DIVIDER_RATIO;

    if (sourceV <= TARGET_SOURCE_VOLTAGE) {
      // 10us Pulse
      digitalWrite(GATE_DRIVE_PIN, HIGH);
      // delayMicroseconds(1000);
      delay(2);
      digitalWrite(GATE_DRIVE_PIN, LOW);
      
      // Disarm: It will not pulse again until the system is turned ON and OFF again
      pulseArmed = false; 
      
      Serial.print("CRITICAL: One-time Pulse fired at "); 
      Serial.print(sourceV);
      Serial.println("V");
    }
  }
}
