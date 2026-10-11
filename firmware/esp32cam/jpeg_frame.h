#pragma once
// Separate header so the Arduino IDE's auto-generated function prototypes can see this type.
#include "esp_camera.h"

// One JPEG frame, whatever the sensor. Call releaseJpeg() when done with it.
struct JpegFrame {
  camera_fb_t *fb;
  uint8_t *buf;
  size_t len;
  bool owned;  // buf was allocated by software encoding
};
