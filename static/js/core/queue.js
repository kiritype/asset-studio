// Global generation queue: header counter and the queue drawer.

import {byId, node, notify} from './dom.js';
import {t, tr} from '../core/i18n.js';

const STATUS_LABELS = {
  running: t('생성 중'),
  queued: t('대기'),
  completed: t('완료'),
  failed: t('실패'),
  cancelled: t('취소'),
  cancelling: t('취소 중'),
  interrupted: t('중단'),
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
      image.alt = t('생성 결과');
      row.append(image);
    }

    const main = node('div', undefined, 'q-main');
    const lab = job.kind === 'lab';
    const title = ['tag', 'post'].includes(job.kind)
      ? tr(job.title)
      : lab
        ? t('실험실 · {0}', [tr(job.lab_variant) || t('단일 생성')])
        : `${job.character_id} / ${job.outfit_id} · ${job.expression_id} ${job.expression_name || ''}`;
    const detail =
      job.kind === 'post'
        ? STATUS_LABELS[job.status] || job.status
        : job.kind === 'tag'
          ? `${STATUS_LABELS[job.status] || job.status}${job.tag_count != null ? t(' · 태그 {0}개', [job.tag_count]) : ''}`
          : lab
            ? t('{0} · 시드 {1}', [STATUS_LABELS[job.status] || job.status, job.seed])
            : t('{0} · {1} · 시드 {2}', [
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
        actionButton(t('취소'), () => ctx.api(`/api/jobs/${job.id}/cancel`, {}), true),
      );
    }
    if (RETRYABLE.includes(job.status)) {
      buttons.append(actionButton(t('재시도'), () => ctx.api(`/api/jobs/${job.id}/retry`, {})));
    }
    if (FINISHED.includes(job.status)) {
      buttons.append(actionButton(t('기록 삭제'), () => ctx.api(`/api/jobs/${job.id}/remove`, {})));
    }
    row.append(buttons);
    return row;
  }

  function render() {
    const counts = {};
    for (const job of queue.jobs) counts[job.status] = (counts[job.status] || 0) + 1;
    const active = (counts.running || 0) + (counts.cancelling || 0);
    const waiting = counts.queued || 0;
    byId('global-queue-count').textContent = t('{0} 진행 · {1} 대기', [active, waiting]);
    if (!byId('queue-drawer').open) return;

    byId('queue-state').textContent = t('{0} · 진행 {1} · 대기 {2} · 완료 {3}', [
      queue.paused ? t('일시정지') : t('실행 중'),
      active,
      waiting,
      counts.completed || 0,
    ]);

    const pauseLabel = queue.paused ? t('재개') : t('다음 작업부터 일시정지');
    const pausePath = '/api/queue/' + (queue.paused ? 'resume' : 'pause');
    byId('queue-actions').replaceChildren(
      actionButton(pauseLabel, () => ctx.api(pausePath, {})),
      actionButton(
        t('대기 작업 취소'),
        async () => {
          if (confirm(t('대기 중인 작업을 모두 취소할까요? 진행 중인 이미지는 계속 생성됩니다.'))) {
            await ctx.api('/api/queue/clear', {});
          }
        },
        true,
      ),
      actionButton(t('종료 기록 지우기'), async () => {
        if (confirm(t('종료된 작업 기록을 지울까요? 이미지와 메타데이터는 보존됩니다.'))) {
          await ctx.api('/api/queue/clear-finished', {});
        }
      }),
    );

    const rows = [...queue.jobs].reverse().map(jobRow);
    byId('queue-rows').replaceChildren(
      ...(rows.length ? rows : [node('p', t('등록된 작업이 없습니다.'), 'muted')]),
    );
  }

  async function load() {
    if (busy) return;
    busy = true;
    try {
      queue = await ctx.api('/api/jobs');
      render();
    } catch {
      byId('global-queue-count').textContent = t('연결 확인 필요');
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
