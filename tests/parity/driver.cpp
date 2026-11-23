// Parity driver: runs the Arduino SME AIoT SDK (built for the host against its
// own test stand-ins in test/fakes) through a script read from stdin, and
// prints everything it does on the wire as a trace. tests/parity/driver.py does
// the same with the Python SDK; the two traces must be identical.
//
// Script lines:
//   offer_mqtt <host>|-        wifi 0|1        epoch <n>
//   code <url-suffix> <code>   cmds <json array of commands>
//   begin [fw] | begin_nofw    reboot          run <ms>
//   pub_i <pin> <int>  pub_f <pin> <hex32>  pub_d <pin> <hex64>  pub_b <pin> 0|1  pub_s <pin> <text>
//   deadband <pin|-1> <hex32>  minint <pin|-1> <ms>
//   msg <pin> <text>   messenger <pin>   type <text>
//   mqtt_drop   mqtt_accept 0|1   mqtt_pubok 0|1   deliver <payload>

#define SME_PRINT Serial
#include "test_support.h"

#include <cstring>
#include <iostream>
#include <sstream>

static std::vector<std::pair<int, std::string>> g_events;   // (kind, text) this tick
static unsigned long g_tick = 0;
enum { K_HTTP = 0, K_CONNECT = 1, K_SUB = 2, K_PUB = 3, K_CB = 4, K_OUT = 5 };

static void ev(int kind, const std::string& s) { g_events.push_back({kind, s}); }

static void flush_events() {
  std::stable_sort(g_events.begin(), g_events.end(),
                   [](const std::pair<int, std::string>& a, const std::pair<int, std::string>& b) {
                     return a.first < b.first;
                   });
  for (auto& e : g_events) std::cout << g_tick << " " << e.second << "\n";
  g_events.clear();
}

#define LISTEN(n) SME_LISTEN(TP##n) { ev(K_CB, "CB " #n " " + std::string(data.c_str())); }
LISTEN(0) LISTEN(1) LISTEN(2) LISTEN(3) LISTEN(4) LISTEN(5) LISTEN(6) LISTEN(7)
LISTEN(8) LISTEN(9) LISTEN(10) LISTEN(11) LISTEN(12) LISTEN(13) LISTEN(14) LISTEN(15)
LISTEN(16) LISTEN(17) LISTEN(18) LISTEN(19) LISTEN(20) LISTEN(127)

static std::map<std::string, int> g_codes;
static std::vector<std::string> g_cmds;
static std::string g_mqtt_host;
static size_t g_out_seen = 0, g_pub_seen = 0;
static int g_connects_seen = 0;

static void install_backend() {
  fake::http_answer = [](const fake::HttpRequest& r) -> fake::HttpReply {
    std::string h;
    for (auto& kv : r.headers) h += kv.first + "=" + kv.second + ";";
    ev(K_HTTP, "HTTP " + r.method + " " + r.url + " " + h + " " + r.body);
    for (auto& kv : g_codes)
      if (backend::ends_with(r.url, kv.first) && kv.second != 200) return {kv.second, "{\"message\":\"no\"}"};
    if (backend::ends_with(r.url, "/devices/register")) {
      std::string d = std::string("{\"data\":{\"device_id\":\"dev-123\"");
      if (!g_mqtt_host.empty())
        d += ",\"mqtt_broker\":\"" + g_mqtt_host +
             "\",\"mqtt_port\":8883,\"mqtt_tls\":true,\"mqtt_username\":\"mq-user\",\"mqtt_password\":\"mq-pass\"";
      return {200, d + "}}"};
    }
    if (backend::ends_with(r.url, "/commands") && r.method == "GET") {
      if (g_cmds.empty()) return {200, "{\"data\":[]}"};
      std::string b = g_cmds.front();
      g_cmds.erase(g_cmds.begin());
      return {200, "{\"data\":" + b + "}"};
    }
    return {200, "{}"};
  };
}

static PubSubClient& mq() { return SME._mqtt._mqtt; }

static void collect() {
  PubSubClient& m = mq();
  if (m.connect_calls != g_connects_seen) {
    g_connects_seen = m.connect_calls;
    std::ostringstream o;
    o << "CONNECT " << m.host << ":" << m.port << " tls=" << (m.client && m.client->secure ? 1 : 0)
      << " id=" << m.client_id << " user=" << m.user << " pass=" << m.pass
      << " will=" << m.will_topic << "|" << (int)m.will_qos << "|" << m.will_retain << "|" << m.will_msg
      << " clean=" << m.clean << " keepalive=" << m.keepalive << " ok=" << m.is_connected;
    ev(K_CONNECT, o.str());
    if (m.is_connected) ev(K_SUB, "SUB " + m.subscribed + " " + std::to_string((int)m.sub_qos));
  }
  while (g_pub_seen < m.published.size()) {
    auto& p = m.published[g_pub_seen++];
    ev(K_PUB, "PUB " + p.topic + " " + (p.retained ? "1" : "0") + " " + p.payload);
  }
  std::string& out = Serial.out;
  while (true) {
    size_t nl = out.find('\n', g_out_seen);
    if (nl == std::string::npos) break;
    ev(K_OUT, "OUT " + out.substr(g_out_seen, nl - g_out_seen));
    g_out_seen = nl + 1;
  }
}

