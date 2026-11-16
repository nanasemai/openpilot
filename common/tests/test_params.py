import pytest
import datetime
import os
import threading
import time
import uuid
import fcntl
from pathlib import Path

from openpilot.common.params import Params, ParamKeyFlag, UnknownKeyName

class TestParams:
  def setup_method(self):
    self.params = Params()

  def test_params_put_and_get(self):
    self.params.put("DongleId", "cb38263377b873ee", block=True)
    assert self.params.get("DongleId") == "cb38263377b873ee"

  def test_params_non_ascii(self):
    st = b"\xe1\x90\xff"
    self.params.put("CarParams", st, block=True)
    assert self.params.get("CarParams") == st

  def test_params_get_cleared_manager_start(self):
    self.params.put("CarParams", b"test", block=True)
    self.params.put("DongleId", "cb38263377b873ee", block=True)
    assert self.params.get("CarParams") == b"test"

    undefined_param = self.params.get_param_path(uuid.uuid4().hex)
    with open(undefined_param, "w") as f:
      f.write("test")
    assert os.path.isfile(undefined_param)

    self.params.clear_all(ParamKeyFlag.CLEAR_ON_MANAGER_START)
    assert self.params.get("CarParams") is None
    assert self.params.get("DongleId") is not None
    assert not os.path.isfile(undefined_param)

  def test_params_two_things(self):
    self.params.put("DongleId", "bob", block=True)
    self.params.put("AthenadPid", 123, block=True)
    assert self.params.get("DongleId") == "bob"
    assert self.params.get("AthenadPid") == 123

  def test_params_get_block(self):
    def _delayed_writer():
      time.sleep(0.1)
      self.params.put("CarParams", b"test", block=True)
    threading.Thread(target=_delayed_writer).start()
    assert self.params.get("CarParams") is None
    assert self.params.get("CarParams", block=True) == b"test"

  def test_params_unknown_key_fails(self):
    with pytest.raises(UnknownKeyName):
      self.params.get("swag")

    with pytest.raises(UnknownKeyName):
      self.params.get_bool("swag")

    with pytest.raises(UnknownKeyName):
      self.params.put("swag", "abc", block=True)

    with pytest.raises(UnknownKeyName):
      self.params.put_bool("swag", True, block=True)

  def test_remove_not_there(self):
    assert self.params.get("CarParams") is None
    self.params.remove("CarParams")
    assert self.params.get("CarParams") is None

  @pytest.mark.parametrize('operation', ['put', 'remove'])
  @pytest.mark.parametrize('change', ['unchanged', 'same_value', 'cancelled', 'clear_onroad'])
  def test_conditional_operation_uses_file_snapshot(self, operation, change):
    self.params.put('ModelManager_DownloadIndex', 7, block=True)
    self.params.put('ModelManager_ActiveBundle', {'ref': 'active'}, block=True)
    with open(self.params.get_param_path('ModelManager_DownloadIndex'), 'rb') as snapshot:
      if change == 'same_value':
        self.params.remove('ModelManager_DownloadIndex')
        self.params.put('ModelManager_DownloadIndex', 7, block=True)
      elif change == 'cancelled':
        self.params.remove('ModelManager_DownloadIndex')
      elif change == 'clear_onroad':
        self.params.clear_all(ParamKeyFlag.CLEAR_ON_ONROAD_TRANSITION)
      if operation == 'put':
        saved = self.params.put_if_unchanged('ModelManager_ActiveBundle', {'ref': 'new'},
                                            'ModelManager_DownloadIndex', snapshot.fileno())
        assert self.params.get('ModelManager_ActiveBundle') == {'ref': 'new' if change == 'unchanged' else 'active'}
      else:
        saved = self.params.remove_if_unchanged('ModelManager_DownloadIndex', snapshot.fileno())
        assert self.params.get('ModelManager_DownloadIndex') == (7 if change == 'same_value' else None)
      assert saved == (change == 'unchanged')
    root = Path(self.params.get_param_path()).parent
    assert not list(root.glob('.tmp_value_*'))

  @pytest.mark.parametrize('operation', ['put', 'remove'])
  def test_conditional_operation_checks_after_acquiring_params_lock(self, operation):
    self.params.put('ModelManager_DownloadIndex', 7, block=True)
    self.params.put('ModelManager_ActiveBundle', {'ref': 'active'}, block=True)
    root = Path(self.params.get_param_path()).parent
    results, errors = [], []
    started, finished = threading.Event(), threading.Event()
    with open(self.params.get_param_path('ModelManager_DownloadIndex'), 'rb') as snapshot, open(root / '.lock', 'rb') as lock:
      fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
      def worker():
        started.set()
        try:
          if operation == 'put':
            results.append(self.params.put_if_unchanged('ModelManager_ActiveBundle', {'ref': 'old-result'},
                                                       'ModelManager_DownloadIndex', snapshot.fileno()))
          else:
            results.append(self.params.remove_if_unchanged('ModelManager_DownloadIndex', snapshot.fileno()))
        except Exception as error:
          errors.append(error)
        finally:
          finished.set()
      thread = threading.Thread(target=worker)
      thread.start()
      try:
        assert started.wait(1)
        assert not finished.wait(.05)
        # Replace while owning the real Params lock, exactly as Params.put does.
        replacement = root / '.replacement'
        replacement.write_bytes(b'7')
        os.replace(replacement, self.params.get_param_path('ModelManager_DownloadIndex'))
      finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        thread.join(timeout=2)
      assert not thread.is_alive()
      assert not errors
      assert results == [False]
    assert self.params.get('ModelManager_DownloadIndex') == 7
    assert self.params.get('ModelManager_ActiveBundle') == {'ref': 'active'}
    assert not list(root.glob('.tmp_value_*'))

  @pytest.mark.parametrize('operation', ['put', 'remove'])
  def test_conditional_operation_rejects_invalid_snapshot(self, operation):
    self.params.put('ModelManager_DownloadIndex', 7, block=True)
    with pytest.raises(OSError):
      if operation == 'put':
        self.params.put_if_unchanged('ModelManager_ActiveBundle', {'ref': 'new'}, 'ModelManager_DownloadIndex', -1)
      else:
        self.params.remove_if_unchanged('ModelManager_DownloadIndex', -1)
    assert self.params.get('ModelManager_DownloadIndex') == 7

  def test_get_bool(self):
    self.params.remove("IsMetric")
    assert not self.params.get_bool("IsMetric")

    self.params.put_bool("IsMetric", True, block=True)
    assert self.params.get_bool("IsMetric")

    self.params.put_bool("IsMetric", False, block=True)
    assert not self.params.get_bool("IsMetric")

    self.params.put("IsMetric", True, block=True)
    assert self.params.get_bool("IsMetric")

    self.params.put("IsMetric", False, block=True)
    assert not self.params.get_bool("IsMetric")

  def test_put_non_blocking_with_get_block(self):
    q = Params()
    def _delayed_writer():
      time.sleep(0.1)
      Params().put("CarParams", b"test")
    threading.Thread(target=_delayed_writer).start()
    assert q.get("CarParams") is None
    assert q.get("CarParams", True) == b"test"

  def test_put_bool_non_blocking_with_get_block(self):
    q = Params()
    def _delayed_writer():
      time.sleep(0.1)
      Params().put_bool("CarParams", True)
    threading.Thread(target=_delayed_writer).start()
    assert q.get("CarParams") is None
    assert q.get("CarParams", True) == b"1"

  def test_params_all_keys(self):
    keys = Params().all_keys()

    # sanity checks
    assert len(keys) > 20
    assert len(keys) == len(set(keys))
    assert b"CarParams" in keys

  def test_params_default_value(self):
    self.params.remove("LanguageSetting")
    self.params.remove("LongitudinalPersonality")
    self.params.remove("LiveParameters")

    assert self.params.get("LanguageSetting") is None
    assert self.params.get("LanguageSetting", return_default=False) is None
    assert isinstance(self.params.get("LanguageSetting", return_default=True), str)
    assert isinstance(self.params.get("LongitudinalPersonality", return_default=True), int)
    assert self.params.get("LiveParameters") is None
    assert self.params.get("LiveParameters", return_default=True) is None

  def test_params_get_type(self):
    # json
    self.params.put("ApiCache_FirehoseStats", {"a": 0}, block=True)
    assert self.params.get("ApiCache_FirehoseStats") == {"a": 0}

    # int
    self.params.put("BootCount", 1441, block=True)
    assert self.params.get("BootCount") == 1441

    # bool
    self.params.put("AdbEnabled", True, block=True)
    assert self.params.get("AdbEnabled")
    assert isinstance(self.params.get("AdbEnabled"), bool)

    # time
    now = datetime.datetime.now(datetime.UTC)
    self.params.put("InstallDate", now, block=True)
    assert self.params.get("InstallDate") == now
