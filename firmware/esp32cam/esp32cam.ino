// Gym queue camera - Freenove ESP32-S3 WROOM CAM (default) or AI-Thinker ESP32-CAM
//
// Joins the phone hotspot and serves JPEG frames to the laptop running vision/:
//   http://<ip>/capture      one JPEG (what the vision service polls)
//   http://<ip>/status       JSON health info
//   http://<ip>/flash?on=1   flash LED on/off (AI-Thinker only; Freenove has no flash LED)
//   http://<ip>:81/stream    MJPEG live view (browser preview / mjpeg: source)
// Also reachable as http://gymcam-<CAMERA_NAME>.local if the laptop supports mDNS.
//
// Copy secrets.example.h -> secrets.h first. Arduino IDE board settings (esp32 core 3.x):
//   Freenove ESP32-S3: Board "ESP32S3 Dev Module", PSRAM "OPI PSRAM", Flash Size "8MB",
//                      Partition Scheme "8M with spiffs (3MB APP/1.5MB SPIFFS)"
//   AI-Thinker:        Board "AI Thinker ESP32-CAM", and set BOARD below

#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include "esp_camera.h"
#include "esp_http_server.h"
#include "img_converters.h"
#include "jpeg_frame.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "secrets.h"

#ifndef CAMERA_NAME
#define CAMERA_NAME "bench1"
#endif

// ---- pick the board (or #define BOARD_AI_THINKER in secrets.h) ----
#if !defined(BOARD_AI_THINKER) && !defined(BOARD_FREENOVE_S3)
#define BOARD_FREENOVE_S3
#endif

#if defined(BOARD_FREENOVE_S3)
// Freenove ESP32-S3 WROOM CAM: same camera wiring as Espressif's ESP32-S3-EYE.
// GPIO 33-37 belong to the octal PSRAM - never use them.
#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     15
#define SIOD_GPIO_NUM      4
#define SIOC_GPIO_NUM      5
#define Y9_GPIO_NUM       16
#define Y8_GPIO_NUM       17
#define Y7_GPIO_NUM       18
#define Y6_GPIO_NUM       12
#define Y5_GPIO_NUM       10
#define Y4_GPIO_NUM        8
#define Y3_GPIO_NUM        9
#define Y2_GPIO_NUM       11
#define VSYNC_GPIO_NUM     6
#define HREF_GPIO_NUM      7
#define PCLK_GPIO_NUM     13
#define FLASH_LED_PIN     -1   // no flash LED on this board
#define STATUS_LED_PIN     2   // blue user LED
#define STATUS_LED_ON   HIGH
#define FLIP_IMAGE         1   // camera is mounted upside down on this board
#elif defined(BOARD_AI_THINKER)
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22
#define FLASH_LED_PIN      4
#define STATUS_LED_PIN    33   // small red LED on the back
#define STATUS_LED_ON    LOW
#define FLIP_IMAGE         0
#endif

// 1280x720: a face 3-4 m away is still ~35 px wide, enough to recognise. At 640x480 the same
// face is ~17 px and is lost past ~2 m. Drop to FRAMESIZE_SVGA if Wi-Fi can't keep up.
#ifndef CAM_FRAMESIZE
#define CAM_FRAMESIZE FRAMESIZE_HD
#endif

static void statusLed(bool on) { digitalWrite(STATUS_LED_PIN, on ? STATUS_LED_ON : !STATUS_LED_ON); }

// Some kits ship a sensor without a hardware JPEG encoder (e.g. GC2145). Then we capture
// RGB565 and compress on the ESP32 instead (slower, so at 640x480).
static bool softJpeg = false;
#define SOFT_JPEG_QUALITY 80
// Compressing on the ESP32 takes ~0.5 s per 640x480 frame; 320x240 is ~4x faster and still
// plenty for someone sitting on the machine. Override in secrets.h if needed.
#ifndef SOFT_JPEG_FRAMESIZE
#define SOFT_JPEG_FRAMESIZE FRAMESIZE_QVGA
#endif


