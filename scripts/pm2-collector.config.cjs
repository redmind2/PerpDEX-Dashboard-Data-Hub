const path = require("path");

const projectRoot = path.resolve(__dirname, "..");
const pythonPath =
  "C:\\Users\\USER\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe";

module.exports = {
  apps: [
    {
      name: "perpdex-collector-hibachi",
      cwd: projectRoot,
      script: pythonPath,
      interpreter: "none",
      args: [
        "-m",
        "perpdex_bot",
        "collect-live",
        "--exchange",
        "Hibachi",
        "--interval",
        "60",
        "--log-file",
        "data/logs/collector.log",
      ],
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 20,
      out_file: "data/logs/pm2-hibachi-out.log",
      error_file: "data/logs/pm2-hibachi-error.log",
      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONPATH: path.join(projectRoot, "src"),
      },
    },
    {
      name: "perpdex-collector-rise",
      cwd: projectRoot,
      script: pythonPath,
      interpreter: "none",
      args: [
        "-m",
        "perpdex_bot",
        "collect-live",
        "--exchange",
        "Rise",
        "--interval",
        "60",
        "--log-file",
        "data/logs/collector.log",
      ],
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 20,
      out_file: "data/logs/pm2-rise-out.log",
      error_file: "data/logs/pm2-rise-error.log",
      env: {
        PYTHONUNBUFFERED: "1",
        PYTHONPATH: path.join(projectRoot, "src"),
      },
    },
  ],
};
