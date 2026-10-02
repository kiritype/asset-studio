// Small DOM helpers shared by every view.

export const byId = (id) => document.getElementById(id);

export function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

let toastTimer;

/** Show a short status message at the top of the page. */
export function notify(text, isError = false) {
  const toast = byId('studio-toast');
  toast.textContent = text;
  toast.className = isError ? 'error' : '';
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(
    () => {
      toast.hidden = true;
    },
    isError ? 12000 : 5500,
  );
}
