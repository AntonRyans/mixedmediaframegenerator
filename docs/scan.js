// Scan tab: upload drawn-on paper sheets, recover nine frames per page as a ZIP.
(function () {
  const $ = id => document.getElementById(id);
  const form = $('scan-form');
  const files = $('scan-images');
  const dropzone = $('scan-dropzone');
  const fileTitle = $('scan-file-title');
  const submit = $('scan-submit');
  const progress = $('scan-progress');
  const fill = $('scan-fill');
  const status = $('scan-status');
  const message = $('scan-message');
  const goPrint = $('scan-go-print');
  const api = (window.APP_CONFIG?.API_URL || '').replace(/\/+$/, '');

  function updateName() {
    const count = files.files.length;
    fileTitle.textContent = count === 0 ? 'Choose scanned PDFs or photos' :
      count === 1 ? files.files[0].name : count + ' scanned sheets selected';
    dropzone.classList.toggle('has-file', Boolean(count));
  }
  files.addEventListener('change', updateName);
  ['dragenter', 'dragover'].forEach(event => dropzone.addEventListener(event, e => {
    e.preventDefault();
    dropzone.classList.add('drag');
  }));
  ['dragleave', 'drop'].forEach(event => dropzone.addEventListener(event, e => {
    e.preventDefault();
    dropzone.classList.remove('drag');
  }));
  dropzone.addEventListener('drop', e => {
    if (!e.dataTransfer.files.length) return;
    files.files = e.dataTransfer.files;
    updateName();
  });

  function busy(value) {
    submit.disabled = value;
    progress.hidden = !value;
    if (value) {
      fill.style.width = '0%';
      fill.classList.remove('indeterminate');
    }
  }
  function report(text, error = false) {
    message.className = 'message ' + (error ? 'error' : 'ok');
    message.textContent = text;
  }
  function downloadZip(blob) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'scanned_frames.zip';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 15000);
  }
  form.addEventListener('submit', e => {
    e.preventDefault();
    message.textContent = '';
    goPrint.hidden = true;
    if (!files.files.length) {
      report('Choose at least one PDF or marked sheet image.', true);
      return;
    }
    // Backend accepts PDFs of multiple pages, or separate image sheets.
    const allowed = /\.(pdf|png|jpe?g|webp)$/i;
    const invalid = Array.from(files.files).find(file => !allowed.test(file.name));
    if (invalid) {
      report('Unsupported file: ' + invalid.name + '. Select PDF, PNG, JPG or WebP.', true);
      return;
    }
    const pdfLimit = (Number($('scan-pdf-max-mb')?.textContent) || 1024) * 1024 * 1024;
    const imageLimit = (Number($('scan-image-max-mb')?.textContent) || 25) * 1024 * 1024;
    const oversized = Array.from(files.files).find(file =>
      file.size > (/\.pdf$/i.test(file.name) ? pdfLimit : imageLimit));
    if (oversized) {
      report('File is too large: ' + oversized.name, true);
      return;
    }
    const xhr = new XMLHttpRequest();
    xhr.open('POST', api + '/scan');
    xhr.responseType = 'blob';
    xhr.upload.onprogress = event => {
      if (event.lengthComputable) {
        const pct = Math.round(event.loaded / event.total * 100);
        fill.style.width = pct + '%';
        status.textContent = 'Uploading sheets… ' + pct + '%';
      }
    };
    xhr.upload.onload = () => {
      fill.style.width = '100%';
      fill.classList.add('indeterminate');
      status.textContent = 'Rendering PDF pages (if any), straightening sheets and cropping frames…';
    };
    xhr.onload = async () => {
      busy(false);
      if (xhr.status === 200) {
        const count = xhr.getResponseHeader('X-Frame-Count');
        const capped = xhr.getResponseHeader('X-Frame-Cap-Hit') === '1';
        const fallback = Number(xhr.getResponseHeader('X-Scan-Fallback-Pages') || 0);
        downloadZip(xhr.response);
        report('Recovered ' + count + ' frames! The ZIP download has started.' +
          (fallback ? ' ' + fallback + ' page(s) needed fallback alignment; check the crops and scan_report.txt inside the ZIP.' : '') +
          (capped ? ' Output stopped at the frame limit.' : ''));
        window.dispatchEvent(new CustomEvent('frames-ready', { detail: { blob: xhr.response } }));
        goPrint.hidden = false;
      } else {
        let error = 'Could not recover those frames.';
        try { error = JSON.parse(await xhr.response.text()).error || error; } catch (_) {}
        report(error, true);
      }
    };
    xhr.onerror = () => { busy(false); report('Could not contact the server.', true); };
    busy(true);
    status.textContent = 'Uploading sheets…';
    xhr.send(new FormData(form));
  });
  goPrint.addEventListener('click', () => {
    document.getElementById('tab-print').click();
  });
})();
