// Print tab: lay frames out 9 per page (3 x 3) and print them.
// Runs entirely in the browser; uses readZip() from zip.js.
(function () {
  const PER_PAGE = 9;
  const PAPERS = { a4: [210, 297], letter: [215.9, 279.4] }; // mm, portrait
  const PX_PER_MM = 96 / 25.4;

  const $ = id => document.getElementById(id);
  const sheet = $('sheet');
  const statusEl = $('print-status');
  const options = $('print-options');
  const useLast = $('use-last');
  const filesInput = $('print-files');
  const paperSel = $('paper');
  const orientSel = $('orientation');
  const fromInput = $('range-from');
  const toInput = $('range-to');
  const namesBox = $('show-names');
  const printBtn = $('print-btn');

  const pageStyle = document.createElement('style');
  document.head.appendChild(pageStyle);

  let frames = [];        // { name, url, w, h }
  let pendingZip = null;  // zip from the Extract tab, not unpacked yet
  let renderToken = 0;

  function setStatus(text, isError) {
    statusEl.textContent = text;
    statusEl.classList.toggle('error', Boolean(isError));
  }

  function stem(name) {
    return name.replace(/\.[^.]+$/, '');
  }

  function naturalSort(list) {
    return list.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
  }

  function measure(url) {
    return new Promise(resolve => {
      const img = new Image();
      img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight });
      img.onerror = () => resolve({ w: 0, h: 0 });
      img.src = url;
    });
  }

  // --- Loading frames ------------------------------------------------------
  async function loadFiles(list) {
    // list: [{ name, blob }]
    if (!list.length) throw new Error('No images found.');
    frames.forEach(f => URL.revokeObjectURL(f.url));
    frames = naturalSort(list).map(f => ({ name: f.name, url: URL.createObjectURL(f.blob), w: 0, h: 0 }));

    fromInput.max = toInput.max = frames.length;
    fromInput.value = 1;
    toInput.value = frames.length;
    options.hidden = false;
    await render();
  }

  async function loadFromZipBlob(blob) {
    setStatus('Unpacking frames…');
    try {
      await loadFiles(await readZip(blob));
    } catch (err) {
      clearSheet();
      setStatus(err.message || 'Couldn’t read that file.', true);
    }
  }

  async function loadFromPicker(fileList) {
    const picked = Array.from(fileList);
    if (!picked.length) return;
    const zip = picked.find(f => /\.zip$/i.test(f.name) || f.type === 'application/zip');
    if (zip) return loadFromZipBlob(zip);

    const images = picked.filter(f => f.type.startsWith('image/'));
    if (!images.length) {
      clearSheet();
      setStatus('Please choose a .zip of frames or some image files.', true);
      return;
    }
    setStatus('Loading images…');
    try {
      await loadFiles(images.map(f => ({ name: f.name, blob: f })));
    } catch (err) {
      clearSheet();
      setStatus(err.message, true);
    }
  }

  function clearSheet() {
    renderToken++;
    sheet.textContent = '';
    options.hidden = true;
    printBtn.disabled = true;
    pageStyle.textContent = '';
  }

  // --- Layout --------------------------------------------------------------
  function selectedRange() {
    const n = frames.length;
    let from = Math.round(Number(fromInput.value)) || 1;
    let to = Math.round(Number(toInput.value)) || n;
    from = Math.min(Math.max(from, 1), n);
    to = Math.min(Math.max(to, 1), n);
    if (from > to) [from, to] = [to, from];
    return [from, to];
  }

  function updateZoom() {
    const width = sheet.clientWidth;
    const pw = parseFloat(sheet.style.getPropertyValue('--pw'));
    if (width > 0 && pw > 0) sheet.style.setProperty('--zoom', String(width / (pw * PX_PER_MM)));
  }

  async function render() {
    if (!frames.length) return;
    const token = ++renderToken;
    const [from, to] = selectedRange();
    const chosen = frames.slice(from - 1, to);

    // Work out orientation (auto = match the first selected frame).
    let landscape = orientSel.value === 'landscape';
    if (orientSel.value === 'auto') {
      const first = chosen[0];
      if (!first.w) Object.assign(first, await measure(first.url));
      if (token !== renderToken) return;
      landscape = first.w >= first.h;
    }
    const [short, long] = PAPERS[paperSel.value];
    const pw = landscape ? long : short;
    const ph = landscape ? short : long;

    sheet.style.setProperty('--pw', pw);
    sheet.style.setProperty('--ph', ph);
    pageStyle.textContent = `@page { size: ${pw}mm ${ph}mm; margin: 0; }`;

    const fragment = document.createDocumentFragment();
    for (let i = 0; i < chosen.length; i += PER_PAGE) {
      const page = document.createElement('div');
      page.className = 'page';
      chosen.slice(i, i + PER_PAGE).forEach(frame => {
        const fig = document.createElement('figure');
        const img = document.createElement('img');
        img.src = frame.url;
        img.alt = frame.name;
        fig.appendChild(img);
        if (namesBox.checked) {
          const cap = document.createElement('figcaption');
          cap.textContent = stem(frame.name);
          fig.appendChild(cap);
        }
        page.appendChild(fig);
      });
      fragment.appendChild(page);
    }
    sheet.textContent = '';
    sheet.appendChild(fragment);
    updateZoom();

    const pages = Math.ceil(chosen.length / PER_PAGE);
    setStatus(
      chosen.length + (chosen.length === 1 ? ' frame' : ' frames') + ' on ' +
      pages + (pages === 1 ? ' page' : ' pages') +
      ' (' + (landscape ? 'landscape' : 'portrait') + ', ' + paperSel.options[paperSel.selectedIndex].text + ')'
    );
    printBtn.disabled = false;
  }

  // --- Events --------------------------------------------------------------
  window.addEventListener('frames-ready', e => {
    pendingZip = e.detail.blob;
    useLast.disabled = false;
  });

  window.addEventListener('tabchange', e => {
    if (e.detail !== 'print') return;
    if (pendingZip) {
      const blob = pendingZip;
      pendingZip = null;
      loadFromZipBlob(blob);
    } else {
      updateZoom();
    }
  });

  let lastZip = null;
  window.addEventListener('frames-ready', e => { lastZip = e.detail.blob; });
  useLast.addEventListener('click', () => { if (lastZip) loadFromZipBlob(lastZip); });

  filesInput.addEventListener('change', () => {
    loadFromPicker(filesInput.files);
    filesInput.value = '';
  });

  [paperSel, orientSel, fromInput, toInput, namesBox].forEach(el =>
    el.addEventListener('change', render));

  window.addEventListener('resize', updateZoom);

  printBtn.addEventListener('click', async () => {
    const imgs = Array.from(sheet.querySelectorAll('img'));
    await Promise.all(imgs.map(img => img.decode().catch(() => {})));
    window.print();
  });
})();
