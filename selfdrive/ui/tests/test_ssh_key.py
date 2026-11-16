"""Verify SSH key downloads publish on the UI thread and preserve current parameters."""
from types import SimpleNamespace

import pytest
import requests

from openpilot.common.params import Params
from openpilot.selfdrive.ui.widgets import ssh_key
from openpilot.system.ui.lib.multilang import multilang, tr


@pytest.fixture
def fetcher(monkeypatch):
  jobs = []
  monkeypatch.setattr(ssh_key.threading, 'Thread',
                      lambda target, args, daemon: SimpleNamespace(start=lambda: jobs.append(lambda: target(*args))))
  params = Params()
  multilang._language = 'zh-CHS'
  multilang.setup()
  return ssh_key.SshKeyFetcher(params), params, jobs


def response(keys='ssh-ed25519 example-public-key'):
  return SimpleNamespace(text=keys, raise_for_status=lambda: None)


def test_fetch_result_is_saved_only_on_ui_update_and_callback_runs_once(fetcher, monkeypatch):
  worker, params, jobs = fetcher
  calls, results = [], []
  def get(url, timeout):
    calls.append((url, timeout))
    return response()
  monkeypatch.setattr(ssh_key.requests, 'get', get)
  assert worker.fetch('example-user', results.append)
  assert worker.busy and len(jobs) == 1
  jobs.pop(0)()
  assert params.get('GithubUsername') is None
  assert params.get('GithubSshKeys') is None
  assert results == []
  worker.update()
  assert calls == [('https://github.com/example-user.keys', 15)]
  assert params.get('GithubUsername') == 'example-user'
  assert params.get('GithubSshKeys') == 'ssh-ed25519 example-public-key'
  assert not worker.busy
  assert results == [None]
  worker.update()
  assert results == [None]


@pytest.mark.parametrize('failure,source', [
  ('empty', "No SSH keys found for user '{}'"),
  ('timeout', 'Request timed out'),
  ('http', "Unable to fetch SSH keys for user '{}'. Check the username and try again."),
  ('network', 'Unable to fetch SSH keys. Check your internet connection and try again.'),
])
def test_fetch_errors_preserve_previous_keys_and_translate_at_ui_consumption(fetcher, monkeypatch, failure, source):
  worker, params, jobs = fetcher
  params.put('GithubUsername', 'saved-user', block=True)
  params.put('GithubSshKeys', 'ssh-ed25519 saved-public-key', block=True)
  def get(*args, **kwargs):
    if failure == 'empty':
      return response('   ')
    raise {'timeout': requests.Timeout, 'http': requests.HTTPError, 'network': requests.ConnectionError}[failure]()
  monkeypatch.setattr(ssh_key.requests, 'get', get)
  results = []
  worker.fetch('new-user', results.append)
  jobs.pop(0)()
  multilang._language = 'en'
  multilang.setup()
  worker.update()
  assert results[0]() == source.format('new-user')
  multilang._language = 'zh-CHS'
  multilang.setup()
  assert results[0]() == tr(source).format('new-user')
  assert worker.snapshot() == ('saved-user', 'ssh-ed25519 saved-public-key')
  assert not worker.busy


@pytest.mark.parametrize('failure', [False, True])
def test_external_key_change_during_fetch_is_not_overwritten_or_cleared(fetcher, monkeypatch, failure):
  worker, params, jobs = fetcher
  def get(*args, **kwargs):
    if failure:
      raise requests.Timeout()
    return response()
  monkeypatch.setattr(ssh_key.requests, 'get', get)
  results = []
  worker.fetch('original', results.append)
  jobs.pop(0)()
  params.put('GithubUsername', 'external', block=True)
  params.put('GithubSshKeys', 'ssh-ed25519 external-public-key', block=True)
  worker.update()
  assert worker.snapshot() == ('external', 'ssh-ed25519 external-public-key')
  assert results[0]() == tr('SSH keys changed. Reopen the settings and try again.')