static httpd_handle_t mainServer = NULL;
static httpd_handle_t streamServer = NULL;
static bool flashOn = false;
static uint32_t framesServed = 0;
static unsigned long wifiLostAt = 0;

// ------------------------------------------------------------------ camera
static bool initCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM;  c.pin_d1 = Y3_GPIO_NUM;  c.pin_d2 = Y4_GPIO_NUM;  c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM;  c.pin_d5 = Y7_GPIO_NUM;  c.pin_d6 = Y8_GPIO_NUM;  c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM;
  c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM;
  c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM;
  c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM;
  c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.grab_mode = CAMERA_GRAB_LATEST;   // always hand out the newest frame, never a stale one

  if (psramFound()) {
    c.frame_size = CAM_FRAMESIZE;
    c.jpeg_quality = 12;              // 0-63, lower = better
    c.fb_count = 2;
    c.fb_location = CAMERA_FB_IN_PSRAM;
  } else {
    c.frame_size = FRAMESIZE_QVGA;
    c.jpeg_quality = 15;
    c.fb_count = 1;
    c.fb_location = CAMERA_FB_IN_DRAM;
  }

  esp_err_t err = esp_camera_init(&c);
  if (err == ESP_ERR_NOT_SUPPORTED) {
    Serial.println("Sensor has no JPEG encoder - capturing RGB565 and compressing on the ESP32");
    esp_camera_deinit();
    c.pixel_format = PIXFORMAT_RGB565;
    c.frame_size = SOFT_JPEG_FRAMESIZE;
    c.fb_count = psramFound() ? 2 : 1;
    softJpeg = true;
    err = esp_camera_init(&c);
  }
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  sensor_t *s = esp_camera_sensor_get();
  camera_sensor_info_t *info = esp_camera_sensor_get_info(&s->id);
  Serial.printf("Camera sensor %s (PID 0x%x), %s, PSRAM %s\n", info ? info->name : "unknown", s->id.PID,
                softJpeg ? "software JPEG" : "hardware JPEG",
                psramFound() ? "yes" : "NO - check PSRAM board setting");
  bool flip = FLIP_IMAGE;
  if (s->id.PID == OV3660_PID) {      // OV3660 is mounted the other way round and over-saturated
    flip = !flip;
    s->set_saturation(s, -2);
  }
  // not every sensor driver implements every setting - only call the ones that exist
  if (s->set_brightness) s->set_brightness(s, 1);
  if (s->set_whitebal) s->set_whitebal(s, 1);
  if (s->set_gain_ctrl) s->set_gain_ctrl(s, 1);
  if (s->set_exposure_ctrl) s->set_exposure_ctrl(s, 1);
  if (s->set_aec2) s->set_aec2(s, 1);  // better auto-exposure for indoor gym lighting
  if (s->set_vflip) s->set_vflip(s, flip);
  // If the picture is still upside down / mirrored for how you mount it, toggle these:
  // s->set_vflip(s, !flip); s->set_hmirror(s, 1);
  return true;
}

// ------------------------------------------------------------------ handlers
static bool grabJpeg(JpegFrame &out) {
  out.fb = esp_camera_fb_get();
  if (!out.fb) return false;
  if (out.fb->format == PIXFORMAT_JPEG) {
    out.buf = out.fb->buf;
    out.len = out.fb->len;
    out.owned = false;
    return true;
  }
  out.owned = true;
  bool ok = frame2jpg(out.fb, SOFT_JPEG_QUALITY, &out.buf, &out.len);
  esp_camera_fb_return(out.fb);  // raw frame no longer needed
  out.fb = NULL;
  return ok;
}

static void releaseJpeg(JpegFrame &f) {
  if (f.owned) free(f.buf);
  if (f.fb) esp_camera_fb_return(f.fb);
}

