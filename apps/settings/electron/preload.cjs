const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("localrag", {
  openPath: (folder) => ipcRenderer.invoke("localrag:open-path", folder),
  syncFolders: () => ipcRenderer.invoke("localrag:sync-folders"),
  detachFolder: (kbId) => ipcRenderer.invoke("localrag:detach-folder", kbId),
});
