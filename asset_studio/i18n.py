"""Messages the page shows, written in English with a translation key.

A ``Msg`` is an ordinary English string on the server (logs, exceptions, comparisons) that
also remembers its key and values. ``wire`` turns it into ``{"i18n": key, "params": ...,
"text": english}`` for the page, which translates it with static/i18n/<lang>.json, and for
saved JSON, so a message saved before a restart is still translated afterwards.
"""

from __future__ import annotations


class Msg(str):
    """English text plus the key and values the page translates it with."""

    key: str
    params: dict

    def __new__(cls, key: str, text: str, /, **params):
        # An exception becomes its message so the params stay JSON for the page.
        params = {
            name: message_of(value) if isinstance(value, BaseException) else value
            for name, value in params.items()
        }
        shown = {name: str(value) for name, value in params.items()}
        self = super().__new__(cls, text.format(**shown) if params else text)
        self.key = key
        self.params = params
        return self

    def __reduce__(self):  # copy / deepcopy keep the key
        return (_rebuild, (self.key, str(self), self.params))

    def wire(self) -> dict:
        return {'i18n': self.key, 'params': wire(self.params), 'text': str(self)}


def _rebuild(key, text, params):
    message = str.__new__(Msg, text)
    message.key = key
    message.params = params
    return message


def wire(value):
    """``value`` with every ``Msg`` replaced by its page form (dicts and lists walked)."""
    if isinstance(value, Msg):
        return value.wire()
    if isinstance(value, dict):
        return {key: wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(item) for item in value]
    return value


def message_of(error):
    """The ``Msg`` an exception was raised with, or its text (a message passes through)."""
    if not isinstance(error, BaseException):
        return error if isinstance(error, Msg) else str(error)
    first = error.args[0] if error.args else None
    return first if isinstance(first, Msg) else str(error)
