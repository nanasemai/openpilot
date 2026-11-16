"""Verify the download request handoff using isolated parameter stores."""
import pytest

from openpilot.common.params import Params
from openpilot.sunnypilot.mapd import mapd_manager as manager


@pytest.fixture
def stores(tmp_path, monkeypatch):
  persistent = Params(str(tmp_path / 'persistent'))
  memory = Params(str(tmp_path / 'memory'))
  monkeypatch.setattr(manager, 'params', persistent)
  monkeypatch.setattr(manager, 'mem_params', memory)
  return persistent, memory


def test_new_request_replaces_old_success_before_handoff(stores, monkeypatch):
  persistent, memory = stores
  persistent.put('OSMDownloadProgress', {'total_files': 5, 'downloaded_files': 5}, block=True)
  calls = []
  class RecordedStore:
    def __init__(self, store, name):
      self.store, self.name = store, name
    def __getattr__(self, key):
      return getattr(self.store, key)
    def put(self, key, value, **kwargs):
      calls.append((self.name, key, value))
      return self.store.put(key, value, **kwargs)
    def put_bool(self, key, value, **kwargs):
      calls.append((self.name, key, value))
      return self.store.put_bool(key, value, **kwargs)
  monkeypatch.setattr(manager, 'params', RecordedStore(persistent, 'persistent'))
  monkeypatch.setattr(manager, 'mem_params', RecordedStore(memory, 'memory'))
  manager.request_refresh_osm_location_data(['CN'])
  progress = persistent.get('OSMDownloadProgress')
  assert progress['status'] == 'requested'
  assert progress['downloaded_files'] == progress['total_files'] == 0
  assert memory.get('OSMDownloadLocations') == {'nations': ['CN'], 'states': []}
  assert float(persistent.get('OsmDownloadedDate')) == progress['requested_at']
  assert calls[0] == ('persistent', 'OsmDbUpdatesCheck', True)
  assert calls[-2][0:2] == ('memory', 'OSMDownloadLocations')
  assert calls[-1] == ('persistent', 'OsmDbUpdatesCheck', False)


def test_update_request_waits_for_active_download(stores, monkeypatch):
  persistent, memory = stores
  persistent.put_bool('OsmDbUpdatesCheck', True, block=True)
  memory.put('OSMDownloadLocations', {'nations': ['CN']}, block=True)
  cleanup = []
  monkeypatch.setattr(manager, 'cleanup_old_osm_data', lambda files: cleanup.append(files))
  manager.update_osm_db()
  assert not cleanup
  assert persistent.get_bool('OsmDbUpdatesCheck')
  assert memory.get('OSMDownloadLocations') == {'nations': ['CN']}


def test_missing_region_does_not_delete_existing_cache(stores, monkeypatch):
  persistent, _memory = stores
  persistent.put_bool('OsmDbUpdatesCheck', True, block=True)
  cleanup = []
  monkeypatch.setattr(manager, 'cleanup_old_osm_data', lambda files: cleanup.append(files))
  manager.update_osm_db()
  assert not cleanup
  assert not persistent.get_bool('OsmDbUpdatesCheck')
  assert persistent.get('OSMDownloadProgress')['status'] == 'invalid_request'


@pytest.mark.parametrize('nations,states,expected', [
  (['US'], ['CA'], ([], ['CA'])),
  (['US'], ['All'], (['US'], [])),
  (['US'], ['all'], (['US'], [])),
  (['CN'], ['CA'], (['CN'], [])),
  (['CN'], ['All'], (['CN'], [])),
  ([], None, ([], [])),
])
def test_only_us_downloads_include_state_regions(nations, states, expected):
  assert manager.filter_nations_and_states(nations, states) == expected
