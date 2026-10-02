// Global generation queue: header counter and the queue drawer.

import {byId, node, notify} from './dom.js';
import {t, tr} from '../core/i18n.js';

const STATUS_LABELS = {
  running: t('common.generating'),
  queued: t('common.queued'),
  completed: t('common.done'),
  failed: t('common.failed'),
  cancelled: t('common.cancel'),
  cancelling: t('queue.cancelling'),
  interrupted: t('common.interrupted'),
};
const FINISHED = ['completed', 'failed', 'cancelled', 'interrupted'];
const RETRYABLE = ['failed', 'cancelled', 'interrupted'];

export function createQueue(ctx) {
  let queue = {paused: false, jobs: []};
  let busy = false;

  function actionButton(label, run, danger = false) {
    const button = node('button', label, danger ? 'danger' : '');
    button.type = 'button';
    button.disabled = ctx.preview;
    button.onclick = async () => {
      button.disabled = true;
      try {
        await run();
        await load();
      } catch (error) {
        notify(error.message, true);
      } finally {
        button.disabled = ctx.preview;
      }
    };
    return button;
  }

  function jobRow(job) {
    const row = node('article', undefined, 'q-row');
    if (job.image_url?.startsWith('/outputs/')) {
      const image = node('img');
      image.src = job.image_url;
      image.loading = 'lazy';
      image.alt = t('queue.result');
      row.append(image);
    }

    const main = node('div', undefined, 'q-main');
    const lab = job.kind === 'lab';
    const title = ['tag', 'post'].includes(job.kind)
      ? tr(job.title)
      : lab
        ? t('queue.lab', [tr(job.lab_variant) || t('queue.single_generation')])
        : `${job.character_id} / ${job.outfit_id} · ${job.expression_id} ${job.expression_name || ''}`;
    const detail =
      job.kind === 'post'
        ? STATUS_LABELS[job.status] || job.status
        : job.kind === 'tag'
          ? `${STATUS_LABELS[job.status] || job.status}${job.tag_count != null ? t('queue.tags', [job.tag_count]) : ''}`
          : lab
            ? t('queue.seed', [STATUS_LABELS[job.status] || job.status, job.seed])
            : t('queue.seed_2', [
                STATUS_LABELS[job.status] || job.status,
                job.category?.toUpperCase() || '',
                job.seed,
              ]);
    main.append(node('strong', title), node('p', detail));
    if (job.error) main.append(node('p', tr(job.error), 'q-error'));
    row.append(main);

    const buttons = node('div', undefined, 'q-actions');
    if (['running', 'queued'].includes(job.status)) {
      buttons.append(
        actionButton(t('common.cancel'), () => ctx.api(`/api/jobs/${job.id}/cancel`, {}), true),
      );
    }
    if (RETRYABLE.includes(job.status)) {
      buttons.append(
        actionButton(t('queue.retry'), () => ctx.api(`/api/jobs/${job.id}/retry`, {})),
      );
    }
    if (FINISHED.includes(job.status)) {
      buttons.append(
        actionButton(t('queue.remove_from_history'), () =>
          ctx.api(`/api/jobs/${job.id}/remove`, {}),
        ),
      );
    }
    row.append(buttons);
    return row;
  }

  function render() {
    const counts = {};
    for (const job of queue.jobs) counts[job.status] = (counts[job.status] || 0) + 1;
    const active = (counts.running || 0) + (counts.cancelling || 0);
    const waiting = counts.queued || 0;
    byId('global-queue-count').textContent = t('queue.running_queued', [active, waiting]);
    if (!byId('queue-drawer').open) return;

    byId('queue-state').textContent = t('queue.running_queued_done', [
      queue.paused ? t('queue.pause') : t('common.running'),
      active,
      waiting,
      counts.completed || 0,
    ]);

    const pauseLabel = queue.paused ? t('queue.resume') : t('queue.pause_after_the_current_job');
    const pausePath = '/api/queue/' + (queue.paused ? 'resume' : 'pause');
    byId('queue-actions').replaceChildren(
      actionButton(pauseLabel, () => ctx.api(pausePath, {})),
      actionButton(
        t('queue.cancel_queued_jobs'),
        async () => {
          if (confirm(t('queue.cancel_all_queued_jobs_the_image'))) {
            await ctx.api('/api/queue/clear', {});
          }
        },
        true,
      ),
      actionButton(t('queue.clear_finished'), async () => {
        if (confirm(t('queue.clear_finished_jobs_from_the_history'))) {
          await ctx.api('/api/queue/clear-finished', {});
        }
      }),
    );

    const rows = [...queue.jobs].reverse().map(jobRow);
    byId('queue-rows').replaceChildren(
      ...(rows.length ? rows : [node('p', t('queue.no_jobs'), 'muted')]),
    );
  }

  async function load() {
    if (busy) return;
    busy = true;
    try {
      queue = await ctx.api('/api/jobs');
      render();
    } catch {
      byId('global-queue-count').textContent = t('queue.check_the_connection');
    } finally {
      busy = false;
    }
  }

  byId('queue-open').onclick = () => {
    byId('queue-drawer').showModal();
    render();
    load();
  };
  byId('queue-close').onclick = () => byId('queue-drawer').close();

  return {load};
}