def test_clear_invalidates_inflight_result_and_allows_new_request(fetcher, monkeypatch):
  worker, params, jobs = fetcher
  monkeypatch.setattr(ssh_key.requests, 'get', lambda *args, **kwargs: response())
  old, new = [], []
  worker.fetch('old-user', old.append)
  first = jobs.pop(0)
  worker.clear()
  assert not worker.busy
  worker.fetch('new-user', new.append)
  first()
  worker.update()
  assert worker.busy
  assert old == [] and new == []
  assert params.get('GithubSshKeys') is None
  jobs.pop(0)()
  worker.update()
  assert params.get('GithubUsername') == 'new-user'
  assert new == [None]


def test_duplicate_fetch_is_rejected_and_failure_can_retry(fetcher, monkeypatch):
  worker, params, jobs = fetcher
  results = []
  monkeypatch.setattr(ssh_key.requests, 'get', lambda *args, **kwargs: response(''))
  assert worker.fetch('first', results.append)
  assert not worker.fetch('second', results.append)
  assert len(jobs) == 1
  jobs.pop(0)()
  worker.update()
  assert results[0]()
  monkeypatch.setattr(ssh_key.requests, 'get', lambda *args, **kwargs: response())
  assert worker.fetch('second', results.append)
  jobs.pop(0)()
  worker.update()
  assert params.get('GithubUsername') == 'second'
  assert results[-1] is None


@pytest.mark.parametrize('has_previous', [False, True])
def test_partial_save_failure_restores_previous_pair_and_reports_failure(fetcher, monkeypatch, has_previous):
  worker, params, jobs = fetcher
  if has_previous:
    params.put('GithubUsername', 'old', block=True)
    params.put('GithubSshKeys', 'ssh-ed25519 old-public-key', block=True)
  saved = worker.snapshot()
  class Store:
    def get(self, key):
      return params.get(key)
    def put(self, key, value, block=True):
      if key == 'GithubUsername' and value == 'new':
        raise OSError('write failed')
      params.put(key, value, block=block)
    def remove(self, key):
      params.remove(key)
  monkeypatch.setattr(worker, '_params', Store())
  monkeypatch.setattr(ssh_key.requests, 'get', lambda *args, **kwargs: response())
  results = []
  worker.fetch('new', results.append)
  jobs.pop(0)()
  worker.update()
  assert worker.snapshot() == saved
  assert results[0]() == tr('Unable to save SSH keys. Try again.')
  assert not worker.busy


def test_slow_ssh_http_request_keeps_ui_polling_nonblocking(monkeypatch):
  import threading
  entered, release, finished = threading.Event(), threading.Event(), threading.Event()
  params = Params()
  worker = ssh_key.SshKeyFetcher(params)
  def get(*args, **kwargs):
    entered.set()
    try:
      assert release.wait(2)
      return response()
    finally:
      finished.set()
  monkeypatch.setattr(ssh_key.requests, 'get', get)
  results = []
  worker.fetch('example-user', results.append)
  try:
    assert entered.wait(1)
    for _ in range(3):
      worker.update()
      assert worker.busy and results == []
      assert params.get('GithubSshKeys') is None
  finally:
    release.set()
  assert finished.wait(1)
  # The worker publishes only after the mocked HTTP call returns.
  import time
  deadline = time.monotonic() + 1
  while worker._results.empty() and time.monotonic() < deadline:
    time.sleep(0.01)
  worker.update()
  assert results == [None]
  assert params.get('GithubUsername') == 'example-user'


def test_fetch_thread_start_failure_is_reported_and_unlocks_retry(fetcher, monkeypatch):
  worker, _, _ = fetcher
  def failed_start():
    raise RuntimeError('unable to start thread')
  monkeypatch.setattr(ssh_key.threading, 'Thread', lambda **kwargs: SimpleNamespace(start=failed_start))
  results = []
  worker.fetch('example-user', results.append)
  worker.update()
  assert results[0]() == tr('Unable to fetch SSH keys. Check your internet connection and try again.')
  assert not worker.busy