static void reboot() {
  fresh_sme();
  install_backend();
  g_out_seen = 0; g_pub_seen = 0; g_connects_seen = 0;
}

static float bits32(const std::string& h) { uint32_t b = std::stoul(h, nullptr, 16); float f; memcpy(&f, &b, 4); return f; }
static double bits64(const std::string& h) { uint64_t b = std::stoull(h, nullptr, 16); double d; memcpy(&d, &b, 8); return d; }

int main() {
  fake::now_ms = 100000;
  fake::epoch = 1800000000;
  reboot();
  std::string line, fw_keep;
  std::vector<std::string> keep;   // begin() keeps pointers to these
  while (std::getline(std::cin, line)) {
    std::istringstream in(line);
    std::string cmd; in >> cmd;
    std::string rest; std::getline(in, rest); if (!rest.empty() && rest[0] == ' ') rest = rest.substr(1);
    g_tick = fake::now_ms;
    if (cmd == "offer_mqtt") g_mqtt_host = rest == "-" ? "" : rest;
    else if (cmd == "wifi") WiFi.connected = rest == "1";
    else if (cmd == "epoch") fake::epoch = std::stoll(rest);
    else if (cmd == "code") { std::istringstream r(rest); std::string s; int c; r >> s >> c; g_codes[s] = c; }
    else if (cmd == "cmds") g_cmds.push_back(rest);
    else if (cmd == "begin") { keep.push_back(rest.empty() ? "0.0.1" : rest); SME.begin("PROJ-TEST0001", "SME-TEST-TOKEN-0001", keep.back().c_str(), "my-wifi", "wifi-pass"); }
    else if (cmd == "begin_nofw") SME.begin("PROJ-TEST0001", "SME-TEST-TOKEN-0001", "my-wifi", "wifi-pass");
    else if (cmd == "reboot") reboot();
    else if (cmd == "run") {
      unsigned long ms = std::stoul(rest);
      for (unsigned long t = 0; t < ms; t += 10) { g_tick = fake::now_ms; SME.run(); collect(); flush_events(); fake::now_ms += 10; }
      continue;
    }
    else if (cmd == "pub_i") { std::istringstream r(rest); int p; long v; r >> p >> v; SME.publish((uint8_t)p, v); }
    else if (cmd == "pub_f") { std::istringstream r(rest); int p; std::string h; r >> p >> h; SME.publish((uint8_t)p, bits32(h)); }
    else if (cmd == "pub_d") { std::istringstream r(rest); int p; std::string h; r >> p >> h; SME.publish((uint8_t)p, bits64(h)); }
    else if (cmd == "pub_b") { std::istringstream r(rest); int p, v; r >> p >> v; SME.publish((uint8_t)p, v != 0); }
    else if (cmd == "pub_s") { size_t sp = rest.find(' '); int p = std::stoi(rest.substr(0, sp)); SME.publish((uint8_t)p, sp == std::string::npos ? "" : rest.c_str() + sp + 1); }
    else if (cmd == "deadband") { std::istringstream r(rest); int p; std::string h; r >> p >> h; if (p < 0) SME.setDeadband(bits32(h)); else SME.setDeadband((uint8_t)p, bits32(h)); }
    else if (cmd == "minint") { std::istringstream r(rest); int p; unsigned long ms; r >> p >> ms; if (p < 0) SME.setMinInterval((uint32_t)ms); else SME.setMinInterval((uint8_t)p, (uint32_t)ms); }
    else if (cmd == "msg") { size_t sp = rest.find(' '); int p = std::stoi(rest.substr(0, sp)); bool ok = SME.sendMessage((uint8_t)p, sp == std::string::npos ? "" : rest.c_str() + sp + 1); ev(K_CB, std::string("MSGQ ") + (ok ? "1" : "0")); }
    else if (cmd == "messenger") SME.messenger((uint8_t)std::stoi(rest));
    else if (cmd == "type") Serial.type(rest + "\n");
    else if (cmd == "mqtt_drop") mq().is_connected = false;
    else if (cmd == "mqtt_accept") mq().accept_connect = rest == "1";
    else if (cmd == "mqtt_pubok") mq().publish_ok = rest == "1";
    else if (cmd == "deliver") { if (mq().callback) mq().deliver("smeiot/devices/dev-123/commands", rest); }
    collect();
    flush_events();
  }
  return 0;
}
