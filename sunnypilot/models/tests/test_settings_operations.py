"""Model settings requests retain meaningful results and preserve active files."""
import asyncio
import hashlib
from types import SimpleNamespace

import pytest
from cereal import custom
from openpilot.common.params import Params
from openpilot.sunnypilot.models import manager as model_manager


@pytest.fixture
def manager(monkeypatch, tmp_path):
  manager = model_manager.ModelManagerSP.__new__(model_manager.ModelManagerSP)
  manager.params = Params()
  manager.active_bundle = None
  manager.selected_bundle = None
  manager.available_models = []
  manager._download_start_times = {}
  manager._download_request = None
  manager.model_fetcher = SimpleNamespace(get_available_bundles=lambda: manager.available_models)
  monkeypatch.setattr(model_manager.Paths, 'model_root', lambda: str(tmp_path / 'models'))
  monkeypatch.setattr(model_manager, 'validate_active_bundle', lambda *args: None)
  monkeypatch.setattr(model_manager, 'get_active_bundle', lambda *args: manager.active_bundle)
  yield manager
  if manager._download_request is not None:
    manager._download_request.close()


class EndIteration(BaseException):
  pass


def run_iteration(manager, monkeypatch):
  def stop():
    raise EndIteration
  monkeypatch.setattr(model_manager, 'Ratekeeper', lambda *args, **kwargs: SimpleNamespace(keep_time=stop))
  with pytest.raises(EndIteration):
    manager.main_thread()


def test_failed_download_remains_available_for_status_and_retry(manager, monkeypatch):
  bundle = custom.ModelManagerSP.ModelBundle.new_message(ref='failed-model', index=7)
  manager.available_models = [bundle]
  manager.params.put('ModelManager_DownloadIndex', 7, block=True)
  def download(bundle, path):
    manager.selected_bundle = bundle
    manager.selected_bundle.status = 'failed'
    raise OSError('network error')
  reports = []
  monkeypatch.setattr(manager, 'download', download)
  monkeypatch.setattr(manager, '_report_status', lambda: reports.append(manager.selected_bundle.ref))
  run_iteration(manager, monkeypatch)
  assert manager.params.get('ModelManager_DownloadIndex') is None
  assert manager.selected_bundle.status == custom.ModelManagerSP.DownloadStatus.failed
  assert reports == ['failed-model']


@pytest.mark.parametrize('cancelled', [False, True])
def test_bundle_terminal_state_keeps_success_and_cancellation_distinct(manager, monkeypatch, tmp_path, cancelled):
  bundle = custom.ModelManagerSP.ModelBundle.new_message(ref='model', index=7,
                                                        models=[{'type': 'supercombo', 'artifact': {'fileName': 'model.onnx'}}])
  manager.params.put('ModelManager_DownloadIndex', 7, block=True)
  async def artifact(artifact, path):
    if cancelled:
      raise model_manager.ModelDownloadCancelled('cancelled')
    artifact.downloadProgress.status = 'downloaded'
    artifact.downloadProgress.progress = 100
  monkeypatch.setattr(manager, '_process_artifact', artifact)
  monkeypatch.setattr(manager, '_report_status', lambda: None)
  if cancelled:
    with pytest.raises(model_manager.ModelDownloadCancelled):
      asyncio.run(manager._download_bundle(bundle, str(tmp_path / 'models')))
    assert manager.active_bundle is None
    assert not manager.params.get('ModelManager_ActiveBundle')
  else:
    asyncio.run(manager._download_bundle(bundle, str(tmp_path / 'models')))
    assert manager.active_bundle.ref == 'model'
    assert manager.params.get('ModelManager_ActiveBundle')['ref'] == 'model'
  assert manager.selected_bundle is None


