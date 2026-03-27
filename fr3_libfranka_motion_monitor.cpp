#include <arpa/inet.h>
#include <franka/exception.h>
#include <franka/robot.h>
#include <netinet/in.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#include <array>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>

namespace {

volatile std::sig_atomic_t g_running = 1;

constexpr double kVelocityNormThreshold = 0.01;
constexpr double kPositionRateThreshold = 0.0005;
constexpr int kLoopSleepMs = 100;
constexpr int kRetrySleepMs = 1000;
constexpr int kApiPort = 8765;

void handle_signal(int) { g_running = 0; }

bool pid_file_points_to_live_process(const std::string& pid_file) {
  std::ifstream in(pid_file);
  if (!in) {
    return false;
  }

  int pid = 0;
  in >> pid;
  if (pid <= 0) {
    return false;
  }

  return ::kill(pid, 0) == 0;
}

double norm(const std::array<double, 7>& values) {
  double total = 0.0;
  for (double value : values) {
    total += value * value;
  }
  return std::sqrt(total);
}

bool post_arm_moving_update() {
  const char* payload = "{\"arm_moving\":1,\"ttl_sec\":0.35}";

  int sock = ::socket(AF_INET, SOCK_STREAM, 0);
  if (sock < 0) {
    return false;
  }

  sockaddr_in addr {};
  addr.sin_family = AF_INET;
  addr.sin_port = htons(kApiPort);
  if (::inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr) != 1) {
    ::close(sock);
    return false;
  }

  if (::connect(sock, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
    ::close(sock);
    return false;
  }

  std::ostringstream request;
  request << "POST /state HTTP/1.1\r\n"
          << "Host: 127.0.0.1\r\n"
          << "Content-Type: application/json\r\n"
          << "Content-Length: " << std::strlen(payload) << "\r\n"
          << "Connection: close\r\n\r\n"
          << payload;

  const std::string body = request.str();
  const char* data = body.c_str();
  std::size_t remaining = body.size();

  while (remaining > 0) {
    ssize_t sent = ::send(sock, data, remaining, 0);
    if (sent <= 0) {
      ::close(sock);
      return false;
    }
    data += sent;
    remaining -= static_cast<std::size_t>(sent);
  }

  char buffer[256];
  while (::recv(sock, buffer, sizeof(buffer), 0) > 0) {
  }

  ::close(sock);
  return true;
}

}  // namespace

int main(int argc, char** argv) {
  std::signal(SIGTERM, handle_signal);
  std::signal(SIGINT, handle_signal);

  std::string robot_ip = "172.16.0.2";
  std::string visual_pid_file = "/tmp/fr3_visual_servo.pid";

  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--ip" && (i + 1) < argc) {
      robot_ip = argv[++i];
    } else if (arg == "--visual-pid-file" && (i + 1) < argc) {
      visual_pid_file = argv[++i];
    }
  }

  std::cout << "fr3_libfranka_motion_monitor started for robot " << robot_ip << std::endl;

  std::array<double, 7> previous_q {};
  bool have_previous_q = false;
  auto previous_time = std::chrono::steady_clock::now();

  while (g_running) {
    if (!pid_file_points_to_live_process(visual_pid_file)) {
      have_previous_q = false;
      std::this_thread::sleep_for(std::chrono::milliseconds(kLoopSleepMs));
      continue;
    }

    try {
      franka::Robot robot(robot_ip);
      std::cout << "Connected to libfranka robot state stream." << std::endl;

      while (g_running && pid_file_points_to_live_process(visual_pid_file)) {
        franka::RobotState state = robot.readOnce();
        auto now = std::chrono::steady_clock::now();

        std::array<double, 7> dq {};
        std::array<double, 7> q {};
        for (std::size_t i = 0; i < 7; ++i) {
          dq[i] = state.dq[i];
          q[i] = state.q[i];
        }

        bool moving = norm(dq) > kVelocityNormThreshold;

        if (!moving && have_previous_q) {
          const double dt =
              std::chrono::duration<double>(now - previous_time).count();
          if (dt > 0.0) {
            std::array<double, 7> q_rate {};
            for (std::size_t i = 0; i < 7; ++i) {
              q_rate[i] = (q[i] - previous_q[i]) / dt;
            }
            moving = norm(q_rate) > kPositionRateThreshold;
          }
        }

        previous_q = q;
        have_previous_q = true;
        previous_time = now;

        if (moving) {
          post_arm_moving_update();
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(kLoopSleepMs));
      }

      std::cout << "Visual servo inactive; waiting." << std::endl;
    } catch (const franka::Exception& exc) {
      have_previous_q = false;
      std::cerr << "libfranka error: " << exc.what() << std::endl;
      std::this_thread::sleep_for(std::chrono::milliseconds(kRetrySleepMs));
    } catch (const std::exception& exc) {
      have_previous_q = false;
      std::cerr << "monitor error: " << exc.what() << std::endl;
      std::this_thread::sleep_for(std::chrono::milliseconds(kRetrySleepMs));
    }
  }

  std::cout << "fr3_libfranka_motion_monitor exiting." << std::endl;
  return 0;
}
