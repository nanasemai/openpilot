import pyray as rl
import requests
import threading
import queue
import re
from collections.abc import Callable
from enum import Enum

from openpilot.common.params import Params
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
from openpilot.system.ui.widgets.keyboard import Keyboard
from openpilot.system.ui.widgets.list_view import (
  ItemAction,
  ListItem,
  BUTTON_HEIGHT,
  BUTTON_BORDER_RADIUS,
  BUTTON_FONT_SIZE,
  BUTTON_WIDTH,
)

VALUE_FONT_SIZE = 48


class SshKeyFetcher:
  HTTP_TIMEOUT = 15  # seconds

  def __init__(self, params: Params):
    self._params = params
    self._on_response: Callable[[Callable[[], str] | None], None] | None = None
    self._generation = 0
    self._busy = False
    self._results = queue.SimpleQueue()

  @property
  def busy(self):
    return self._busy

  def snapshot(self):
    return self._params.get("GithubUsername"), self._params.get("GithubSshKeys")

  def fetch(self, username: str, on_response: Callable[[Callable[[], str] | None], None]):
    if self._busy:
      return False
    self._generation += 1
    self._busy = True
    self._on_response = on_response
    previous = self.snapshot()
    try:
      threading.Thread(target=self._fetch_thread, args=(self._generation, username, previous), daemon=True).start()
    except Exception:
      self._results.put((self._generation, username, previous, None,
                         tr_noop("Unable to fetch SSH keys. Check your internet connection and try again.")))
    return True

  def update(self):
    while not self._results.empty():
      generation, username, previous, keys, error = self._results.get()
      if generation != self._generation:
        continue
      self._busy = False
      if self.snapshot() != previous:
        error = tr_noop("SSH keys changed. Reopen the settings and try again.")
      elif error is None:
        try:
          self._params.put("GithubSshKeys", keys, block=True)
          self._params.put("GithubUsername", username, block=True)
        except Exception:
          # Preserve the previous pair if only one of the saves succeeded.
          for key, value in zip(("GithubUsername", "GithubSshKeys"), previous, strict=True):
            try:
              if value is None:
                self._params.remove(key)
              else:
                self._params.put(key, value, block=True)
            except Exception:
              pass  # Report failure even if the parameter store cannot restore the previous pair.
          error = tr_noop("Unable to save SSH keys. Try again.")
      callback, self._on_response = self._on_response, None
      if callback:
        callback((lambda error=error, username=username: tr(error).format(username)) if error else None)

  def clear(self):
    self._generation += 1
    self._busy = False
    self._on_response = None
    self._params.remove("GithubSshKeys")
    self._params.remove("GithubUsername")

  def _fetch_thread(self, generation: int, username: str, previous):
    keys, error = None, None
    try:
      response = requests.get(f"https://github.com/{username}.keys", timeout=self.HTTP_TIMEOUT)
      response.raise_for_status()
      keys = response.text.strip()
      if not keys:
        error = tr_noop("No SSH keys found for user '{}'")
    except requests.exceptions.Timeout:
      error = tr_noop("Request timed out")
    except requests.exceptions.HTTPError:
      error = tr_noop("Unable to fetch SSH keys for user '{}'. Check the username and try again.")
    except Exception:
      error = tr_noop("Unable to fetch SSH keys. Check your internet connection and try again.")
    finally:
      self._results.put((generation, username, previous, keys, error))


class SshKeyActionState(Enum):
  LOADING = tr_noop("LOADING")
  ADD = tr_noop("ADD")
  REMOVE = tr_noop("REMOVE")