def test_cache_cleanup_preserves_active_artifacts_metadata_and_chunks(manager, tmp_path):
  root = tmp_path / 'models'
  root.mkdir()
  names = ['active.onnx', 'active.pkl', 'active.onnx.chunk.0', 'unused.onnx', 'unused.pkl']
  for name in names:
    (root / name).write_text(name)
  manager.active_bundle = custom.ModelManagerSP.ModelBundle.new_message(
    ref='active', models=[{'type': 'supercombo', 'artifact': {'fileName': 'active.onnx'}, 'metadata': {'fileName': 'active.pkl'}}])
  manager.clear_model_cache()
  assert {path.name for path in root.iterdir()} == {'active.onnx', 'active.pkl', 'active.onnx.chunk.0'}


def test_cache_cleanup_failure_keeps_request_pending(manager, monkeypatch, tmp_path):
  (tmp_path / 'models').mkdir()
  (tmp_path / 'models' / 'unused').write_text('model')
  def remove(path):
    raise OSError('read-only filesystem')
  monkeypatch.setattr(model_manager.os, 'remove', remove)
  monkeypatch.setattr(manager, '_report_status', lambda: None)
  manager.params.put_bool('ModelManager_ClearCache', True, block=True)
  run_iteration(manager, monkeypatch)
  assert manager.params.get_bool('ModelManager_ClearCache')
  assert (tmp_path / 'models' / 'unused').exists()


def test_empty_cache_cleanup_completes_request(manager, monkeypatch):
  monkeypatch.setattr(manager, '_report_status', lambda: None)
  manager.params.put_bool('ModelManager_ClearCache', True, block=True)
  run_iteration(manager, monkeypatch)
  assert not manager.params.get_bool('ModelManager_ClearCache')


def test_switch_to_default_clears_previous_download_failure(manager, monkeypatch):
  manager.active_bundle = custom.ModelManagerSP.ModelBundle.new_message(ref='old-active')
  manager.selected_bundle = custom.ModelManagerSP.ModelBundle.new_message(ref='failed-model', status='failed')
  monkeypatch.setattr(model_manager, 'get_active_bundle', lambda *args: None)
  monkeypatch.setattr(manager, '_report_status', lambda: None)
  run_iteration(manager, monkeypatch)
  assert manager.active_bundle is None
  assert manager.selected_bundle is None


@pytest.mark.parametrize('terminal', ['success', 'failure', 'cancel'])
@pytest.mark.parametrize('new_index', [7, 11])
def test_old_download_cleanup_preserves_new_request(manager, monkeypatch, terminal, new_index):
  old = custom.ModelManagerSP.ModelBundle.new_message(ref='old-model', index=7)
  new = custom.ModelManagerSP.ModelBundle.new_message(ref='new-model', index=new_index)
  manager.available_models = [old]
  manager.params.put('ModelManager_DownloadIndex', 7, block=True)
  calls = []
  def download(bundle, path):
    calls.append(bundle.ref)
    manager.params.remove('ModelManager_DownloadIndex')
    manager.params.put('ModelManager_DownloadIndex', new_index, block=True)
    if terminal == 'failure':
      manager.selected_bundle = old
      manager.selected_bundle.status = 'failed'
      raise OSError('old download failed')
    if terminal == 'cancel':
      raise model_manager.ModelDownloadCancelled('old download cancelled')
  monkeypatch.setattr(manager, 'download', download)
  monkeypatch.setattr(manager, '_report_status', lambda: None)
  run_iteration(manager, monkeypatch)
  assert manager.params.get('ModelManager_DownloadIndex') == new_index
  assert calls == ['old-model']
  # The following actual service iteration consumes the new request once.
  monkeypatch.setattr(manager, 'download', lambda bundle, path: calls.append(bundle.ref))
  manager.available_models = [new]
  run_iteration(manager, monkeypatch)
  assert manager.params.get('ModelManager_DownloadIndex') is None
  assert calls == ['old-model', 'new-model']


