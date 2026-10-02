// JSON API client. GET when no body is given, POST otherwise.

import {t, tr} from '../core/i18n.js';
export async function api(path, body) {
  let response;
  try {
    response = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: {'Content-Type': 'application/json'},
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(t('Asset Studio 서버에 연결할 수 없습니다.'));
  }

  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(t('서버 응답을 읽지 못했습니다.'));
  }

  if (!response.ok || data.ok === false) {
    const error = new Error(tr(data.error) || t('요청 실패 ({0})', [response.status]));
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}
