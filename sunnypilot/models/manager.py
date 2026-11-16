"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

import asyncio
import os
import time
from contextlib import contextmanager

import aiohttp
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware.hw import Paths

from cereal import messaging, custom
from openpilot.sunnypilot.models.fetcher import ModelFetcher
from openpilot.sunnypilot.models.helpers import get_active_bundle, validate_active_bundle, verify_file


class ModelDownloadCancelled(Exception):
  pass


class ModelManagerSP:
  """Manages model downloads and status reporting"""

  def __init__(self):
    self.params = Params()
    self.model_fetcher = ModelFetcher(self.params)
    self.pm = messaging.PubMaster(["modelManagerSP"])
    self.available_models: list[custom.ModelManagerSP.ModelBundle] = []
    self.selected_bundle: custom.ModelManagerSP.ModelBundle = None
    self.active_bundle: custom.ModelManagerSP.ModelBundle = get_active_bundle(self.params)
    self._chunk_size = 128 * 1000  # 128 KB chunks
    self._download_start_times: dict[str, float] = {}  # Track start time per model
    self._download_request = None

  def _sync_artifact_progress(self, source_artifact) -> None:
    """Mirror download progress to all artifacts sharing the same filename in the selected bundle."""
    if not self.selected_bundle:
      return
    for model in self.selected_bundle.models:
      for artifact in (model.artifact, model.metadata):
        if artifact is not source_artifact and artifact.fileName == source_artifact.fileName:
          artifact.downloadProgress.status = source_artifact.downloadProgress.status
          artifact.downloadProgress.progress = source_artifact.downloadProgress.progress
          artifact.downloadProgress.eta = source_artifact.downloadProgress.eta

  def _calculate_eta(self, filename: str, progress: float) -> int:
    """Calculate ETA based on elapsed time and current progress"""
    if filename not in self._download_start_times or progress <= 0:
      return 60  # Default ETA for new downloads

    elapsed_time = time.monotonic() - self._download_start_times[filename]
    if elapsed_time <= 0:
      return 60

    # If we're at X% after Y seconds, we can estimate total time as (Y / X) * 100
    total_estimated_time = (elapsed_time / progress) * 100
    eta = total_estimated_time - elapsed_time

    return max(1, int(eta))  # Return at least 1 second if download is ongoing

  @contextmanager
  def _request_snapshot(self):
    if self._download_request is not None:
      yield self._download_request
      return
    try:
      request = open(self.params.get_param_path("ModelManager_DownloadIndex"), 'rb')
    except FileNotFoundError:
      yield None
      return
    # Params.put replaces the file even when the index stays the same. Keeping
    # this file open distinguishes a fast cancel/retry and prevents inode reuse.
    self._download_request = request
    try:
      yield request
    finally:
      self._download_request = None
      request.close()

  def _check_download_request(self) -> None:
    if not self.selected_bundle or self._download_request is None:
      raise ModelDownloadCancelled("Download cancelled or replaced")
    expected = os.fstat(self._download_request.fileno())
    try:
      current = os.stat(self.params.get_param_path("ModelManager_DownloadIndex"))
    except FileNotFoundError:
      raise ModelDownloadCancelled("Download cancelled or replaced") from None
    if (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino):
      raise ModelDownloadCancelled("Download cancelled or replaced")

  async def _download_file(self, url: str, path: str, model) -> None:
    """Downloads a file with progress tracking"""
    self._download_start_times[model.fileName] = time.monotonic()

    async with aiohttp.ClientSession() as session:
      async with session.get(url) as response:
        response.raise_for_status()
        total_size = int(response.headers.get("content-length", 0))
        bytes_downloaded = 0

        with open(path, 'wb') as f:
          async for chunk in response.content.iter_chunked(self._chunk_size):  # type: bytes
            f.write(chunk)
            bytes_downloaded += len(chunk)

            self._check_download_request()

            if total_size > 0:
              progress = (bytes_downloaded / total_size) * 100
              model.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.downloading
              model.downloadProgress.progress = progress
              model.downloadProgress.eta = self._calculate_eta(model.fileName, progress)
              self._sync_artifact_progress(model)
              self._report_status()

        # Clean up start time after download completes
        del self._download_start_times[model.fileName]

  async def _download_chunked(self, base_url: str, base_path: str, artifact) -> None:
    from openpilot.common.file_chunker import get_manifest_path, get_chunk_name
    manifest_url = get_manifest_path(base_url)
    manifest_path = get_manifest_path(base_path)

    async with aiohttp.ClientSession() as session:
      async with session.get(manifest_url) as resp:
        if resp.status == 404:
          raise FileNotFoundError
        resp.raise_for_status()
        num_chunks = int((await resp.read()).strip())

    self._download_start_times[artifact.fileName] = time.monotonic()

    for i in range(num_chunks):
      chunk_url = get_chunk_name(base_url, i, num_chunks)
      chunk_path = get_chunk_name(base_path, i, num_chunks)
      chunk_downloaded = 0
      async with aiohttp.ClientSession() as session:
        async with session.get(chunk_url) as response:
          response.raise_for_status()
          chunk_size = int(response.headers.get("content-length", 0))
          with open(chunk_path, 'wb') as f:
            async for data in response.content.iter_chunked(self._chunk_size):
              f.write(data)
              chunk_downloaded += len(data)
              self._check_download_request()
              intra = chunk_downloaded / max(chunk_size, 1)
              progress = min(99, (i + intra) / num_chunks * 100)
              artifact.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.downloading
              artifact.downloadProgress.progress = progress
              artifact.downloadProgress.eta = self._calculate_eta(artifact.fileName, progress)
              self._sync_artifact_progress(artifact)
              self._report_status()

    with open(manifest_path, 'w') as f:
      f.write(str(num_chunks))
    if os.path.isfile(base_path):
      os.remove(base_path)
    del self._download_start_times[artifact.fileName]

  async def _process_artifact(self, artifact, destination_path: str) -> None:
    if not artifact.downloadUri.uri:
      return None

    url = artifact.downloadUri.uri
    expected_hash = artifact.downloadUri.sha256
    filename = artifact.fileName
    full_path = os.path.join(destination_path, filename)

    try:
      if await verify_file(full_path, expected_hash):
        artifact.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.cached
        artifact.downloadProgress.progress = 100
        artifact.downloadProgress.eta = 0
        self._sync_artifact_progress(artifact)
        self._report_status()
        return

      try:
        await self._download_chunked(url, full_path, artifact)
      except (FileNotFoundError, aiohttp.ClientResponseError):
        await self._download_file(url, full_path, artifact)

      if not await verify_file(full_path, expected_hash):
        raise ValueError(f"Hash validation failed for {filename}")

      artifact.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.downloaded
      artifact.downloadProgress.progress = 100
      artifact.downloadProgress.eta = 0
      self._sync_artifact_progress(artifact)
      self._report_status()

    except Exception as e:
      for f in [full_path] + [p for p in (os.path.join(destination_path, f) for f in os.listdir(destination_path)) if filename in p]:
        if os.path.isfile(f):
          os.remove(f)
      self._download_start_times.pop(artifact.fileName, None)
      if isinstance(e, ModelDownloadCancelled):
        raise
      cloudlog.error(f"Error downloading {filename}: {str(e)}")
      artifact.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.failed
      artifact.downloadProgress.eta = 0
      self._sync_artifact_progress(artifact)
      self.selected_bundle.status = custom.ModelManagerSP.DownloadStatus.failed
      self._report_status()
      raise

  async def _process_model(self, model, destination_path: str) -> None:
    """Processes a single model download including verification"""
    model_artifact = model.artifact
    metadata_artifact = model.metadata

    await self._process_artifact(metadata_artifact, destination_path)
    await self._process_artifact(model_artifact, destination_path)

  def _report_status(self) -> None:
    """Reports current status through messaging system"""
    msg = messaging.new_message('modelManagerSP', valid=True)
    model_manager_state = msg.modelManagerSP
    if self.selected_bundle:
      model_manager_state.selectedBundle = self.selected_bundle

    if self.active_bundle:
      model_manager_state.activeBundle = self.active_bundle

    model_manager_state.availableBundles = self.available_models
    self.pm.send('modelManagerSP', msg)

  async def _download_bundle(self, model_bundle: custom.ModelManagerSP.ModelBundle, destination_path: str) -> None:
    """Downloads all models in a bundle"""
    with self._request_snapshot():
      await self._download_requested_bundle(model_bundle, destination_path)

  async def _download_requested_bundle(self, model_bundle: custom.ModelManagerSP.ModelBundle, destination_path: str) -> None:
    self.selected_bundle = model_bundle
    self.selected_bundle.status = custom.ModelManagerSP.DownloadStatus.downloading
    os.makedirs(destination_path, exist_ok=True)

    try:
      self._check_download_request()
      if self.params.get("ModelManager_DownloadIndex") != model_bundle.index:
        raise ModelDownloadCancelled("Download cancelled or replaced")
      seen_artifacts: set[str] = set()
      for model in self.selected_bundle.models:
        for artifact in (model.metadata, model.artifact):
          if not artifact.fileName:
            continue
          if artifact.fileName in seen_artifacts:
            artifact.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.cached
            artifact.downloadProgress.progress = 100
            artifact.downloadProgress.eta = 0
          else:
            seen_artifacts.add(artifact.fileName)
            self._check_download_request()
            await self._process_artifact(artifact, destination_path)

      self._check_download_request()
      self.selected_bundle.status = custom.ModelManagerSP.DownloadStatus.downloaded
      if not self.params.put_if_unchanged("ModelManager_ActiveBundle", self.selected_bundle.to_dict(),
                                          "ModelManager_DownloadIndex", self._download_request.fileno()):
        raise ModelDownloadCancelled("Download cancelled or replaced")
      self.active_bundle = self.selected_bundle
      self.selected_bundle = None

    except ModelDownloadCancelled:
      self.selected_bundle = None
      raise
    except Exception:
      self.selected_bundle.status = custom.ModelManagerSP.DownloadStatus.failed
      raise

    finally:
      self._report_status()

  def download(self, model_bundle: custom.ModelManagerSP.ModelBundle, destination_path: str) -> None:
    """Main entry point for downloading a model bundle"""
    asyncio.run(self._download_bundle(model_bundle, destination_path))

  def main_thread(self) -> None:
    """Main thread for model management"""
    rk = Ratekeeper(1, print_delay_threshold=None)

    while True:
      try:
        self.available_models = self.model_fetcher.get_available_bundles()
        validate_active_bundle(self.params, self.available_models)
        previous_active_ref = self.active_bundle.ref if self.active_bundle else None
        self.active_bundle = get_active_bundle(self.params)
        if previous_active_ref != (self.active_bundle.ref if self.active_bundle else None):
          self.selected_bundle = None

        with self._request_snapshot() as request:
          if request is not None:
            index_to_download = int(request.read())
            if model_to_download := next((model for model in self.available_models if model.index == index_to_download), None):
              try:
                self.download(model_to_download, Paths.model_root())
              except ModelDownloadCancelled:
                pass
              except Exception as e:
                cloudlog.exception(e)
              finally:
                self.params.remove_if_unchanged("ModelManager_DownloadIndex", request.fileno())
                # Retain a failed bundle for status display and retry until the
                # next selection. Successful and cancelled downloads clear it.
                if self.selected_bundle and self.selected_bundle.status != custom.ModelManagerSP.DownloadStatus.failed:
                  self.selected_bundle = None

        if self.params.get("ModelManager_ClearCache"):
          self.clear_model_cache()
          self.params.remove("ModelManager_ClearCache")

        self._report_status()
        rk.keep_time()

      except Exception as e:
        cloudlog.exception(f"Error in main thread: {str(e)}")
        rk.keep_time()

  def clear_model_cache(self) -> None:
    """
    Clears the model cache directory of all files except those in the active model bundle.
    """

    # Get list of files used by active model bundle
    active_files = []
    if self.active_bundle is not None: # When the default model is active
      for model in self.active_bundle.models:
        if hasattr(model, 'artifact') and model.artifact.fileName:
          active_files.append(model.artifact.fileName)
        if hasattr(model, 'metadata') and model.metadata.fileName:
          active_files.append(model.metadata.fileName)

    # Remove all files except active ones (including their chunk files)
    model_dir = Paths.model_root()
    if not os.path.exists(model_dir):
      return
    try:
      for filename in os.listdir(model_dir):
        base = filename.split('.chunk')[0] if '.chunk' in filename else filename
        if base not in active_files and filename not in active_files:
          file_path = os.path.join(model_dir, filename)
          if os.path.isfile(file_path):
            os.remove(file_path)
      cloudlog.info("Model cache cleared, keeping active model files")
    except Exception as e:
      cloudlog.exception(f"Error clearing model cache: {str(e)}")
      # Keep the request pending so the UI cannot report a failed cleanup as
      # completed. The main loop retries it after the filesystem recovers.
      raise

def main():
  ModelManagerSP().main_thread()


if __name__ == "__main__":
  main()
