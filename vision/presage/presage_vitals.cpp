// presage_vitals: run one recorded clip through the SmartSpectra C++ SDK and print the
// heart rate / breathing rate it finds as a single JSON line on stdout.
//
// Called by gymvision/vitals.py once per clip (one shoulder-press set's worth of face crops):
//
//   SMARTSPECTRA_API_KEY=... ./presage_vitals --video clip.avi [--timestamps clip_ts.txt]
//       [--timeout_s 90] [--interframe_delay_ms 20]
//
// --timestamps is the SDK's sidecar format: one frame timestamp in milliseconds per line, one
// line per frame. Pass it - the Python side captures at a variable rate, so the container's
// nominal fps is only approximate and rPPG needs real frame timing.
//
// stdout carries exactly one line of JSON, everything else (SDK logging, progress) goes to
// stderr. On success:
//   {"ok":true,"hr":72.4,"peak_hr":80.1,"hr_stable":true,"rr":14.2,"rr_stable":false,
//    "hr_samples":[{"t":...,"v":...,"c":...,"s":true},...],"rr_samples":[...]}
// "hr"/"rr" are null when the SDK produced no reading (e.g. no face found, clip too short -
// pulse rate needs ~12s of footage). On failure: {"ok":false,"error":"..."} and exit code 1.

#include <smartspectra/messages/metrics.h>
#include <smartspectra/smartspectra.h>
#include <smartspectra/smartspectra_config.h>

#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

namespace spectra = presage::smartspectra;

namespace {

struct Sample {
    int64_t t;  // microseconds
    float value;
    float confidence;
    bool stable;
};

struct Args {
    std::string video;
    std::string timestamps;
    std::string api_key;
    int timeout_s = 90;
    int interframe_delay_ms = 20;
};

// Real stdout, kept aside so SDK logging can't interleave with our JSON (see main()).
FILE* g_out = stdout;

std::string JsonEscape(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 2);
    for (const char c : s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out += c;
                }
        }
    }
    return out;
}

[[noreturn]] void Fail(const std::string& message) {
    std::fprintf(g_out, "{\"ok\":false,\"error\":\"%s\"}\n", JsonEscape(message).c_str());
    std::fflush(g_out);
    std::exit(1);
}

std::optional<Args> ParseArgs(int argc, char** argv) {
    Args args;
    for (int i = 1; i < argc; ++i) {
        std::string flag = argv[i];
        std::string value;
        if (const auto eq = flag.find('='); eq != std::string::npos) {  // --flag=value
            value = flag.substr(eq + 1);
            flag = flag.substr(0, eq);
        } else if (i + 1 < argc) {                                       // --flag value
            value = argv[++i];
        } else {
            return std::nullopt;
        }
        if (flag == "--video") args.video = value;
        else if (flag == "--timestamps") args.timestamps = value;
        else if (flag == "--api_key") args.api_key = value;
        else if (flag == "--timeout_s") args.timeout_s = std::atoi(value.c_str());
        else if (flag == "--interframe_delay_ms") args.interframe_delay_ms = std::atoi(value.c_str());
        else return std::nullopt;
    }
    if (args.api_key.empty()) {
        // env is preferred - argv is visible to every user in `ps`
        if (const char* key = std::getenv("SMARTSPECTRA_API_KEY")) args.api_key = key;
    }
    if (args.video.empty()) return std::nullopt;
    return args;
}

void Collect(const google::protobuf::RepeatedPtrField<spectra::MeasurementWithConfidence>& in,
             std::vector<Sample>& out) {
    for (const auto& m : in) {
        if (m.timestamp() > 0) out.push_back({m.timestamp(), m.value(), m.confidence(), m.stable()});
    }
}

// Average over the stable samples if the SDK marked any, otherwise over everything it gave us.
struct Summary {
    std::optional<double> mean;
    std::optional<double> peak;
    bool stable = false;
};

Summary Summarize(const std::vector<Sample>& samples) {
    Summary s;
    const bool any_stable = std::any_of(samples.begin(), samples.end(), [](const Sample& x) { return x.stable; });
    double sum = 0.0, peak = 0.0;
    int n = 0;
    for (const auto& x : samples) {
        if (any_stable && !x.stable) continue;
        sum += x.value;
        peak = n == 0 ? x.value : std::max<double>(peak, x.value);
        ++n;
    }
    if (n > 0) {
        s.mean = sum / n;
        s.peak = peak;
        s.stable = any_stable;
    }
    return s;
}

std::string Num(const std::optional<double>& v) {
    if (!v) return "null";
    std::ostringstream os;
    os.precision(2);
    os << std::fixed << *v;
    return os.str();
}

