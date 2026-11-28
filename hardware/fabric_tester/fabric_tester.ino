// drape fabric tester: ESP32 + HX711 load cell + slide potentiometer.
// Streams "ms,ext_mm,force_N" over USB serial at 115200 baud (the studio reads
// it with Web Serial; any serial monitor works too).
//
// Wiring (ESP32 DevKit):
//   HX711  DT -> GPIO16, SCK -> GPIO4, VCC -> 3V3, GND -> GND
//   Load cell (5 kg bar): red E+, black E-, white A-, green A+   (swap A+/A- if force reads negative)
//   Slide pot 10 kOhm, 100 mm travel: ends to 3V3 and GND, wiper -> GPIO34
//   Optional VL53L0X (droop test): SDA GPIO21, SCL GPIO22
//
// Serial commands:
//   t            tare (no load on the clamp)
//   z            zero the extension (clamps at gauge length, strip slack)
//   c <grams>    calibrate the load cell with a known weight hanging on the clamp
//   s            start streaming   x   stop
//   d            one droop reading from the VL53L0X (mm), if fitted
//   ?            show settings
//
// Library: "HX711" by Bogdan Necula (Arduino Library Manager). Optional: "VL53L0X" by Pololu.

#include <Arduino.h>
#include <Preferences.h>
#include "HX711.h"
#if __has_include(<VL53L0X.h>)
  #include <Wire.h>
  #include <VL53L0X.h>
  #define HAVE_TOF 1
  VL53L0X tof;
#endif

const int PIN_DT = 16, PIN_SCK = 4, PIN_POT = 34;
const float POT_TRAVEL_MM = 100.0;      // your slide pot's travel
const int RATE_HZ = 20;

HX711 scale;
Preferences prefs;
float calib = 2280.0;                   // raw units per gram (set with 'c')
float potZero = 0.0;                    // ADC reading at zero extension
bool streaming = false;
unsigned long t0 = 0;

float readPotMm() {
  long s = 0;
  for (int i = 0; i < 16; i++) s += analogRead(PIN_POT);
  float adc = s / 16.0;
  return (adc - potZero) / 4095.0 * POT_TRAVEL_MM;
}

float readForceN() {
  if (!scale.is_ready()) return NAN;
  return scale.get_units(1) / 1000.0 * 9.81;     // grams -> newtons
}

void showSettings() {
  Serial.printf("# drape fabric tester  calib=%.2f raw/g  potZero=%.1f  travel=%.0f mm  rate=%d Hz\n",
                calib, potZero, POT_TRAVEL_MM, RATE_HZ);
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  scale.begin(PIN_DT, PIN_SCK);
  prefs.begin("drape", false);
  calib = prefs.getFloat("calib", calib);
  potZero = prefs.getFloat("potZero", 0.0);
  scale.set_scale(calib);
  scale.tare();
#ifdef HAVE_TOF
  Wire.begin(21, 22);
  tof.setTimeout(200);
  if (!tof.init()) Serial.println("# no VL53L0X found (droop test by ruler)");
#endif
  showSettings();
  Serial.println("# ready: t=tare z=zero c <g>=calibrate s=start x=stop");
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n'); cmd.trim();
    if (cmd == "t") { scale.tare(); Serial.println("# tared"); }
    else if (cmd == "z") {
      long s = 0; for (int i = 0; i < 64; i++) s += analogRead(PIN_POT);
      potZero = s / 64.0; prefs.putFloat("potZero", potZero); Serial.println("# extension zeroed");
    }
    else if (cmd.startsWith("c")) {
      float g = cmd.substring(1).toFloat();
      if (g > 0) {
        scale.set_scale(1.0);
        float raw = scale.get_units(20);
        calib = raw / g; scale.set_scale(calib); prefs.putFloat("calib", calib);
        Serial.printf("# calibrated: %.2f raw/g\n", calib);
      }
    }
    else if (cmd == "s") { streaming = true; t0 = millis(); Serial.println("ms,ext_mm,force_N"); }
    else if (cmd == "x") { streaming = false; Serial.println("# stopped"); }
    else if (cmd == "?") showSettings();
#ifdef HAVE_TOF
    else if (cmd == "d") { Serial.printf("# droop_mm=%d\n", tof.readRangeSingleMillimeters()); }
#endif
  }
  if (streaming) {
    static unsigned long last = 0;
    if (millis() - last >= 1000 / RATE_HZ) {
      last = millis();
      float f = readForceN();
      if (!isnan(f)) Serial.printf("%lu,%.3f,%.4f\n", millis() - t0, readPotMm(), f);
    }
  }
}