@pytest.mark.parametrize('new_request', [None, 7, 11])
def test_cancel_after_last_artifact_does_not_activate_old_model(manager, monkeypatch, tmp_path, new_request):
  old = custom.ModelManagerSP.ModelBundle.new_message(ref='old-model', index=7,
    models=[{'type': 'supercombo', 'artifact': {'fileName': 'old.onnx'}}])
  active = custom.ModelManagerSP.ModelBundle.new_message(ref='active-model', index=3)
  manager.active_bundle = active
  manager.params.put('ModelManager_ActiveBundle', active.to_dict(), block=True)
  manager.params.put('ModelManager_DownloadIndex', 7, block=True)
  async def artifact(artifact, path):
    artifact.downloadProgress.status = 'downloaded'
    artifact.downloadProgress.progress = 100
    if new_request is None:
      manager.params.remove('ModelManager_DownloadIndex')
    else:
      manager.params.put('ModelManager_DownloadIndex', new_request, block=True)
  monkeypatch.setattr(manager, '_process_artifact', artifact)
  monkeypatch.setattr(manager, '_report_status', lambda: None)
  with pytest.raises(model_manager.ModelDownloadCancelled):
    asyncio.run(manager._download_bundle(old, str(tmp_path / 'models')))
  assert manager.active_bundle.ref == 'active-model'
  assert manager.params.get('ModelManager_ActiveBundle')['ref'] == 'active-model'
  assert manager.params.get('ModelManager_DownloadIndex') == new_request
  assert manager.selected_bundle is None


@pytest.mark.parametrize('new_request', [None, 7, 11])
def test_request_change_after_final_check_cannot_publish_active_model(manager, monkeypatch, tmp_path, new_request):
  old = custom.ModelManagerSP.ModelBundle.new_message(ref='old-model', index=7,
    models=[{'type': 'supercombo', 'artifact': {'fileName': 'old.onnx'}}])
  active = custom.ModelManagerSP.ModelBundle.new_message(ref='active-model', index=3)
  manager.active_bundle = active
  manager.params.put('ModelManager_ActiveBundle', active.to_dict(), block=True)
  manager.params.put('ModelManager_DownloadIndex', 7, block=True)
  async def artifact(artifact, path):
    artifact.downloadProgress.status = 'downloaded'
  monkeypatch.setattr(manager, '_process_artifact', artifact)
  monkeypatch.setattr(manager, '_report_status', lambda: None)
  check = manager._check_download_request
  checks = []
  def change_after_check():
    check()
    checks.append(True)
    if len(checks) == 3:
      manager.params.remove('ModelManager_DownloadIndex')
      if new_request is not None:
        manager.params.put('ModelManager_DownloadIndex', new_request, block=True)
  monkeypatch.setattr(manager, '_check_download_request', change_after_check)
  with pytest.raises(model_manager.ModelDownloadCancelled):
    asyncio.run(manager._download_bundle(old, str(tmp_path / 'models')))
  assert len(checks) == 3
  assert manager.active_bundle.ref == 'active-model'
  assert manager.params.get('ModelManager_ActiveBundle')['ref'] == 'active-model'
  assert manager.params.get('ModelManager_DownloadIndex') == new_request
  assert manager.selected_bundle is None
  assert manager._download_request is None


