const API_URL = (window.APP_CONFIG && window.APP_CONFIG.API_URL || '').replace(/\/+$/, '');

const form = document.getElementById('form');
const fileInput = document.getElementById('video');
const dropzone = document.getElementById('dropzone');
const dzTitle = document.getElementById('dz-title');
const mode = document.getElementById('mode');
const valueLabel = document.getElementById('value-label');
const valueInput = document.getElementById('value');
const submit = document.getElementById('submit');
const progress = document.getElementById('progress');
const fill = document.getElementById('fill');
const status = document.getElementById('status');
const message = document.getElementById('message');
const serverStatus = document.getElementById('server-status');

const goPrint = document.getElementById('go-print');

// --- Tabs ------------------------------------------------------------------
const tabButtons = Array.from(document.querySelectorAll('[role="tab"]'));

function showTab(name) {
  tabButtons.forEach(btn => {
    const on = btn.dataset.tab === name;
    btn.setAttribute('aria-selected', String(on));
    btn.tabIndex = on ? 0 : -1;
    document.getElementById('panel-' + btn.dataset.tab).hidden = !on;
  });
  window.dispatchEvent(new CustomEvent('tabchange', { detail: name }));
}

tabButtons.forEach((btn, i) => {
  btn.addEventListener('click', () => showTab(btn.dataset.tab));
  btn.addEventListener('keydown', e => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const next = tabButtons[(i + (e.key === 'ArrowRight' ? 1 : tabButtons.length - 1)) % tabButtons.length];
    next.focus();
    showTab(next.dataset.tab);
  });
});

goPrint.addEventListener('click', () => showTab('print'));

function showMessage(text, isError) {
  message.textContent = text;
  message.className = 'message ' + (isError ? 'error' : 'ok');
}

// --- Wake the backend and read its limits -----------------------------------
// Render's free tier sleeps when idle; asking for /limits on page load wakes it
// up so it is (hopefully) ready by the time the user has picked a file.
async function connectToServer() {
  serverStatus.textContent = 'Connecting to server… (it can take up to a minute to wake up)';
  try {
    const res = await fetch(API_URL + '/limits');
    if (!res.ok) throw new Error('bad status');
    const data = await res.json();
    document.getElementById('max-mb').textContent = data.max_mb;
    document.getElementById('max-frames').textContent = data.max_frames;
    serverStatus.textContent = '';
  } catch (_) {
    serverStatus.textContent = 'Couldn’t reach the server yet. It may still be waking up; try again shortly.';
  }
}
connectToServer();

// --- File picking ----------------------------------------------------------
function updateFileName() {
  const f = fileInput.files[0];
  dzTitle.textContent = f ? f.name : 'Choose a video or drop it here';
  dropzone.classList.toggle('has-file', Boolean(f));
}

mode.addEventListener('change', () => {
  valueLabel.textContent = mode.value === 'fps' ? 'Frames per second' : 'N (1 = every frame)';
  valueInput.value = 1;
});

fileInput.addEventListener('change', updateFileName);

['dragenter', 'dragover'].forEach(evt =>
  dropzone.addEventListener(evt, e => { e.preventDefault(); dropzone.classList.add('drag'); }));
['dragleave', 'drop'].forEach(evt =>
  dropzone.addEventListener(evt, e => { e.preventDefault(); dropzone.classList.remove('drag'); }));
dropzone.addEventListener('drop', e => {
  if (e.dataTransfer.files.length) {
    fileInput.files = e.dataTransfer.files;
    updateFileName();
  }
});

// --- Upload and download ---------------------------------------------------
function setBusy(busy) {
  submit.disabled = busy;
  progress.hidden = !busy;
  if (busy) { fill.style.width = '0%'; fill.classList.remove('indeterminate'); }
}

form.addEventListener('submit', e => {
  e.preventDefault();
  message.textContent = '';
  message.className = 'message';
  goPrint.hidden = true;

  const file = fileInput.files[0];
  if (!file) { showMessage('Please choose a video file first.', true); return; }

  const xhr = new XMLHttpRequest();
  xhr.open('POST', API_URL + '/extract');
  xhr.responseType = 'blob';

  xhr.upload.onprogress = ev => {
    if (ev.lengthComputable) {
      const pct = Math.round((ev.loaded / ev.total) * 100);
      fill.style.width = pct + '%';
      status.textContent = 'Uploading… ' + pct + '%';
    }
  };
  xhr.upload.onload = () => {
    fill.style.width = '100%';
    fill.classList.add('indeterminate');
    status.textContent = 'Extracting frames…';
  };

  xhr.onload = async () => {
    setBusy(false);
    if (xhr.status === 200) {
      const count = xhr.getResponseHeader('X-Frame-Count');
      const capped = xhr.getResponseHeader('X-Frame-Cap-Hit') === '1';
      const stem = file.name.replace(/\.[^.]+$/, '') || 'video';
      const url = URL.createObjectURL(xhr.response);
      const a = document.createElement('a');
      a.href = url;
      a.download = stem + '_frames.zip';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      let text = 'Done! ' + count + ' frames saved to your zip.';
      if (capped) text += ' (Stopped at the per-clip limit.)';
      showMessage(text, false);
      // Hand the zip to the Print tab and offer a shortcut to it.
      window.dispatchEvent(new CustomEvent('frames-ready', { detail: { blob: xhr.response } }));
      goPrint.hidden = false;
    } else {
      let text = 'Something went wrong.';
      try { text = JSON.parse(await xhr.response.text()).error || text; } catch (_) {}
      showMessage(text, true);
    }
  };

  xhr.onerror = () => {
    setBusy(false);
    showMessage('Couldn’t reach the server. It may be waking up; wait a minute and try again.', true);
  };

  setBusy(true);
  status.textContent = 'Uploading…';
  xhr.send(new FormData(form));
});
