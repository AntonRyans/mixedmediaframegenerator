// Minimal in-browser zip reader (no dependencies).
// Handles "stored" and "deflate" entries, which covers zips made by this app
// and by normal zip tools. Returns only the image files inside the zip.

const IMAGE_TYPES = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  webp: 'image/webp',
  gif: 'image/gif',
  bmp: 'image/bmp',
};

function imageTypeFor(name) {
  const m = /\.([a-z0-9]+)$/i.exec(name);
  return m ? IMAGE_TYPES[m[1].toLowerCase()] || null : null;
}

async function readZip(source) {
  const buf = source instanceof ArrayBuffer ? source : await source.arrayBuffer();
  const view = new DataView(buf);
  const bytes = new Uint8Array(buf);
  const notZip = new Error('That doesn’t look like a valid zip file.');

  // Find the "end of central directory" record, scanning back from the end.
  let eocd = -1;
  const stop = Math.max(0, buf.byteLength - 22 - 65535);
  for (let i = buf.byteLength - 22; i >= stop; i--) {
    if (view.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw notZip;

  const count = view.getUint16(eocd + 10, true);
  let p = view.getUint32(eocd + 16, true);
  if (count === 0xffff || p === 0xffffffff) {
    throw new Error('That zip uses a format this page can’t read (Zip64).');
  }

  const utf8 = new TextDecoder();
  const entries = [];
  for (let n = 0; n < count; n++) {
    if (p + 46 > buf.byteLength || view.getUint32(p, true) !== 0x02014b50) throw notZip;
    const flags = view.getUint16(p + 8, true);
    const method = view.getUint16(p + 10, true);
    const compressedSize = view.getUint32(p + 20, true);
    const nameLen = view.getUint16(p + 28, true);
    const extraLen = view.getUint16(p + 30, true);
    const commentLen = view.getUint16(p + 32, true);
    const localOffset = view.getUint32(p + 42, true);
    const name = utf8.decode(bytes.subarray(p + 46, p + 46 + nameLen));
    p += 46 + nameLen + extraLen + commentLen;
    entries.push({ name, flags, method, compressedSize, localOffset });
  }

  const files = [];
  for (const e of entries) {
    const base = e.name.split('/').pop();
    const type = imageTypeFor(base);
    // Skip folders, non-images, hidden files and macOS metadata.
    if (!type || !base || base.startsWith('.') || e.name.startsWith('__MACOSX/')) continue;
    if (e.flags & 1) throw new Error('That zip is password-protected.');

    if (view.getUint32(e.localOffset, true) !== 0x04034b50) throw notZip;
    const nameLen = view.getUint16(e.localOffset + 26, true);
    const extraLen = view.getUint16(e.localOffset + 28, true);
    const start = e.localOffset + 30 + nameLen + extraLen;
    const raw = new Blob([bytes.subarray(start, start + e.compressedSize)]);

    let blob;
    if (e.method === 0) {
      blob = new Blob([raw], { type });
    } else if (e.method === 8) {
      const stream = raw.stream().pipeThrough(new DecompressionStream('deflate-raw'));
      blob = new Blob([await new Response(stream).arrayBuffer()], { type });
    } else {
      throw new Error('That zip uses an unsupported compression method.');
    }
    files.push({ name: base, blob });
  }
  return files;
}

if (typeof module !== 'undefined') module.exports = { readZip };