@pytest.mark.parametrize('chunked', [False, True])
@pytest.mark.parametrize('new_request', [None, 7, 11])
def test_streaming_download_stops_when_its_request_changes(manager, monkeypatch, tmp_path, chunked, new_request):
  artifact = custom.ModelManagerSP.Artifact.new_message(fileName='old.onnx')
  manager.selected_bundle = custom.ModelManagerSP.ModelBundle.new_message(ref='old-model', index=7)
  manager._chunk_size = 4
  manager.params.put('ModelManager_DownloadIndex', 7, block=True)
  monkeypatch.setattr(manager, '_report_status', lambda: None)
  manager._download_request = open(manager.params.get_param_path('ModelManager_DownloadIndex'), 'rb')
  yielded = []

  class Response:
    status = 200
    headers = {'content-length': '8'}
    @property
    def content(self):
      return self
    async def __aenter__(self):
      return self
    async def __aexit__(self, *args):
      pass
    def raise_for_status(self):
      pass
    async def read(self):
      return b'1'
    async def iter_chunked(self, size):
      assert size == 4
      yield b'init'
      if new_request is None:
        manager.params.remove('ModelManager_DownloadIndex')
      else:
        manager.params.put('ModelManager_DownloadIndex', new_request, block=True)
      yielded.append('changed')
      yield b'last'
      yielded.append('finished')

  class Session:
    async def __aenter__(self):
      return self
    async def __aexit__(self, *args):
      pass
    def get(self, url):
      return Response()

  monkeypatch.setattr(model_manager.aiohttp, 'ClientSession', Session)
  download = manager._download_chunked if chunked else manager._download_file
  with pytest.raises(model_manager.ModelDownloadCancelled):
    asyncio.run(download('controlled-file', str(tmp_path / 'old.onnx'), artifact))
  assert yielded == ['changed']
  assert manager.params.get('ModelManager_DownloadIndex') == new_request
  assert artifact.downloadProgress.progress < 100


@pytest.mark.parametrize('new_request', [None, 11])
def test_already_cancelled_bundle_does_not_process_cached_files(manager, monkeypatch, tmp_path, new_request):
  bundle = custom.ModelManagerSP.ModelBundle.new_message(ref='old-model', index=7,
    models=[{'type': 'supercombo', 'artifact': {'fileName': 'cached.onnx'}}])
  if new_request is not None:
    manager.params.put('ModelManager_DownloadIndex', new_request, block=True)
  calls = []
  async def artifact(artifact, path):
    calls.append(artifact.fileName)
  monkeypatch.setattr(manager, '_process_artifact', artifact)
  monkeypatch.setattr(manager, '_report_status', lambda: None)
  with pytest.raises(model_manager.ModelDownloadCancelled):
    asyncio.run(manager._download_bundle(bundle, str(tmp_path / 'models')))
  assert not calls
  assert manager.active_bundle is None
  assert manager.params.get('ModelManager_DownloadIndex') == new_request


@pytest.mark.parametrize('outcome', ['cancel', 'replace', 'failure'])
def test_artifact_cleanup_reports_cancellation_and_failure_distinctly(manager, monkeypatch, tmp_path, outcome):
  bundle = custom.ModelManagerSP.ModelBundle.new_message(ref='old-model', index=7, models=[{
    'type': 'supercombo', 'artifact': {'fileName': 'old.onnx', 'downloadUri': {'uri': 'controlled-file', 'sha256': 'expected-hash'}},
  }])
  active = custom.ModelManagerSP.ModelBundle.new_message(ref='active-model', index=3)
  manager.active_bundle = active
  manager.params.put('ModelManager_ActiveBundle', active.to_dict(), block=True)
  manager.params.put('ModelManager_DownloadIndex', 7, block=True)
  reports = []
  monkeypatch.setattr(manager, '_report_status', lambda: reports.append(
    manager.selected_bundle.status if manager.selected_bundle else None))

  async def verify(path, expected_hash):
    return False
  monkeypatch.setattr(model_manager, 'verify_file', verify)

  async def download(url, path, artifact):
    with open(path, 'wb') as output:
      output.write(b'partial')
    manager._download_start_times[artifact.fileName] = 1
    if outcome == 'failure':
      raise OSError('network error')
    if outcome == 'cancel':
      manager.params.remove('ModelManager_DownloadIndex')
    else:
      manager.params.put('ModelManager_DownloadIndex', 11, block=True)
    manager._check_download_request()
  monkeypatch.setattr(manager, '_download_chunked', download)

  error = OSError if outcome == 'failure' else model_manager.ModelDownloadCancelled
  with pytest.raises(error):
    asyncio.run(manager._download_bundle(bundle, str(tmp_path / 'models')))
  assert not (tmp_path / 'models' / 'old.onnx').exists()
  assert not manager._download_start_times
  assert manager.active_bundle.ref == 'active-model'
  assert manager.params.get('ModelManager_ActiveBundle')['ref'] == 'active-model'
  if outcome == 'failure':
    assert manager.selected_bundle.status == custom.ModelManagerSP.DownloadStatus.failed
    assert custom.ModelManagerSP.DownloadStatus.failed in reports
    assert manager.params.get('ModelManager_DownloadIndex') == 7
  else:
    assert manager.selected_bundle is None
    assert custom.ModelManagerSP.DownloadStatus.failed not in reports
    assert reports[-1] is None
    assert manager.params.get('ModelManager_DownloadIndex') == (None if outcome == 'cancel' else 11)


