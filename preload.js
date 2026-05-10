const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  // Window controls
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close:    () => ipcRenderer.send('window-close'),

  // Settings
  getSetting:    (key)        => ipcRenderer.invoke('settings-get', key),
  setSetting:    (key, value) => ipcRenderer.invoke('settings-set', key, value),
  getAllSettings: ()           => ipcRenderer.invoke('settings-get-all'),

  // Dialogs
  openFiles:   (opts) => ipcRenderer.invoke('dialog-open-files', opts),
  saveFile:    (opts) => ipcRenderer.invoke('dialog-save-file', opts),
  openFolder:  ()     => ipcRenderer.invoke('dialog-open-folder'),

  // YouTube downloader
  ytGetInfo:       (url)    => ipcRenderer.invoke('yt-get-info', url),
  ytStartDownload: (params) => ipcRenderer.invoke('yt-start-download', params),
  ytPause:         (id)     => ipcRenderer.send('yt-pause-download', id),
  ytResume:        (id)     => ipcRenderer.send('yt-resume-download', id),
  ytCancel:        (id)     => ipcRenderer.send('yt-cancel-download', id),

  // AI Translator
  aiStartTranslation: (params) => ipcRenderer.invoke('ai-start-translation', params),
  aiCancelTranslation:(id)     => ipcRenderer.send('ai-cancel-translation', id),
  aiRenderFinal:      (params) => ipcRenderer.invoke('ai-render-final', params),

  // Shell
  openInExplorer: (path) => ipcRenderer.send('open-file-in-explorer', path),
  openExternal:   (url)  => ipcRenderer.send('open-external', url),

  // Event listeners (renderer subscribes to main push events)
  on: (channel, callback) => {
    const allowed = [
      'dl-progress', 'dl-done', 'dl-error',
      'tr-step', 'tr-done', 'tr-error',
      'render-progress',
    ];
    if (allowed.includes(channel)) {
      ipcRenderer.on(channel, (_, data) => callback(data));
    }
  },
  off: (channel, callback) => {
    ipcRenderer.removeListener(channel, callback);
  },
});
