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
    throw new Error(t('app.cannot_connect_to_the_asset_studio'));
  }

  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(t('app.could_not_read_the_server_response'));
  }

  if (!response.ok || data.ok === false) {
    const error = new Error(tr(data.error) || t('app.request_failed', [response.status]));
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}
