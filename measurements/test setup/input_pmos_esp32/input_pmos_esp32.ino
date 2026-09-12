#include <Arduino.h>

// --- PIN DEFINITIONS ---
const int SWITCH_PIN = 27;        
const int GATE_DRIVE_PIN = 21;    
const int VOLTAGE_SENSE_PIN = 32; 
const int STATUS_LED_PIN = 13;    

// --- CALIBRATION & MATH ---
const float DIVIDER_RATIO = 5.0; 
const float TARGET_SOURCE_VOLTAGE = 5.5; 

// Replace with your measured values
float actualVolts[] = { 0.0, 0.5, 1.1, 1.5, 2.0, 2.5, 3.0, 3.3 };
int rawADCValues[]  = { 120, 640, 1380, 1890, 2520, 3150, 3850, 4095 };
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
  }

  // 4. One-Time Pulse Logic
  // Only fires if system is OFF and we have previously transitioned from ON
  if (!systemOn && pulseArmed) {
    long sum = 0;
    for(int i = 0; i < 16; i++) sum += analogRead(VOLTAGE_SENSE_PIN);
    int rawAvg = sum / 16;

    float sourceV = getCalibratedVoltage(rawAvg) * DIVIDER_RATIO;

    if (sourceV <= TARGET_SOURCE_VOLTAGE) {
      // 10us Pulse
      digitalWrite(GATE_DRIVE_PIN, HIGH);
      delayMicroseconds(10);
      digitalWrite(GATE_DRIVE_PIN, LOW);
      
      // Disarm: It will not pulse again until the system is turned ON and OFF again
      pulseArmed = false; 
      
      Serial.print("CRITICAL: One-time Pulse fired at "); 
      Serial.print(sourceV);
      Serial.println("V");
    }
  }
}
