"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import datetime
import json
import os
import platform
import queue
import requests
import shutil
import threading
from pathlib import Path
from functools import lru_cache
from time import monotonic

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.selfdrive.ui.layouts.settings.software import time_ago
from openpilot.system.hardware.hw import Paths
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import TRANSLATIONS_DIR, multilang, tr, tr_noop
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
from openpilot.system.ui.widgets.list_view import text_item
from openpilot.system.ui.widgets.scroller_tici import Scroller

from openpilot.system.ui.sunnypilot.lib.utils import NoElideButtonAction
from openpilot.system.ui.sunnypilot.widgets.list_view import ListItemSP
from openpilot.system.ui.sunnypilot.widgets.tree_dialog import TreeFolder, TreeNode, TreeOptionDialog
from openpilot.system.ui.sunnypilot.widgets.progress_bar import progress_item

MAP_PATH = Path(Paths.mapd_root()) / "offline"
REQUEST_TIMEOUT = 30


@lru_cache(maxsize=1)
def _region_names():
  with TRANSLATIONS_DIR.joinpath("map_regions.json").open(encoding="utf-8") as file:
    return json.load(file)


def region_display_name(region_type, ref, source=""):
  if region_type == "State" and ref.lower() == "all":
    return tr("All states (~6.0 GB)")
  kind = region_type.lower()
  entry = _region_names().get(f"{kind}:{ref}", {})
  source = source or entry.get('display_name') or ref
  key = entry.get('text', f"Map {kind}: {source}")
  translated = tr(key)
  return source if translated == key else translated


