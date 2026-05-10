const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');
const Store = require('electron-store');

const store = new Store();

// ─── Window ────────────────────────────────────────────────────────────────────
let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 780,
    minWidth: 860,
    minHeight: 600,
    frame: false,           // custom titlebar
    backgroundColor: '#0f0f0f',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    icon: path.join(__dirname, '../renderer/assets/icon.png'),
    show: false,
  });

  mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));

  mainWindow.once('ready-to-show', () => mainWindow.show());

  if (process.env.NODE_ENV === 'development') {
    mainWindow.webContents.openDevTools();
  }
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });

// ─── Helpers ───────────────────────────────────────────────────────────────────
function getPythonPath() {
  // In packaged app, use bundled python scripts; in dev use system python
  const isPacked = app.isPackaged;
  const scriptDir = isPacked
    ? path.join(process.resourcesPath, 'python')
    : path.join(__dirname, '../../python');
  return scriptDir;
}

function runPython(scriptName, args, onData, onError, onClose) {
  const scriptDir = getPythonPath();
  const scriptPath = path.join(scriptDir, scriptName);
  const py = spawn('python3', [scriptPath, ...args]);

  py.stdout.on('data', (d) => onData && onData(d.toString()));
  py.stderr.on('data', (d) => onError && onError(d.toString()));
  py.on('close', (code) => onClose && onClose(code));

  return py; // return process so we can kill it
}

// ─── Window controls IPC ────────────────────────────────────────────────────────
ipcMain.on('window-minimize', () => mainWindow.minimize());
ipcMain.on('window-maximize', () => {
  if (mainWindow.isMaximized()) mainWindow.unmaximize();
  else mainWindow.maximize();
});
ipcMain.on('window-close', () => mainWindow.close());

// ─── Settings IPC ──────────────────────────────────────────────────────────────
ipcMain.handle('settings-get', (_, key) => store.get(key));
ipcMain.handle('settings-set', (_, key, value) => { store.set(key, value); return true; });
ipcMain.handle('settings-get-all', () => store.store);

// ─── File dialog ───────────────────────────────────────────────────────────────
ipcMain.handle('dialog-open-files', async (_, opts) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile', 'multiSelections'],
    filters: [
      { name: 'Video/Audio', extensions: ['mp4','mov','avi','mkv','mp3','wav','m4a','webm'] },
      { name: 'Subtitles', extensions: ['srt','vtt'] },
      { name: 'All Files', extensions: ['*'] }
    ],
    ...opts
  });
  return result.filePaths;
});

ipcMain.handle('dialog-save-file', async (_, opts) => {
  const result = await dialog.showSaveDialog(mainWindow, opts);
  return result.filePath;
});

ipcMain.handle('dialog-open-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory']
  });
  return result.filePaths[0];
});

// ─── YouTube Download IPC ──────────────────────────────────────────────────────
const activeDownloads = new Map(); // id -> child process

ipcMain.handle('yt-get-info', async (_, url) => {
  return new Promise((resolve, reject) => {
    let output = '';
    const py = runPython(
      'downloader.py',
      ['info', url],
      (data) => { output += data; },
      (err) => console.error('yt-info err:', err),
      (code) => {
        if (code === 0) {
          try { resolve(JSON.parse(output)); }
          catch (e) { reject(new Error('Failed to parse video info')); }
        } else {
          reject(new Error('Could not fetch video info'));
        }
      }
    );
  });
});

ipcMain.handle('yt-start-download', async (_, { id, url, quality, audioOnly, outputDir }) => {
  const dir = outputDir || store.get('downloadDir') || app.getPath('downloads');
  return new Promise((resolve) => {
    const args = ['download', url, quality, audioOnly ? 'audio' : 'video', dir, id];
    const py = runPython(
      'downloader.py',
      args,
      (data) => {
        // Progress lines: PROGRESS:<percent>:<speed>:<eta>
        if (data.startsWith('PROGRESS:')) {
          const [, pct, speed, eta] = data.trim().split(':');
          mainWindow.webContents.send('dl-progress', { id, pct: parseFloat(pct), speed, eta });
        } else if (data.startsWith('DONE:')) {
          const filePath = data.replace('DONE:', '').trim();
          mainWindow.webContents.send('dl-done', { id, filePath });
        }
      },
      (err) => {
        if (!err.includes('WARNING')) {
          mainWindow.webContents.send('dl-error', { id, error: err.trim() });
        }
      },
      (code) => {
        activeDownloads.delete(id);
        resolve({ success: code === 0 });
      }
    );
    activeDownloads.set(id, py);
  });
});

