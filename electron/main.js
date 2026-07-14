const { app, BrowserWindow, ipcMain } = require("electron");
const { spawn } = require("child_process");
const path = require("path");

const API = "http://127.0.0.1:8765";
let pyProcess = null;

function startPythonBackend() {
  const root = path.join(__dirname, "..");
  pyProcess = spawn("python3", [path.join(root, "run_api.py")], {
    cwd: root,
    stdio: "ignore",
  });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
    },
    title: "同声传译 · Electron 前端",
  });
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
}

app.whenReady().then(() => {
  startPythonBackend();
  setTimeout(createWindow, 1500);
});

app.on("window-all-closed", () => {
  if (pyProcess) pyProcess.kill();
  if (process.platform !== "darwin") app.quit();
});

ipcMain.handle("api-base", () => API);
