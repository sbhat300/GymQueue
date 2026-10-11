import time

import numpy as np
import pytest

from gymvision.camera import FallbackSource, FrameSource, SerialSource, open_source


class FakeSource(FrameSource):
    """Publishes frames while `working`, else nothing."""

    def __init__(self, spec, working):
        super().__init__(spec)
        self.working = working

    def _loop(self):
        while not self._stop.is_set():
            if self.working:
                self._publish(np.zeros((4, 4, 3), np.uint8))
            self._stop.wait(0.02)


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_fallback_moves_to_the_source_that_works(monkeypatch):
    monkeypatch.setattr(FallbackSource, "SWITCH_AFTER_S", 0.3)
    made = []

    def factory(spec):
        made.append(spec)
        return FakeSource(spec, working=(spec == "usb"))

    src = FallbackSource(["wifi", "usb"], factory=factory).start()
    try:
        assert wait_for(lambda: src.active is not None and src.active.spec == "usb")
        assert wait_for(lambda: src.latest()[2] is not None)
        assert "wifi" in src.last_error
    finally:
        src.stop()
    assert made[:2] == ["wifi", "usb"]


def test_fallback_stays_on_a_working_first_source(monkeypatch):
    monkeypatch.setattr(FallbackSource, "SWITCH_AFTER_S", 0.3)
    src = FallbackSource(["wifi", "usb"], factory=lambda spec: FakeSource(spec, working=True)).start()
    try:
        time.sleep(0.8)
        assert src.active.spec == "wifi"
    finally:
        src.stop()


def test_open_source_parses_serial_and_lists():
    s = open_source("serial:/dev/ttyACM0@460800")
    assert isinstance(s, SerialSource) and (s.port, s.baud) == ("/dev/ttyACM0", 460800)
    assert isinstance(open_source(["esp32:http://x", "serial:/dev/ttyACM0"]), FallbackSource)
    assert open_source(["serial:/dev/ttyACM0"]).spec == "serial:/dev/ttyACM0"


class FakeSerial:
    def __init__(self, lines):
        self.lines = list(lines)

    def readline(self):
        return self.lines.pop(0) if self.lines else b""


def test_serial_header_skips_log_lines():
    src = SerialSource("serial:x", "x")
    assert src._read_header(FakeSerial([b"Wi-Fi not connected, retrying\r\n", b"FRAME 6123\n"])) == 6123


def test_serial_header_times_out_cleanly():
    with pytest.raises(RuntimeError, match="didn't answer"):
        SerialSource("serial:x", "x")._read_header(FakeSerial([]))
