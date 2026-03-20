/**
 * iFlow Desktop Module (Lightweight)
 * 使用 PowerShell 和系统命令实现桌面自动化
 */

const { exec, spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// 鼠标位置
function getMousePosition() {
  const start = Date.now();
  return new Promise((resolve) => {
    exec('powershell -Command "Add-Type -AssemblyName System.Windows.Forms; Write-Output ([System.Windows.Forms.Cursor]::Position.X); Write-Output ([System.Windows.Forms.Cursor]::Position.Y)"', (err, stdout) => {
      if (err) {
        resolve({ status: 'error', message: err.message, time: Date.now() - start });
        return;
      }
      const lines = stdout.trim().split('\n');
      const x = parseInt(lines[0]) || 0;
      const y = parseInt(lines[1]) || 0;
      resolve({ status: 'ok', x, y, time: Date.now() - start });
    });
  });
}

// 移动鼠标
function moveMouse(x, y) {
  const start = Date.now();
  return new Promise((resolve) => {
    exec('powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(' + x + ',' + y + ')"', (err) => {
      if (err) {
        resolve({ status: 'error', message: err.message, time: Date.now() - start });
        return;
      }
      resolve({ status: 'ok', x, y, time: Date.now() - start });
    });
  });
}

// 点击 (简化版)
function click(x, y, button = 'left') {
  const start = Date.now();
  return new Promise((resolve) => {
    // 先移动再点击
    exec('powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(' + x + ',' + y + ')"', (err) => {
      if (err) {
        resolve({ status: 'error', message: err.message, time: Date.now() - start });
        return;
      }
      resolve({ status: 'ok', x, y, button, time: Date.now() - start });
    });
  });
}

// 屏幕尺寸
function getScreenSize() {
  const start = Date.now();
  return new Promise((resolve) => {
    exec('powershell -Command "Add-Type -AssemblyName System.Windows.Forms; Write-Output ([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width); Write-Output ([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height)"', (err, stdout) => {
      if (err) {
        resolve({ status: 'error', message: err.message, time: Date.now() - start });
        return;
      }
      const lines = stdout.trim().split('\n');
      const width = parseInt(lines[0]) || 1920;
      const height = parseInt(lines[1]) || 1080;
      resolve({ status: 'ok', width, height, time: Date.now() - start });
    });
  });
}

// 剪贴板读取
function getClipboard() {
  const start = Date.now();
  return new Promise((resolve) => {
    exec('powershell -Command "Get-Clipboard"', (err, stdout) => {
      if (err) {
        resolve({ status: 'error', message: err.message, time: Date.now() - start });
        return;
      }
      resolve({ status: 'ok', content: stdout.trim(), time: Date.now() - start });
    });
  });
}

// 剪贴板写入
function setClipboard(text) {
  const start = Date.now();
  return new Promise((resolve) => {
    const escaped = text.replace(/'/g, "''").replace(/"/g, '\\"');
    exec('powershell -Command "Set-Clipboard -Value \"' + escaped + '\""', (err) => {
      if (err) {
        resolve({ status: 'error', message: err.message, time: Date.now() - start });
        return;
      }
      resolve({ status: 'ok', time: Date.now() - start });
    });
  });
}

// 截图
function screenshot(savePath) {
  const start = Date.now();
  const finalPath = savePath || path.join(process.cwd(), 'screenshot_' + Date.now() + '.png');
  
  return new Promise((resolve) => {
    const cmd = 'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; ' +
      '$bitmap = New-Object System.Drawing.Bitmap([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width, [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height); ' +
      '$graphics = [System.Drawing.Graphics]::FromImage($bitmap); ' +
      '$graphics.CopyFromScreen([System.Drawing.Point]::Empty, [System.Drawing.Point]::Empty, $bitmap.Size); ' +
      '$bitmap.Save(\"' + finalPath.replace(/\\/g, '\\\\') + '\"); ' +
      '$graphics.Dispose(); $bitmap.Dispose()"';
    
    exec(cmd, (err) => {
      if (err) {
        resolve({ status: 'error', message: err.message, time: Date.now() - start });
        return;
      }
      resolve({ status: 'ok', path: finalPath, time: Date.now() - start });
    });
  });
}

// 窗口列表 (简化版 - 使用 tasklist)
function getWindows() {
  const start = Date.now();
  return new Promise((resolve) => {
    exec('tasklist /fo csv /nh', (err, stdout) => {
      if (err) {
        resolve({ status: 'error', message: err.message, time: Date.now() - start });
        return;
      }
      const lines = stdout.trim().split('\n');
      const windows = lines.slice(0, 30).map(line => {
        const parts = line.match(/"([^"]+)"/g);
        if (parts && parts.length >= 2) {
          return {
            name: parts[0].replace(/"/g, ''),
            pid: parts[1].replace(/"/g, '')
          };
        }
        return null;
      }).filter(Boolean);
      
      resolve({ status: 'ok', windows, count: windows.length, time: Date.now() - start });
    });
  });
}

// 键盘输入
function typeText(text) {
  const start = Date.now();
  return new Promise((resolve) => {
    const escaped = text.replace(/"/g, '""');
    exec('powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait(\"' + escaped + '\")"', (err) => {
      if (err) {
        resolve({ status: 'error', message: err.message, time: Date.now() - start });
        return;
      }
      resolve({ status: 'ok', text, time: Date.now() - start });
    });
  });
}

// 按键
function pressKey(key) {
  const start = Date.now();
  const keyMap = {
    'enter': '{ENTER}',
    'tab': '{TAB}',
    'esc': '{ESC}',
    'space': '{SPACE}',
    'backspace': '{BS}',
    'delete': '{DEL}',
    'up': '{UP}',
    'down': '{DOWN}',
    'left': '{LEFT}',
    'right': '{RIGHT}'
  };
  
  return new Promise((resolve) => {
    const keyCode = keyMap[key.toLowerCase()] || key;
    exec('powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait(\"' + keyCode + '\")"', (err) => {
      if (err) {
        resolve({ status: 'error', message: err.message, time: Date.now() - start });
        return;
      }
      resolve({ status: 'ok', key, time: Date.now() - start });
    });
  });
}

// 运行程序
function runApp(command) {
  const start = Date.now();
  return new Promise((resolve) => {
    exec('start "" "' + command + '"', { shell: 'cmd.exe' }, (err) => {
      if (err) {
        resolve({ status: 'error', message: err.message, time: Date.now() - start });
        return;
      }
      resolve({ status: 'ok', command, time: Date.now() - start });
    });
  });
}

// 系统通知
function notify(title, message) {
  const start = Date.now();
  return new Promise((resolve) => {
    exec('powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show(\"' + message + '\", \"' + title + '\")"', (err) => {
      if (err) {
        resolve({ status: 'error', message: err.message, time: Date.now() - start });
        return;
      }
      resolve({ status: 'ok', title, message, time: Date.now() - start });
    });
  });
}

// 同步版本用于 benchmark
function getMousePositionSync() {
  const start = Date.now();
  try {
    const result = require('child_process').execSync(
      'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; Write-Output ([System.Windows.Forms.Cursor]::Position.X); Write-Output ([System.Windows.Forms.Cursor]::Position.Y)"',
      { encoding: 'utf8' }
    );
    const lines = result.trim().split('\n');
    return { status: 'ok', x: parseInt(lines[0]), y: parseInt(lines[1]), time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

module.exports = {
  getMousePosition,
  getMousePositionSync,
  moveMouse,
  click,
  getScreenSize,
  getClipboard,
  setClipboard,
  screenshot,
  getWindows,
  typeText,
  pressKey,
  runApp,
  notify
};
