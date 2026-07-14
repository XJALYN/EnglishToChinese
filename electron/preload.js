const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  apiBase: "http://127.0.0.1:8765",
});
