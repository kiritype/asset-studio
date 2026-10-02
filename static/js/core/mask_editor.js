// Brush editor for a mask over an image: paint to add, erase to remove, undo / redo,
// zoom and pan. The mask is kept at the image's own resolution and exported as an RGBA
// PNG whose alpha says where the mask is (the server reads that channel).
//
// Keys: B brush, E eraser, [ ] size, Ctrl+Z undo, Ctrl+Y / Ctrl+Shift+Z redo,
// space + drag or middle button to pan, wheel to zoom, 0 fit, 1 actual size.

import {t} from './i18n.js';

const HISTORY = 30;
const ZOOM_MIN = 0.05;
const ZOOM_MAX = 8;

const el = (tag, cls = '', text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const button = (text, onClick, cls = '', title = '') => {
  const n = el('button', cls, text);
  n.type = 'button';
  if (title) n.title = title;
  n.addEventListener('click', onClick);
  return n;
};
const range = (min, max, value, step = 1) => {
  const n = el('input');
  n.type = 'range';
  n.min = String(min);
  n.max = String(max);
  n.step = String(step);
  n.value = String(value);
  return n;
};

/**
 * ``imageUrl`` is shown under the mask; ``maskUrl`` (optional) is a grayscale mask to start
 * from. ``onSave(blob)`` stores the mask. ``color`` tints the mask overlay. Returns
 * {element, isDirty(), save(), setStatus(text), maskCanvas, onPaint(callback)}.
 */
export function createMaskEditor({
  imageUrl,
  maskUrl,
  width,
  height,
  onSave,
  onChange,
  color = [255, 40, 60],
  background = 'checker',
  preview = false,
}) {
  const root = el('div', 'mask-editor');
  const toolbar = el('div', 'mask-toolbar');
  const viewport = el('div', `mask-viewport mask-bg-${background}`);
  const board = el('div', 'mask-board');
  const image = el('img');
  image.src = imageUrl;
  image.alt = '';
  image.draggable = false;
  const canvas = el('canvas', 'mask-canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d', {willReadFrequently: true});
  const cursor = el('div', 'mask-cursor');
  // Result preview: the image with the mask as its alpha (for "keep" masks).
  const previewCanvas = el('canvas', 'mask-preview');
  previewCanvas.width = width;
  previewCanvas.height = height;
  previewCanvas.hidden = true;
  board.append(image, previewCanvas, canvas);
  viewport.append(board, cursor);

  const paintListeners = new Set();
  let mode = 'brush';
  let size = Math.max(8, Math.round(Math.max(width, height) / 40));
  let scale = 1;
  let offset = {x: 0, y: 0};
  let dirty = false;
  let drawing = null;
  let panning = null;
  let spaceHeld = false;
  let userView = false;
  const undo = [];
  const redo = [];

  // ---- toolbar ------------------------------------------------------------------------

  const brush = button(t('mask.brush'), () => setMode('brush'), '', 'B');
  const eraser = button(t('mask.eraser'), () => setMode('eraser'), '', 'E');
  const sizeInput = range(2, Math.max(64, Math.round(Math.max(width, height) / 4)), size);
  const sizeLabel = el('span', 'mask-size');
  const sizeBox = el('label', 'mask-group');
  sizeBox.append(el('span', '', t('common.size')), sizeInput, sizeLabel);
  const undoButton = button(t('mask.undo'), restoreUndo, '', 'Ctrl+Z');
  const redoButton = button(t('mask.redo'), restoreRedo, '', 'Ctrl+Y');
  const fitButton = button(t('common.fit_to_screen'), () => ((userView = false), fit()), '', '0');
  const actualButton = button('100%', () => zoomTo(1), '', '1');
  const zoomLabel = el('span', 'mask-size');
  const show = el('input');
  show.type = 'checkbox';
  show.checked = true;
  const opacity = range(10, 100, 55);
  const overlayBox = el('label', 'mask-group');
  overlayBox.append(show, el('span', '', t('mask.show_mask')), opacity);
  const backgroundSelect = el('select');
  for (const [value, text] of [
    ['checker', t('mask.checker')],
    ['white', t('mask.white')],
    ['black', t('mask.black')],
  ]) {
    const option = el('option', '', text);
    option.value = value;
    backgroundSelect.append(option);
  }
  backgroundSelect.value = background;
  const backgroundBox = el('label', 'mask-group');
  backgroundBox.append(el('span', '', t('mask.background')), backgroundSelect);
  const status = el('span', 'mask-status');
  const previewInput = el('input');
  previewInput.type = 'checkbox';
  const previewBox = el('label', 'mask-group');
  previewBox.append(previewInput, el('span', '', t('mask.preview_result')));
  previewBox.hidden = !preview;
  function renderPreview() {
    if (!previewInput.checked) return;
    const target = previewCanvas.getContext('2d');
    target.globalCompositeOperation = 'source-over';
    target.clearRect(0, 0, width, height);
    target.drawImage(image, 0, 0, width, height);
    target.globalCompositeOperation = 'destination-in';
    target.drawImage(canvas, 0, 0);
  }
  previewInput.addEventListener('change', () => {
    const on = previewInput.checked;
    previewCanvas.hidden = !on;
    image.style.visibility = on ? 'hidden' : '';
    canvas.style.visibility = on || !show.checked ? 'hidden' : '';
    renderPreview();
  });
  paintListeners.add(renderPreview);
  toolbar.append(
    brush,
    eraser,
    sizeBox,
    undoButton,
    redoButton,
    fitButton,
    actualButton,
    zoomLabel,
    overlayBox,
    backgroundBox,
    previewBox,
    status,
  );
  root.append(toolbar, viewport);

  function setMode(next) {
    mode = next;
    brush.setAttribute('aria-pressed', String(mode === 'brush'));
    eraser.setAttribute('aria-pressed', String(mode === 'eraser'));
  }
  function showSize() {
    sizeLabel.textContent = `${size}px`;
    sizeInput.value = String(size);
  }
  function refreshButtons() {
    undoButton.disabled = !undo.length;
    redoButton.disabled = !redo.length;
  }
  function changed() {
    dirty = true;
    refreshButtons();
    onChange?.(dirty);
    for (const listener of paintListeners) listener();
  }
  sizeInput.addEventListener('input', () => {
    size = Number(sizeInput.value);
    showSize();
  });
  show.addEventListener('change', () => (canvas.style.visibility = show.checked ? '' : 'hidden'));
  opacity.addEventListener('input', () => (canvas.style.opacity = String(opacity.value / 100)));
  backgroundSelect.addEventListener('change', () => {
    viewport.className = `mask-viewport mask-bg-${backgroundSelect.value}`;
  });

  // ---- zoom and pan -----------------------------------------------------------------

  function place() {
    board.style.width = `${width * scale}px`;
    board.style.height = `${height * scale}px`;
    board.style.transform = `translate(${offset.x}px, ${offset.y}px)`;
    zoomLabel.textContent = `${Math.round(scale * 100)}%`;
  }
  function fit() {
    const box = viewport.getBoundingClientRect();
    if (!box.width || !box.height) return;
    scale = Math.min(box.width / width, box.height / height);
    offset = {x: (box.width - width * scale) / 2, y: (box.height - height * scale) / 2};
    place();
  }
  /** Zoom to ``next``, keeping the image point under (cx, cy) in place. */
  function zoomTo(next, cx, cy) {
    userView = true;
    const box = viewport.getBoundingClientRect();
    const x = cx ?? box.width / 2;
    const y = cy ?? box.height / 2;
    const clamped = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next));
    offset = {
      x: x - ((x - offset.x) * clamped) / scale,
      y: y - ((y - offset.y) * clamped) / scale,
    };
    scale = clamped;
    place();
  }
  viewport.addEventListener(
    'wheel',
    (event) => {
      event.preventDefault();
      const box = viewport.getBoundingClientRect();
      zoomTo(
        scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15),
        event.clientX - box.left,
        event.clientY - box.top,
      );
    },
    {passive: false},
  );

  // ---- painting -----------------------------------------------------------------------

  function point(event) {
    const box = canvas.getBoundingClientRect();
    return {
      x: ((event.clientX - box.left) * width) / box.width,
      y: ((event.clientY - box.top) * height) / box.height,
    };
  }
  function stroke(from, to) {
    context.globalCompositeOperation = mode === 'eraser' ? 'destination-out' : 'source-over';
    context.strokeStyle = `rgb(${color.join(',')})`;
    context.fillStyle = context.strokeStyle;
    context.lineWidth = size;
    context.lineCap = 'round';
    context.lineJoin = 'round';
    context.beginPath();
    context.moveTo(from.x, from.y);
    context.lineTo(to.x, to.y);
    context.stroke();
    context.beginPath();
    context.arc(to.x, to.y, size / 2, 0, Math.PI * 2);
    context.fill();
  }
  function moveCursor(event) {
    const box = viewport.getBoundingClientRect();
    const diameter = size * scale;
    cursor.style.width = cursor.style.height = `${diameter}px`;
    cursor.style.left = `${event.clientX - box.left - diameter / 2}px`;
    cursor.style.top = `${event.clientY - box.top - diameter / 2}px`;
    cursor.hidden = !!panning || spaceHeld;
  }
  viewport.addEventListener('pointerdown', (event) => {
    event.preventDefault();
    viewport.setPointerCapture(event.pointerId);
    if (event.button === 1 || spaceHeld) {
      panning = {x: event.clientX - offset.x, y: event.clientY - offset.y};
      userView = true;
      viewport.classList.add('panning');
      return;
    }
    if (event.button !== 0) return;
    undo.push(context.getImageData(0, 0, width, height));
    if (undo.length > HISTORY) undo.shift();
    redo.length = 0;
    drawing = point(event);
    stroke(drawing, drawing);
    changed();
  });
  viewport.addEventListener('pointermove', (event) => {
    moveCursor(event);
    if (panning) {
      offset = {x: event.clientX - panning.x, y: event.clientY - panning.y};
      place();
      return;
    }
    if (!drawing) return;
    const next = point(event);
    stroke(drawing, next);
    drawing = next;
  });
  const finish = () => {
    if (drawing) for (const listener of paintListeners) listener();
    drawing = null;
    panning = null;
    viewport.classList.remove('panning');
  };
  viewport.addEventListener('pointerup', finish);
  viewport.addEventListener('pointercancel', finish);
  viewport.addEventListener('pointerleave', () => (cursor.hidden = true));
  viewport.addEventListener('pointerenter', () => (cursor.hidden = false));

  function restoreUndo() {
    const previous = undo.pop();
    if (!previous) return;
    redo.push(context.getImageData(0, 0, width, height));
    context.putImageData(previous, 0, 0);
    changed();
  }
  function restoreRedo() {
    const next = redo.pop();
    if (!next) return;
    undo.push(context.getImageData(0, 0, width, height));
    context.putImageData(next, 0, 0);
    changed();
  }

  // Shortcuts only while the editor is on the page and no text field has focus.
  function onKey(event) {
    if (!root.isConnected) return document.removeEventListener('keydown', onKey);
    if (event.target.closest?.('input, textarea, select')) return;
    const key = event.key.toLowerCase();
    if (event.ctrlKey && key === 'z' && !event.shiftKey) restoreUndo();
    else if (event.ctrlKey && (key === 'y' || (key === 'z' && event.shiftKey))) restoreRedo();
    else if (event.code === 'Space') {
      spaceHeld = event.type === 'keydown';
      viewport.classList.toggle('can-pan', spaceHeld);
      cursor.hidden = spaceHeld;
    } else if (event.type !== 'keydown' || event.ctrlKey) return;
    else if (key === 'b') setMode('brush');
    else if (key === 'e') setMode('eraser');
    else if (key === '[') ((size = Math.max(2, Math.round(size / 1.25))), showSize());
    else if (key === ']')
      ((size = Math.min(Number(sizeInput.max), Math.round(size * 1.25) + 1)), showSize());
    else if (key === '0') ((userView = false), fit());
    else if (key === '1') zoomTo(1);
    else return;
    event.preventDefault();
  }
  document.addEventListener('keydown', onKey);
  document.addEventListener('keyup', (event) => {
    if (event.code === 'Space' && spaceHeld) onKey(event);
  });

  // ---- loading and saving -----------------------------------------------------------

  async function loadMask() {
    if (!maskUrl) return;
    const response = await fetch(maskUrl, {cache: 'no-store'});
    if (!response.ok) {
      status.textContent = t('common.no_mask_paint_with_the_brush');
      return;
    }
    const bitmap = await createImageBitmap(await response.blob());
    const scratch = document.createElement('canvas');
    scratch.width = width;
    scratch.height = height;
    const scratchContext = scratch.getContext('2d', {willReadFrequently: true});
    scratchContext.drawImage(bitmap, 0, 0, width, height);
    const gray = scratchContext.getImageData(0, 0, width, height);
    const tinted = context.createImageData(width, height);
    for (let i = 0; i < gray.data.length; i += 4) {
      tinted.data[i] = color[0];
      tinted.data[i + 1] = color[1];
      tinted.data[i + 2] = color[2];
      tinted.data[i + 3] = gray.data[i];
    }
    context.putImageData(tinted, 0, 0);
    for (const listener of paintListeners) listener();
  }

  async function save() {
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
    await onSave(blob);
    dirty = false;
    onChange?.(dirty);
  }

  setMode('brush');
  showSize();
  refreshButtons();
  place();
  // Keep the image fitted while the page settles, until the user zooms or pans.
  const sizing = new ResizeObserver(() => {
    if (!root.isConnected) return sizing.disconnect();
    if (viewport.clientWidth && !userView) fit();
  });
  sizing.observe(viewport);
  loadMask().catch(() => {
    status.textContent = t('mask.could_not_load_the_mask');
  });
  return {
    element: root,
    isDirty: () => dirty,
    save,
    setStatus: (text) => (status.textContent = text),
    maskCanvas: canvas,
    /** Called after each stroke and after the mask is loaded. */
    onPaint: (listener) => paintListeners.add(listener),
  };
}