class OSMLayout(Widget):
  def __init__(self):
    super().__init__()
    self._current_percent = 0
    self._last_map_size_update = 0
    self._last_language = None
    self._events = queue.SimpleQueue()
    self._size_scan_running = False
    self._size_rescan_requested = False
    self._size_generation = 0
    self._deleting = False
    self._fetching_regions = set()
    self._pending_country = None
    self._pending_country_context = None
    self._region_fetch_contexts = {}
    self._region_events = queue.SimpleQueue()
    self._region_generation = 0
    self._region_page_open = False
    self._request_started = None
    self._download_seen = False
    self._download_state = "idle"
    self._download_reason = ""
    self._params = ui_state.params
    self._mem_params = Params("/dev/shm/params") if platform.system() != "Darwin" else ui_state.params
    self._initialize_items()
    self._update_map_size()
    self._progress.set_visible(False)
    self._state_btn.set_visible(False)
    self._scroller = Scroller(self.items, line_separator=True, spacing=0)

  def _initialize_items(self):
    self._mapd_version = text_item(lambda: tr("Mapd Version"), lambda: self._params.get("MapdVersion") or tr("Loading..."))
    self._delete_maps_btn = ListItemSP(lambda: tr("Downloaded Maps"), action_item=NoElideButtonAction(lambda: tr("DELETE")), callback=self._delete_maps)
    self._progress = progress_item(lambda: tr("Map Download Status"))
    self._progress.set_description(lambda: self._download_reason)
    self._update_btn = ListItemSP(lambda: tr("Database Update"), action_item=NoElideButtonAction(lambda: tr("CHECK")), callback=self._update_db)
    self._country_btn = ListItemSP(lambda: tr("Country"), action_item=NoElideButtonAction(lambda: tr("SELECT")),
                                   callback=lambda: self._select_region("Country"))
    self._state_btn = ListItemSP(lambda: tr("State"), action_item=NoElideButtonAction(lambda: tr("SELECT")), callback=lambda: self._select_region("State"))
    for item in (self._delete_maps_btn, self._update_btn, self._country_btn, self._state_btn):
      item.set_description(self._operation_reason)

    self.items = [self._mapd_version, self._delete_maps_btn, self._progress, self._update_btn, self._country_btn, self._state_btn]

  def _show_confirm(self, msg, confirm_text, func):
    generation = self._region_generation
    gui_app.push_widget(ConfirmDialog(msg, confirm_text, callback=lambda res: func()
                                     if res == DialogResult.CONFIRM and self._region_context_current(generation) else None))

  def _region_context_current(self, generation):
    return self._region_page_open and (generation is None or generation == self._region_generation)

  def calculate_size(self, generation=None, root=None):
    generation = self._size_generation if generation is None else generation
    root = MAP_PATH if root is None else root
    total_size = 0
    try:
      directories_to_scan = [root] if root.exists() and not root.is_symlink() else []
      while directories_to_scan:
        with os.scandir(directories_to_scan.pop()) as entries:
          for entry in entries:
            if entry.is_file(follow_symlinks=False):
              total_size += entry.stat(follow_symlinks=False).st_size
            elif entry.is_dir(follow_symlinks=False):
              directories_to_scan.append(entry.path)
      self._events.put(("size", (generation, total_size, None)))
    except OSError as error:
      self._events.put(("size", (generation, None, str(error))))

  def _update_map_size(self):
    if self._deleting:
      return
    if self._size_scan_running:
      self._size_rescan_requested = True
      return
    self._size_scan_running = True
    self._size_rescan_requested = False
    threading.Thread(target=self.calculate_size, args=(self._size_generation, MAP_PATH), daemon=True).start()

  def _do_delete_maps(self, root=None):
    root = MAP_PATH if root is None else root
    try:
      if root.exists():
        shutil.rmtree(root)
      # Complete the operation even if the page is closed or the screen is off.
      # Only the result presentation waits for the UI to consume the event.
      for param in ("OsmDownloadedDate", "OsmLocal", "OsmLocationName", "OsmLocationTitle", "OsmStateName", "OsmStateTitle", "OSMDownloadProgress"):
        self._params.remove(param)
      self._events.put(("delete", (True, None)))
    except Exception as error:
      self._events.put(("delete", (False, str(error))))

  def _on_confirm_delete_maps(self):
    if self._busy():
      return
    self._deleting = True
    self._size_generation += 1
    self._update_labels()
    threading.Thread(target=self._do_delete_maps, args=(MAP_PATH,), daemon=True).start()

  def _delete_maps(self):
    if self._busy():
      return
    self._show_confirm(tr("This will delete ALL downloaded maps\n\nAre you sure you want to delete all maps?"),
                       tr("Yes, delete all maps"), self._on_confirm_delete_maps)

  def _update_db(self):
    if not self._region_page_open or self._deleting or self._fetching_regions or self._mem_params.get("OSMDownloadLocations"):
      return
    if self._params.get_bool("OsmDbUpdatesCheck") and self._download_state != "waiting_timeout":
      return
    if not self._params.get("OsmLocationName"):
      return
    context = self._map_context()
    generation = self._region_generation
    country = self._params.get("OsmLocationName")
    country_title = self._params.get("OsmLocationTitle") or ""
    state = self._params.get("OsmStateName", return_default=True) if country == "US" else None
    state_title = self._params.get("OsmStateTitle") or ""
    def message():
      region = region_display_name("Country", country, country_title) + f" ({country})"
      if state:
        region += " / " + region_display_name("State", state, state_title) + (f" ({state})" if state.lower() != "all" else "")
      return tr("Download maps for {region}? This may take a while to complete.").format(region=region)
    dialog = ConfirmDialog(message(), tr("Start Download"), callback=lambda result: self._begin_update_request(context, generation)
                           if result == DialogResult.CONFIRM else None)
    dialog._label.set_text(message)
    gui_app.push_widget(dialog)

  def _begin_update_request(self, context=None, generation=None):
    if not self._region_context_current(generation):
      return
    if context is not None and not self._check_map_context(context):
      return
    if self._deleting or self._fetching_regions or self._mem_params.get("OSMDownloadLocations") or not self._params.get("OsmLocationName"):
      return
    if self._params.get_bool("OsmDbUpdatesCheck") and self._download_state != "waiting_timeout":
      return
    self._request_started = monotonic()
    self._download_seen = False
    self._params.remove("OSMDownloadProgress")
    self._params.put_bool("OsmDbUpdatesCheck", True, block=True)
    self._update_labels()

  def _busy(self):
    return self._deleting or bool(self._fetching_regions) or self._params.get_bool("OsmDbUpdatesCheck") or bool(self._mem_params.get("OSMDownloadLocations"))

  def _operation_reason(self):
    if self._deleting:
      return tr("Wait for map deletion to finish.")
    if self._fetching_regions:
      return tr("Fetching map regions. Please wait.")
    if self._mem_params.get("OSMDownloadLocations") or self._params.get_bool("OsmDbUpdatesCheck"):
      return tr("Wait for the current map download to finish.")
    return ""

  def _map_context(self):
    regions = tuple(self._params.get(key) for key in
                    ("OsmLocationName", "OsmLocationTitle", "OsmStateName", "OsmStateTitle", "OsmLocal"))
    requests = []
    for store, key in ((self._params, "OsmDbUpdatesCheck"), (self._params, "OSMDownloadProgress"),
                       (self._mem_params, "OSMDownloadLocations")):
      try:
        stat = os.stat(store.get_param_path(key))
        requests.append((stat.st_dev, stat.st_ino, stat.st_mtime_ns))
      except FileNotFoundError:
        requests.append(None)
    return regions, tuple(requests)

  def _clear_pending_country(self):
    self._pending_country = None
    self._pending_country_context = None

  def _check_map_context(self, context):
    if context == self._map_context():
      return True
    self._clear_pending_country()
    gui_app.push_widget(alert_dialog(tr("Map settings changed. Reopen the map page and try again.")))
    return False

  def _select_region(self, region_type):
    if not self._region_page_open or self._busy():
      return
    is_country = region_type == "Country"
    btn = self._country_btn if is_country else self._state_btn
    self._region_fetch_contexts[region_type] = self._pending_country_context or self._map_context()
    self._fetching_regions.add(region_type)
    btn.action_item.set_enabled(False)
    btn.action_item.set_text(tr("FETCHING..."))
    threading.Thread(target=self._do_select_region, args=(region_type, btn, self._region_generation), daemon=True).start()

  def _handle_region_selection(self, region_type, locations, key, res, ref, context=None, generation=None):
    if not self._region_context_current(generation):
      return
    if res != DialogResult.CONFIRM or not ref:
      self._clear_pending_country()
      return
    if context is not None and not self._check_map_context(context):
      return
    if self._busy():
      self._clear_pending_country()
      return
    if region_type == "State" and self._pending_country is None and self._params.get("OsmLocationName") != "US":
      return
    node = next((node for node in locations if node.ref == ref), None)
    if node is None:
      return
    name = node.data['display_name']
    if ref == "US" and region_type == "Country":
      self._pending_country = (ref, name)
      self._pending_country_context = context or self._map_context()
      self._select_region("State")
      return
    if region_type == "Country":
      self._params.put_bool("OsmLocal", True, block=True)
      self._params.remove("OsmStateName")
      self._params.remove("OsmStateTitle")
    elif self._pending_country is not None:
      country, country_name = self._pending_country
      self._params.put_bool("OsmLocal", True, block=True)
      self._params.put("OsmLocationName", country, block=True)
      self._params.put("OsmLocationTitle", country_name, block=True)
      self._clear_pending_country()
    self._params.put(f"{key}Name", ref, block=True)
    self._params.put(f"{key}Title", name, block=True)
    self._update_labels()
    self._update_db()

  def _do_select_region(self, region_type, btn, generation=None):
    generation = self._region_generation if generation is None else generation
    base_url = "https://raw.githubusercontent.com/pfeiferj/openpilot-mapd/main/"
    url = base_url + ("nation_bounding_boxes.json" if region_type == "Country" else "us_states_bounding_boxes.json")
    try:
      response = requests.get(url, timeout=10)
      response.raise_for_status()
      data = response.json()
      if not isinstance(data, dict) or not data:
        raise ValueError(tr_noop("Empty map region data"))
      if any(not isinstance(ref, str) or not ref or not isinstance(value, dict) or not isinstance(value.get('full_name'), str) or not value['full_name'].strip()
             for ref, value in data.items()):
        raise ValueError(tr_noop("Invalid map region data"))
      locations = sorted([(ref, value['full_name']) for ref, value in data.items()], key=lambda location: location[1])
      error = None
    except Exception as exception:
      locations = []
      error = str(exception)

    self._region_events.put((region_type, btn, locations, error, generation))

  def _show_region_dialog(self, region_type, btn, locations, error=None, generation=None):
    generation = self._region_generation if generation is None else generation
    if not self._region_context_current(generation):
      return
    self._fetching_regions.discard(region_type)
    context = self._region_fetch_contexts.pop(region_type, None) or self._pending_country_context or self._map_context()
    btn.action_item.set_text(tr("SELECT"))
    self._update_labels()
    if not self._check_map_context(context):
      return
    if self._busy():
      self._clear_pending_country()
      return
    if not locations:
      def retry(result):
        if not self._region_context_current(generation):
          return
        if result == DialogResult.CONFIRM and self._check_map_context(context):
          self._select_region(region_type)
        else:
          self._clear_pending_country()
      def message():
        return tr("Failed to fetch map regions. Check the network and retry.") + ("\n\n" + tr(str(error)) if error else "")
      dialog = ConfirmDialog(message(), tr("Retry"), callback=retry)
      dialog._label.set_text(message)
      gui_app.push_widget(dialog)
      return
    locations = [TreeNode(ref=ref, data={'display_name': name}) for ref, name in locations]
    if region_type == "State":
      locations.insert(0, TreeNode(ref="All", data={'display_name': tr_noop("All states (~6.0 GB)")}))

    key = "OsmLocation" if region_type == "Country" else "OsmState"
    current = self._params.get(f"{key}Name") or ""
    def display(node):
      name = region_display_name(region_type, node.ref, node.data['display_name'])
      return name + (f" ({node.ref})" if node.ref != "All" else "")

    dialog = TreeOptionDialog(lambda: tr("Select {}").format(tr(region_type)), [TreeFolder(folder="", nodes=locations)],
                              current_ref=current, search_prompt=tr("Perform a search"),
                              display_func=display, search_funcs=[display, lambda node: node.data['display_name'] + ' ' + node.ref, lambda node: node.ref],
                              search_title=tr("English name or code"))
    dialog.on_exit = lambda res: self._handle_region_selection(region_type, locations, key, res, dialog.selection_ref, context, generation)
    gui_app.push_widget(dialog)

  def _process_events(self):
    while not self._events.empty():
      kind, data = self._events.get_nowait()
      if kind == "size":
        self._size_scan_running = False
        generation, size, error = data
        if generation != self._size_generation:
          self._last_map_size_update = 0
        elif error is not None:
          self._delete_maps_btn.action_item.set_value(tr("Map size unavailable"))
        else:
          self._delete_maps_btn.action_item.set_value(f"{size / 1024 ** 2:.2f} MB" if size < 1024 ** 3 else f"{size / 1024 ** 3:.2f} GB")
        if self._size_rescan_requested:
          self._update_map_size()
      elif kind == "delete":
        self._deleting = False
        ok, error = data
        if ok:
          self._pending_country = None
          self._request_started = None
          self._download_seen = False
          gui_app.push_widget(ConfirmDialog(tr("Downloaded maps deleted."), tr("OK"), cancel_text=""))
        else:
          gui_app.push_widget(ConfirmDialog(tr("Could not delete all maps: {error}").format(error=error), tr("Retry"),
                                            callback=lambda result: self._on_confirm_delete_maps() if result == DialogResult.CONFIRM else None))
        self._last_map_size_update = 0
        self._update_labels()
        self._update_map_size()

  def _update_labels(self):
    downloading = bool(self._mem_params.get("OSMDownloadLocations"))
    pending = self._params.get_bool("OsmDbUpdatesCheck")
    progress = self._params.get("OSMDownloadProgress")
    valid = isinstance(progress, dict)
    try:
      total = int(progress.get('total_files', 0)) if valid else 0
      done = int(progress.get('downloaded_files', 0)) if valid else 0
      valid = valid and total >= 0 and done >= 0
    except (TypeError, ValueError, OverflowError):
      total, done, valid = 0, 0, False

    previous = self._download_state
    self._current_percent = max(0.0, min(100.0, done / total * 100)) if total > 0 else 0
    if downloading:
      self._download_seen = True
      self._download_state = "downloading"
      text = tr("{progress}% - Downloading Maps").format(progress=int(self._current_percent)) if total > 0 else tr("Preparing map download...")
      self._download_reason = tr("Downloaded {done}/{total} map files.").format(done=done, total=total)
      device._reset_interactive_timeout()
      self._update_map_size()
    elif pending:
      if self._request_started is None:
        self._request_started = monotonic()
      self._download_state = "waiting_timeout" if monotonic() - self._request_started >= REQUEST_TIMEOUT else "waiting"
      text = (tr("Map service has not started the download. Retry the request.") if self._download_state == "waiting_timeout"
              else tr("Waiting for map service..."))
      self._download_reason = text
    elif valid and total > 0 and done >= total:
      self._download_state = "completed"
      text = tr("Map download completed.")
      self._download_reason = tr("Downloaded {done}/{total} map files.").format(done=done, total=total)
    elif valid and progress.get('status') == "invalid_request":
      self._download_state = "failed"
      text = tr("Select a map region before downloading.")
      self._download_reason = text
    elif (valid and total > 0) or progress or self._download_seen or self._request_started is not None:
      self._download_state = "failed"
      text = tr("Map download incomplete. Retry.")
      self._download_reason = (tr("Downloaded {done}/{total} map files. Retry the download to complete it.").format(done=done, total=total)
                               if total > 0 else tr("No map files were reported as downloaded. Check the network and retry."))
    else:
      self._download_state = "idle"
      text = ""
      self._download_reason = ""

    if previous == "downloading" and not downloading:
      self._update_map_size()
    self._progress.set_visible(self._download_state != "idle")
    self._progress.action_item.update(self._current_percent, text,
                                      show_progress=valid and total > 0 and self._download_state in ("downloading", "completed"))
    busy = self._busy()
    self._state_btn.set_visible(self._params.get("OsmLocationName") == "US")
    self._update_btn.set_visible(bool(self._params.get("OsmLocationName")))
    country = self._params.get("OsmLocationName") or ""
    state = self._params.get("OsmStateName", return_default=country == "US") or ""
    self._country_btn.action_item.set_value(region_display_name("Country", country, self._params.get("OsmLocationTitle") or "") if country else "")
    self._state_btn.action_item.set_value(region_display_name("State", state, self._params.get("OsmStateTitle") or "") if state else "")
    for region, button in (("Country", self._country_btn), ("State", self._state_btn)):
      button.set_enabled(not downloading and not pending and not self._deleting)
      button.action_item.set_enabled(not busy)
      button.action_item.set_text(tr("FETCHING...") if region in self._fetching_regions else tr("SELECT"))
      if region in self._fetching_regions:
        button.action_item.set_value(tr("FETCHING..."))
    self._delete_maps_btn.action_item.set_enabled(not busy)
    self._delete_maps_btn.action_item.set_text(tr("DELETING...") if self._deleting else tr("DELETE"))
    if self._deleting:
      self._delete_maps_btn.action_item.set_value(tr("DELETING..."))
    retry = self._download_state in ("failed", "waiting_timeout")
    retry_waiting = self._download_state == "waiting_timeout" and not downloading and not self._deleting and not self._fetching_regions
    self._update_btn.action_item.set_enabled(not busy or retry_waiting)
    self._update_btn.action_item.set_text(tr("Retry") if retry else tr("CHECK"))
    if retry:
      self._update_btn.action_item.set_value(tr("Retry Download"))
    elif self._download_state in ("waiting", "downloading"):
      self._update_btn.action_item.set_value(text)
    else:
      timestamp = self._params.get("OsmDownloadedDate")
      date = None
      try:
        if timestamp and float(timestamp) > 0:
          date = datetime.datetime.fromtimestamp(float(timestamp), tz=datetime.UTC)
      except (TypeError, ValueError, OverflowError, OSError):
        pass
      self._update_btn.action_item.set_value(tr("Last requested {time}").format(time=time_ago(date)))

  def show_event(self):
    self._region_page_open = True
    self._scroller.show_event()
    self._update_labels()

  def hide_event(self):
    self._region_page_open = False
    self._region_generation += 1
    self._fetching_regions.clear()
    self._region_fetch_contexts.clear()
    self._clear_pending_country()

  def _update_state(self):
    self._process_events()
    while not self._region_events.empty():
      self._show_region_dialog(*self._region_events.get_nowait())
    now = monotonic()
    if now - self._last_map_size_update >= 1.0 or self._last_language != multilang.language:
      self._last_map_size_update = now
      self._last_language = multilang.language
      self._update_labels()

  def _render(self, rect):
    self._scroller.render(rect)
