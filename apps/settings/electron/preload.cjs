const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("localrag", {
  openPath: (folder) => ipcRenderer.invoke("localrag:open-path", folder),
  pickFolder: () => ipcRenderer.invoke("localrag:pick-folder"),
});
