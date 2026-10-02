// Entry point: wires the views, routing, the queue drawer and the ComfyUI status badge.

import {api} from './core/api.js';
import {byId, notify} from './core/dom.js';
import {loadPreferences} from './core/preferences.js';
import {createQueue} from './core/queue.js';
import {createGallery} from './views/gallery.js';
import {createJobs} from './views/jobs.js';
import {createLab} from './views/lab.js';
import {createLora} from './views/lora.js';
import {createLibrary} from './views/prompts.js';
import {createSettings} from './views/settings.js';
import {createTools} from './views/tools.js';
import {t, tr, translatePage} from './core/i18n.js';

const QUEUE_POLL_MS = 3000;
const STATUS_POLL_MS = 7000;
const DEFAULT_ROUTE = '/jobs';

const info = await api('/api/app').catch(() => ({preview: true}));
await loadPreferences(api);
translatePage();
byId('preview-banner').hidden = !info.preview;

// Other tabs are told when the prompt library changes so they can reload it.
const channel =
  typeof BroadcastChannel !== 'undefined'
    ? new BroadcastChannel('asset-studio-library-updates')
    : null;
const announceLibraryChange = () => window.dispatchEvent(new Event('studio-library-changed'));
channel?.addEventListener('message', announceLibraryChange);

const ctx = {
  api,
  notify,
  preview: Boolean(info.preview),
  navigate,
  onQueueChanged: () => queue.load(),
  onLibraryChanged() {
    channel?.postMessage({type: 'changed'});
    announceLibraryChange();
  },
};
const queue = createQueue(ctx);

const views = {
  '/prompts': createLibrary(ctx),
  '/jobs': createJobs(ctx),
  '/lab': createLab(ctx),
  '/tools': createTools(ctx),
  '/lora': createLora(ctx),
  '/gallery': createGallery(ctx),
  '/settings': createSettings(ctx),
};
for (const view of Object.values(views)) {
  view.element.hidden = true;
  byId('studio-content').append(view.element);
}

let activeView = null;
let routeId = 0;

function navigate(path) {
  const url = new URL(path, location.origin);
  if (url.origin !== location.origin) return;
  history.pushState(null, '', url.pathname + url.search);
  route();
}

async function route() {
  const id = ++routeId;
  const pathname = views[location.pathname] ? location.pathname : DEFAULT_ROUTE;
  if (location.pathname !== pathname) history.replaceState(null, '', pathname + location.search);

  if (activeView) {
    activeView.leave?.();
    activeView.element.hidden = true;
  }
  activeView = views[pathname];
  activeView.element.hidden = false;

  for (const link of document.querySelectorAll('[data-route]')) {
    if (link.pathname === pathname) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }

  try {
    await activeView.enter(new URLSearchParams(location.search));
  } catch (error) {
    if (id === routeId) notify(error.message, true);
  }
}

document.addEventListener('click', (event) => {
  const link = event.target.closest('a[data-route]');
  const plainClick = !event.ctrlKey && !event.metaKey && !event.shiftKey && event.button === 0;
  if (link && plainClick) {
    event.preventDefault();
    navigate(link.href);
  }
});
window.addEventListener('popstate', route);
byId('runtime-status').onclick = () => navigate('/settings');

let statusBusy = false;

async function loadStatus() {
  if (statusBusy) return;
  statusBusy = true;
  const dot = document.querySelector('.runtime-dot');
  try {
    const [status, gpu] = await Promise.all([
      api('/api/connection/status'),
      api('/api/gpu').catch(() => null),
    ]);
    let label = t('ComfyUI 연결됨');
    if (status.operation) label = t('실행 제어 중');
    else if (!status.connected) label = t('ComfyUI 연결 안 됨');
    else if (gpu?.holder)
      label = `GPU: ${tr(gpu.label)}${gpu.state_label ? ` · ${tr(gpu.state_label)}` : ''}`;
    else if (gpu?.waiting) label = t('GPU 대기 중 · 다른 프로그램');
    else if (status.running) label = t('ComfyUI 생성 중');
    byId('runtime-label').textContent = label;
    dot.className = `runtime-dot ${status.connected ? 'online' : 'offline'}`;
  } catch {
    byId('runtime-label').textContent = t('서버 연결 안 됨');
    dot.className = 'runtime-dot offline';
  } finally {
    statusBusy = false;
  }
}

await route();
queue.load();
loadStatus();
setInterval(() => {
  if (!document.hidden) queue.load();
}, QUEUE_POLL_MS);
setInterval(() => {
  if (!document.hidden) loadStatus();
}, STATUS_POLL_MS);