static esp_err_t captureHandler(httpd_req_t *req) {
  JpegFrame f;
  if (!grabJpeg(f)) {
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  esp_err_t res = httpd_resp_send(req, (const char *)f.buf, f.len);
  releaseJpeg(f);
  framesServed++;
  return res;
}

#define PART_BOUNDARY "gymcamframe"
static const char *STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char *STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char *STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static esp_err_t streamHandler(httpd_req_t *req) {
  char partBuf[64];
  esp_err_t res = httpd_resp_set_type(req, STREAM_CONTENT_TYPE);
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  while (res == ESP_OK) {
    JpegFrame f;
    if (!grabJpeg(f)) {
      res = ESP_FAIL;
      break;
    }
    size_t hlen = snprintf(partBuf, sizeof(partBuf), STREAM_PART, f.len);
    res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, partBuf, hlen);
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, (const char *)f.buf, f.len);
    releaseJpeg(f);
    framesServed++;
  }
  return res;  // client disconnected
}

static esp_err_t statusHandler(httpd_req_t *req) {
  sensor_t *s = esp_camera_sensor_get();
  char json[320];
  snprintf(json, sizeof(json),
           "{\"device\":\"esp32-cam\",\"name\":\"%s\",\"ip\":\"%s\",\"rssi\":%d,"
           "\"uptime_s\":%lu,\"free_heap\":%u,\"psram\":%s,\"framesize\":%d,"
           "\"quality\":%d,\"flash\":%s,\"frames_served\":%lu}",
           CAMERA_NAME, WiFi.localIP().toString().c_str(), WiFi.RSSI(), millis() / 1000,
           ESP.getFreeHeap(), psramFound() ? "true" : "false", s->status.framesize,
           s->status.quality, flashOn ? "true" : "false", (unsigned long)framesServed);
  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  return httpd_resp_send(req, json, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t flashHandler(httpd_req_t *req) {
  if (FLASH_LED_PIN < 0) {
    httpd_resp_set_type(req, "application/json");
    return httpd_resp_send(req, "{\"flash\":false,\"supported\":false}", HTTPD_RESP_USE_STRLEN);
  }
  char query[32], val[8];
  if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK &&
      httpd_query_key_value(query, "on", val, sizeof(val)) == ESP_OK) {
    flashOn = atoi(val) != 0;
    digitalWrite(FLASH_LED_PIN, flashOn ? HIGH : LOW);
  }
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_send(req, flashOn ? "{\"flash\":true}" : "{\"flash\":false}", HTTPD_RESP_USE_STRLEN);
}

static void startServers() {
  httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
  cfg.server_port = 80;
  cfg.ctrl_port = 32768;
  httpd_uri_t capture = {"/capture", HTTP_GET, captureHandler, NULL};
  httpd_uri_t status = {"/status", HTTP_GET, statusHandler, NULL};
  httpd_uri_t flash = {"/flash", HTTP_GET, flashHandler, NULL};
  if (httpd_start(&mainServer, &cfg) == ESP_OK) {
    httpd_register_uri_handler(mainServer, &capture);
    httpd_register_uri_handler(mainServer, &status);
    httpd_register_uri_handler(mainServer, &flash);
  }
  // separate server so a browser watching /stream never blocks the vision service's /capture
  cfg.server_port = 81;
  cfg.ctrl_port = 32769;
  httpd_uri_t stream = {"/stream", HTTP_GET, streamHandler, NULL};
  if (httpd_start(&streamServer, &cfg) == ESP_OK) {
    httpd_register_uri_handler(streamServer, &stream);
  }
}

// ------------------------------------------------------------------ wifi
static const char *authName(wifi_auth_mode_t m) {
  switch (m) {
    case WIFI_AUTH_OPEN: return "open";
    case WIFI_AUTH_WPA_PSK: return "WPA";
    case WIFI_AUTH_WPA2_PSK: return "WPA2";
    case WIFI_AUTH_WPA_WPA2_PSK: return "WPA/WPA2";
    case WIFI_AUTH_WPA2_ENTERPRISE: return "WPA2-Enterprise (not supported)";
    case WIFI_AUTH_WPA3_PSK: return "WPA3";
    case WIFI_AUTH_WPA2_WPA3_PSK: return "WPA2/WPA3";
    default: return "other";
  }
}

// Why the last connection attempt failed, so setup problems are diagnosable from the serial log.
static void onWifiEvent(arduino_event_id_t event, arduino_event_info_t info) {
  if (event != ARDUINO_EVENT_WIFI_STA_DISCONNECTED) return;
  uint8_t r = info.wifi_sta_disconnected.reason;
  const char *hint = r == WIFI_REASON_NO_AP_FOUND ? "network not found on 2.4 GHz - check the name, or move closer"
                   : (r == WIFI_REASON_AUTH_FAIL || r == WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT || r == WIFI_REASON_HANDSHAKE_TIMEOUT)
                       ? "wrong password (or the router rejected the security mode)"
                   : r == WIFI_REASON_ASSOC_FAIL ? "router refused the connection (MAC filter / client limit?)" : "";
  Serial.printf("\nWi-Fi disconnected, reason %u %s\n", r, hint);
}

static void scanForNetwork() {
  int n = WiFi.scanNetworks();
  for (int i = 0; i < n; i++) {
    if (WiFi.SSID(i) == WIFI_SSID) {
      Serial.printf("Found network: channel %d, signal %d dBm, security %s\n", WiFi.channel(i), WiFi.RSSI(i),
                    authName(WiFi.encryptionType(i)));
      WiFi.scanDelete();
      return;
    }
  }
  Serial.printf("Network NOT visible on 2.4 GHz (%d networks seen) - name typo, 5 GHz only, or too far\n", n);
  WiFi.scanDelete();
}

static void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);               // power save adds big latency to every request
  WiFi.setHostname("gymcam-" CAMERA_NAME);
  WiFi.onEvent(onWifiEvent);
  scanForNetwork();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("Connecting to %s", WIFI_SSID);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    statusLed((millis() / 250) % 2);
    delay(250);
    Serial.print(".");
    if (millis() - start > 30000) {
      Serial.println("\nWi-Fi timeout, rebooting");
      ESP.restart();
    }
  }
  statusLed(true);                    // solid on = connected
  Serial.printf("\nConnected. Camera URL: http://%s/capture\n", WiFi.localIP().toString().c_str());
  Serial.printf("cameras.json source:   esp32:http://%s\n", WiFi.localIP().toString().c_str());
  if (MDNS.begin("gymcam-" CAMERA_NAME)) {
    MDNS.addService("http", "tcp", 80);
    Serial.println("mDNS: http://gymcam-" CAMERA_NAME ".local");
  }
}

void setup() {
#if defined(BOARD_AI_THINKER)
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);  // AI-Thinker browns out on weak USB power at Wi-Fi start
#endif
  Serial.begin(115200);
  Serial.println("\nGym queue camera booting");
  if (FLASH_LED_PIN >= 0) {
    pinMode(FLASH_LED_PIN, OUTPUT);
    digitalWrite(FLASH_LED_PIN, LOW);
  }
  pinMode(STATUS_LED_PIN, OUTPUT);
  statusLed(false);

  if (!initCamera()) {
    delay(3000);
    ESP.restart();
  }
  connectWifi();
  startServers();
}

void loop() {
  // hotspots drop clients; reconnect, and reboot if it stays down
  if (WiFi.status() != WL_CONNECTED) {
    if (wifiLostAt == 0) {
      wifiLostAt = millis();
      statusLed(false);
      Serial.println("Wi-Fi lost, reconnecting");
      WiFi.reconnect();
    } else if (millis() - wifiLostAt > 30000) {
      ESP.restart();
    }
  } else if (wifiLostAt != 0) {
    wifiLostAt = 0;
    statusLed(true);
    Serial.printf("Wi-Fi back: http://%s/capture\n", WiFi.localIP().toString().c_str());
  }
  delay(1000);
}