std::string SamplesJson(const std::vector<Sample>& samples) {
    std::ostringstream os;
    os << '[';
    for (size_t i = 0; i < samples.size(); ++i) {
        const auto& x = samples[i];
        if (i) os << ',';
        os << "{\"t\":" << x.t << ",\"v\":" << x.value << ",\"c\":" << x.confidence
           << ",\"s\":" << (x.stable ? "true" : "false") << '}';
    }
    os << ']';
    return os.str();
}

}  // namespace

int main(int argc, char** argv) {
    // Keep the real stdout for our one JSON line and point fd 1 at stderr, so anything the SDK
    // (or its bundled logging) writes to stdout ends up on stderr instead of corrupting the result.
    if (const int fd = dup(STDOUT_FILENO); fd >= 0) {
        if (FILE* f = fdopen(fd, "w")) g_out = f;
        dup2(STDERR_FILENO, STDOUT_FILENO);
    }

    const auto parsed = ParseArgs(argc, argv);
    if (!parsed) {
        std::cerr << "usage: presage_vitals --video PATH [--timestamps PATH] [--api_key KEY] "
                     "[--timeout_s N] [--interframe_delay_ms N]\n"
                     "       (or set SMARTSPECTRA_API_KEY instead of --api_key)\n";
        Fail("bad arguments");
    }
    const Args& args = *parsed;
    if (args.api_key.empty()) Fail("no API key (set SMARTSPECTRA_API_KEY or pass --api_key)");

    spectra::SmartSpectraConfig config;
    config.api_key = args.api_key;
    config.requested_metrics = spectra::SmartSpectraConfig::BreathingMetrics();
    config.AddMetrics(spectra::SmartSpectraConfig::CardioMetrics());

    std::mutex mu;  // callbacks fire on SDK worker threads
    std::vector<Sample> hr_samples, rr_samples;
    std::string last_error, last_validation;

    spectra::SmartSpectra sdk(config);
    sdk.SetOnMetrics([&](const spectra::Metrics& metrics, int64_t) {
        std::lock_guard<std::mutex> lock(mu);
        if (metrics.has_cardio()) Collect(metrics.cardio().pulse_rate(), hr_samples);
        if (metrics.has_breathing()) Collect(metrics.breathing().rate(), rr_samples);
    });
    sdk.SetOnValidationStatusChanged([&](const spectra::ValidationStatus& status, int64_t) {
        std::ostringstream os;
        os << status.code << ": " << status.hint;
        std::lock_guard<std::mutex> lock(mu);
        if (os.str() != last_validation) {
            last_validation = os.str();
            std::cerr << "validation [" << last_validation << "]\n";
        }
    });
    sdk.SetOnError([&](const spectra::SmartSpectraError& error) {
        std::lock_guard<std::mutex> lock(mu);
        last_error = error.FullMessage();
        std::cerr << "error: " << last_error << "\n";
    });

    const auto source_error = args.timestamps.empty()
        ? sdk.UseFile(args.video).SetInterframeDelay(args.interframe_delay_ms).Build()
        : sdk.UseFile(args.video).SetTimestamps(args.timestamps)
              .SetInterframeDelay(args.interframe_delay_ms).Build();
    if (!source_error.ok()) Fail("input setup failed: " + source_error.FullMessage());

    if (const auto err = sdk.Start(); !err.ok()) Fail("start failed: " + err.FullMessage());

    // A file source ends its own session at EOF, so Stop() is only needed if we timed out.
    const bool completed = sdk.WaitUntilComplete(std::chrono::seconds(args.timeout_s));
    std::cerr << "finished (completed=" << completed << ", status=" << static_cast<int>(sdk.GetStatus()) << ")\n";
    if (!completed) {
        if (const auto err = sdk.Stop(); !err.ok()) std::cerr << "stop failed: " << err.message << "\n";
    }

    std::lock_guard<std::mutex> lock(mu);
    if (!completed && hr_samples.empty() && rr_samples.empty()) {
        Fail("timed out after " + std::to_string(args.timeout_s) + "s with no readings");
    }
    // A clip the SDK simply found nothing in (no face, too short) isn't an error - it's a null
    // reading with the validation hint saying why. Only fail on errors the SDK actually reported.
    if (!last_error.empty() && hr_samples.empty() && rr_samples.empty()) Fail(last_error);

    const Summary hr = Summarize(hr_samples);
    const Summary rr = Summarize(rr_samples);
    std::fprintf(g_out,
                 "{\"ok\":true,\"hr\":%s,\"peak_hr\":%s,\"hr_stable\":%s,\"rr\":%s,\"rr_stable\":%s,"
                 "\"validation\":\"%s\",\"hr_samples\":%s,\"rr_samples\":%s}\n",
                 Num(hr.mean).c_str(), Num(hr.peak).c_str(), hr.stable ? "true" : "false",
                 Num(rr.mean).c_str(), rr.stable ? "true" : "false",
                 JsonEscape(last_validation).c_str(),
                 SamplesJson(hr_samples).c_str(), SamplesJson(rr_samples).c_str());
    std::fflush(g_out);
    return 0;
}