ipcMain.on('yt-pause-download', (_, id) => {
  const proc = activeDownloads.get(id);
  if (proc) proc.kill('SIGSTOP'); // POSIX pause (Linux/Mac)
});

ipcMain.on('yt-resume-download', (_, id) => {
  const proc = activeDownloads.get(id);
  if (proc) proc.kill('SIGCONT');
});

ipcMain.on('yt-cancel-download', (_, id) => {
  const proc = activeDownloads.get(id);
  if (proc) { proc.kill(); activeDownloads.delete(id); }
});

// ─── AI Translator IPC ─────────────────────────────────────────────────────────
const activeTranslations = new Map();

ipcMain.handle('ai-start-translation', async (_, params) => {
  const { id, filePath, sourceLang, targetLang, gender, options } = params;

  return new Promise((resolve) => {
    const apiKeys = {
      openai: store.get('apiKeys.openai', ''),
      google: store.get('apiKeys.google', ''),
      elevenlabs: store.get('apiKeys.elevenlabs', ''),
    };

    const args = [
      'translate',
      filePath,
      sourceLang,
      targetLang,
      gender,
      JSON.stringify(options),
      JSON.stringify(apiKeys),
      id,
    ];

    const py = runPython(
      'translator.py',
      args,
      (data) => {
        // Step updates: STEP:<stepName>:<percent>
        if (data.startsWith('STEP:')) {
          const [, step, pct] = data.trim().split(':');
          mainWindow.webContents.send('tr-step', { id, step, pct: parseInt(pct) });
        } else if (data.startsWith('RESULT:')) {
          const jsonStr = data.replace('RESULT:', '').trim();
          try {
            const result = JSON.parse(jsonStr);
            mainWindow.webContents.send('tr-done', { id, result });
          } catch (e) {
            mainWindow.webContents.send('tr-error', { id, error: 'Parse error' });
          }
        }
      },
      (err) => {
        if (err.includes('ERROR:')) {
          mainWindow.webContents.send('tr-error', { id, error: err.replace('ERROR:', '').trim() });
        }
      },
      (code) => {
        activeTranslations.delete(id);
        resolve({ success: code === 0 });
      }
    );
    activeTranslations.set(id, py);
  });
});

ipcMain.on('ai-cancel-translation', (_, id) => {
  const proc = activeTranslations.get(id);
  if (proc) { proc.kill(); activeTranslations.delete(id); }
});

ipcMain.handle('ai-render-final', async (_, params) => {
  const { id, subtitles, videoPath, options } = params;
  const outputPath = await dialog.showSaveDialog(mainWindow, {
    defaultPath: path.join(app.getPath('downloads'), 'output_translated.mp4'),
    filters: [{ name: 'Video', extensions: ['mp4'] }]
  });
  if (!outputPath.filePath) return { cancelled: true };

  return new Promise((resolve) => {
    const args = ['render', videoPath, JSON.stringify(subtitles), JSON.stringify(options), outputPath.filePath, id];
    runPython(
      'translator.py',
      args,
      (data) => {
        if (data.startsWith('RENDER:')) {
          const pct = parseInt(data.replace('RENDER:', '').trim());
          mainWindow.webContents.send('render-progress', { id, pct });
        }
      },
      (err) => console.error('render err:', err),
      (code) => resolve({ success: code === 0, outputPath: outputPath.filePath })
    );
  });
});

// ─── Shell helpers ─────────────────────────────────────────────────────────────
ipcMain.on('open-file-in-explorer', (_, filePath) => shell.showItemInFolder(filePath));
ipcMain.on('open-external', (_, url) => shell.openExternal(url));