@pytest.mark.parametrize('chunked', [False, True])
@pytest.mark.parametrize('cancel_and_retry', [False, True])
def test_local_http_download_verifies_cache_and_same_index_retry(manager, monkeypatch, tmp_path, chunked, cancel_and_retry):
  """Exercise actual HTTP, hashing, cache files and activation with small test bytes."""
  from aiohttp import web
  from openpilot.common.file_chunker import read_file_chunked
  parts = [b'controlled-model-part-one', b'controlled-model-part-two']
  payload = b''.join(parts)
  hits = []
  async def serve(request):
    hits.append(request.path)
    if request.path.endswith('.chunkmanifest'):
      return web.Response(body=b'2') if chunked else web.Response(status=404)
    if request.path.endswith('.chunk01of02'):
      return web.Response(body=parts[0])
    if request.path.endswith('.chunk02of02'):
      return web.Response(body=parts[1])
    return web.Response(body=payload)

  async def run():
    app = web.Application()
    app.router.add_get('/{name:.*}', serve)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    try:
      port = runner.addresses[0][1]
      bundle = custom.ModelManagerSP.ModelBundle.new_message(ref='local-test-model', index=7, models=[{
        'type': 'supercombo', 'artifact': {'fileName': 'local-test.onnx',
          'downloadUri': {'uri': f'http://127.0.0.1:{port}/local-test.onnx', 'sha256': hashlib.sha256(payload).hexdigest()}}}])
      manager._chunk_size = 4
      manager.params.put('ModelManager_DownloadIndex', 7, block=True)
      replaced = []
      def report():
        if (cancel_and_retry and not replaced and manager.selected_bundle and
            manager.selected_bundle.models[0].artifact.downloadProgress.progress > 0):
          manager.params.remove('ModelManager_DownloadIndex')
          manager.params.put('ModelManager_DownloadIndex', 7, block=True)
          replaced.append(True)
      monkeypatch.setattr(manager, '_report_status', report)
      destination = str(tmp_path / 'models')
      if cancel_and_retry:
        with pytest.raises(model_manager.ModelDownloadCancelled):
          await manager._download_bundle(bundle, destination)
        assert replaced == [True]
        assert manager.params.get('ModelManager_DownloadIndex') == 7
        assert manager.params.get('ModelManager_ActiveBundle') is None
        assert manager.active_bundle is None
        assert not list((tmp_path / 'models').iterdir())
      await manager._download_bundle(bundle, destination)
      assert read_file_chunked(str(tmp_path / 'models' / 'local-test.onnx')) == payload
      assert manager.params.get('ModelManager_ActiveBundle')['ref'] == 'local-test-model'
      assert manager.active_bundle.models[0].artifact.downloadProgress.progress == 100
      requests = len(hits)
      await manager._download_bundle(bundle, destination)
      assert len(hits) == requests  # Hash-verified cache reuse requires no HTTP.
      assert manager.active_bundle.models[0].artifact.downloadProgress.status == custom.ModelManagerSP.DownloadStatus.cached
      assert manager._download_request is None
      assert not manager._download_start_times
    finally:
      await runner.cleanup()
  asyncio.run(run())
