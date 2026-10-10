# Camera firmware (Freenove ESP32-S3 WROOM CAM)

Joins the phone hotspot and serves frames to the vision service. The default target is the
**Freenove ESP32-S3 WROOM CAM** (8 MB flash, 8 MB PSRAM). AI-Thinker ESP32-CAM still works:
see the bottom of this page.

| URL | what |
|---|---|
| `http://<ip>/capture` | one JPEG (polled by `vision/`) |
| `http://<ip>:81/stream` | MJPEG live view |
| `http://<ip>/status` | JSON: sensor, rssi, heap, uptime, frames served |

## Flash it
1. `cp secrets.example.h secrets.h` and set the hotspot SSID/password and a unique `CAMERA_NAME`.
   The hotspot must be **2.4 GHz** (on iPhone, turn on *Maximize Compatibility*).
2. **Arduino IDE:** in Preferences → Additional boards manager URLs, add
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`, then install
   **esp32** by Espressif (3.x). Under Tools, set:
   - Board: **ESP32S3 Dev Module**
   - PSRAM: **OPI PSRAM** ← required; without it the camera falls back to tiny frames
   - Flash Size: **8MB (64Mb)**
   - Partition Scheme: **8M with spiffs (3MB APP/1.5MB SPIFFS)**

   **arduino-cli:**
   ```bash
   arduino-cli core install esp32:esp32 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
   FQBN="esp32:esp32:esp32s3:PSRAM=opi,FlashSize=8M,PartitionScheme=default_8MB"
   arduino-cli compile --fqbn $FQBN .
   arduino-cli upload  --fqbn $FQBN -p /dev/ttyACM0 .     # or /dev/ttyUSB0, see `arduino-cli board list`
   ```
3. Plug the USB-C cable into the port marked **UART** (the board's USB-to-serial chip).
   - **Upload won't start:** hold **BOOT**, tap **RST**, release BOOT, and upload again.
   - **Using the other port (native USB):** set Tools → *USB CDC On Boot* → **Enabled**,
     or the serial monitor stays blank.
   - **Linux "permission denied":** `sudo usermod -aG dialout $USER`, then log out and back in.
4. Serial monitor at 115200 prints the sensor type, then the line to put in `vision/cameras.json`:
   ```
   Camera sensor PID 0x2642 (OV2640), PSRAM yes
   cameras.json source:   esp32:http://192.168.43.50
   ```
   The blue LED blinks while connecting and stays on once connected.

The kit's SD card isn't used; frames go straight to the laptop over Wi-Fi.

## Troubleshooting
- **`PSRAM NO` in the serial log:** PSRAM isn't set to *OPI PSRAM* in the board settings.
- **`Camera init failed 0x105` / `0x20004`:** the camera ribbon isn't fully seated. Lift the
  latch, push the cable in fully (contacts facing the board), and close the latch.
- **Picture upside down or mirrored:** toggle the `set_vflip` / `set_hmirror` lines in
  `initCamera()`. The firmware already corrects for OV2640 vs OV3660.
- **Laptop can't reach the camera:** both devices must be on the same hotspot. Check
  `curl http://<ip>/status`. Some Android hotspots isolate clients; if so, try another phone.
- **No flash LED:** this board doesn't have one. Light the face from the front for the demo;
  backlighting (e.g. a window behind the user) hurts recognition the most.

## Using an AI-Thinker ESP32-CAM instead
Add `#define BOARD_AI_THINKER` in `secrets.h` and pick the board **AI Thinker ESP32-CAM**.
That gives you `/flash?on=1` for its white LED. Flash it with an ESP32-CAM-MB, or an FTDI
adapter at 5 V with GPIO0 tied to GND while uploading.
