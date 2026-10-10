// Copy to secrets.h (git-ignored) and fill in your phone hotspot.
// Phone hotspot tips: use 2.4 GHz (ESP32 has no 5 GHz), and turn on
// "maximize compatibility" on iPhone.
#pragma once
#define WIFI_SSID     "YourHotspotName"
#define WIFI_PASSWORD "hotspot-password"
#define CAMERA_NAME   "bench1"   // unique per camera; becomes http://gymcam-bench1.local

// Board: Freenove ESP32-S3 WROOM CAM is the default. For an AI-Thinker ESP32-CAM uncomment:
// #define BOARD_AI_THINKER

// Optional: frame size (default FRAMESIZE_HD 1280x720). Smaller = faster over Wi-Fi but shorter range.
// #define CAM_FRAMESIZE FRAMESIZE_SVGA