class SshKeyAction(ItemAction):
  MAX_WIDTH = 500

  def __init__(self):
    super().__init__(self.MAX_WIDTH, True)

    self._keyboard = Keyboard(min_text_size=1)
    self._params = Params()
    self._fetcher = SshKeyFetcher(self._params)
    self._text_font = gui_app.font(FontWeight.NORMAL)
    self._button = Button("", click_callback=self._handle_button_click, button_style=ButtonStyle.LIST_ACTION,
                          border_radius=BUTTON_BORDER_RADIUS, font_size=BUTTON_FONT_SIZE)

    self._refresh_state()
    self._edit_snapshot = self._fetcher.snapshot()
    self._pending_error: Callable[[], str] | None = None

  def set_touch_valid_callback(self, touch_callback: Callable[[], bool]) -> None:
    super().set_touch_valid_callback(touch_callback)
    self._button.set_touch_valid_callback(touch_callback)

  def _refresh_state(self):
    keys = self._params.get("GithubSshKeys")
    self._username = self._params.get("GithubUsername") if keys else ""
    self._state = SshKeyActionState.REMOVE if keys else SshKeyActionState.ADD

  def _update_state(self):
    super()._update_state()
    self._fetcher.update()
    if not self._fetcher.busy:
      self._refresh_state()

  def get_status(self):
    if self._fetcher.busy:
      return tr("Fetching SSH keys...")
    return self._username or tr("Not set")

  def present_error(self):
    if self._pending_error:
      error, self._pending_error = self._pending_error, None
      dialog = alert_dialog(error())
      dialog._label.set_text(error)
      gui_app.push_widget(dialog)

  def _render(self, rect: rl.Rectangle) -> bool:
    if self.enabled:
      self.present_error()
    # Draw username if exists
    if self._username:
      text_size = measure_text_cached(self._text_font, self._username, VALUE_FONT_SIZE)
      rl.draw_text_ex(
        self._text_font,
        self._username,
        (rect.x + rect.width - BUTTON_WIDTH - text_size.x - 30, rect.y + (rect.height - text_size.y) / 2),
        VALUE_FONT_SIZE,
        1.0,
        rl.Color(170, 170, 170, 255),
      )

    # Draw button
    button_rect = rl.Rectangle(rect.x + rect.width - BUTTON_WIDTH, rect.y + (rect.height - BUTTON_HEIGHT) / 2, BUTTON_WIDTH, BUTTON_HEIGHT)
    self._button.set_rect(button_rect)
    self._button.set_text(tr(self._state.value))
    self._button.set_enabled(self._state != SshKeyActionState.LOADING)
    self._button.render(button_rect)
    return False

  def _handle_button_click(self):
    if self._fetcher.busy or not self.enabled:
      return
    self._refresh_state()
    self._edit_snapshot = self._fetcher.snapshot()
    if self._state == SshKeyActionState.ADD:
      if not gui_app.big_ui():
        from openpilot.selfdrive.ui.mici.widgets.dialog import BigInputDialog
        dialog = BigInputDialog(tr("Enter your GitHub username"), confirm_callback=self._submit_username)
        dialog._hint_label.set_text(lambda: tr("Enter your GitHub username"))
        gui_app.push_widget(dialog)
        return
      self._keyboard.reset()
      self._keyboard.set_title(tr("Enter your GitHub username"))
      self._keyboard.set_callback(self._on_username_submit)
      gui_app.push_widget(self._keyboard)
    elif self._state == SshKeyActionState.REMOVE:
      previous = self._fetcher.snapshot()
      def confirm(result):
        if result == DialogResult.CONFIRM:
          if self._fetcher.snapshot() == previous:
            try:
              self._fetcher.clear()
            except Exception:
              gui_app.push_widget(alert_dialog(tr("Unable to remove SSH keys. Try again.")))
          else:
            gui_app.push_widget(alert_dialog(tr("SSH keys changed. Reopen the settings and try again.")))
        self._refresh_state()
      username = self._username
      def text():
        return tr("Remove SSH keys for {username}?").format(username=username or tr("Unknown"))
      dialog = ConfirmDialog(text(), tr("Remove"), callback=confirm)
      dialog._label.set_text(text)
      gui_app.push_widget(dialog)

  def _on_username_submit(self, result: DialogResult):
    if result != DialogResult.CONFIRM:
      return

    username = self._keyboard.text.strip()
    self._submit_username(username)

  def _submit_username(self, username):
    username = username.strip()
    if not username:
      return
    if self._fetcher.busy or not self.enabled:
      return
    if self._fetcher.snapshot() != self._edit_snapshot:
      self._refresh_state()
      gui_app.push_widget(alert_dialog(tr("SSH keys changed. Reopen the settings and try again.")))
      return
    if re.fullmatch(r"[A-Za-z0-9-]+", username) is None:
      gui_app.push_widget(alert_dialog(tr("Enter a GitHub username using letters, numbers, or hyphens.")))
      return
    if self._fetcher.fetch(username, self._on_fetch_response):
      self._state = SshKeyActionState.LOADING

  def _on_fetch_response(self, error: Callable[[], str] | None):
    self._refresh_state()
    self._pending_error = error


def ssh_key_item(title: str | Callable[[], str], description: str | Callable[[], str]) -> ListItem:
  return ListItem(title=title, description=description, action_item=SshKeyAction())
