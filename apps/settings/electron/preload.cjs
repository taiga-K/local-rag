const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("localrag", {
  openPath: (folder) => ipcRenderer.invoke("localrag:open-path", folder),
  pickFolder: () => ipcRenderer.invoke("localrag:pick-folder"),
  clonePath: () => ipcRenderer.invoke("localrag:clone-path"),
  pickClone: () => ipcRenderer.invoke("localrag:pick-clone"),
});
