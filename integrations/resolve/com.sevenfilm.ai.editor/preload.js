const { contextBridge, ipcRenderer } = require("electron/renderer");

contextBridge.exposeInMainWorld("resolveAPI", {
  getContext: () => ipcRenderer.invoke("resolve:getContext"),
  selectFolder: (title) => ipcRenderer.invoke("system:selectFolder", title),
  selectMusic: () => ipcRenderer.invoke("system:selectMusic"),
  importTimeline: (timelineId, timelineName) =>
    ipcRenderer.invoke("resolve:importTimeline", { timelineId, timelineName }),
  openPage: (pageName) => ipcRenderer.invoke("resolve:openPage", pageName),
  cleanup: () => ipcRenderer.invoke("resolve:cleanup"),
});
