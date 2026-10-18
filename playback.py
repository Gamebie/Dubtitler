"""Audio selection and bounded subtitle replay for the desktop player."""
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QCheckBox, QHBoxLayout, QLabel, QMessageBox
from audio_tracks import list_audio_tracks, default_audio_track


class TrackProbe(QThread):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        try:
            self.completed.emit(list_audio_tracks(self.path))
        except Exception as exc:
            self.failed.emit(str(exc))


def replay_bounds(start, end, duration, context):
    if start < 0 or end <= start:
        raise ValueError('The selected subtitle needs a valid start and end time.')
    if duration <= 0:
        raise ValueError('Wait for the video to load before replaying a subtitle.')
    if start >= duration:
        raise ValueError('The selected subtitle starts after the video ends.')
    return max(0, start - context), min(duration, end + context)


class PlaybackTools:
    def init_playback(self, choose_layout, controls):
        self.track_probe = None
        self.audio_ready = False
        self.audio_track_list = []
        self.preferred_audio_index = None
        track_row = choose_layout.itemAt(0).layout()
        track_row.addWidget(QLabel('Audio track:'))
        self.audio_tracks = QComboBox()
        self.audio_tracks.addItem('Choose a video first', None)
        self.audio_tracks.setMinimumContentsLength(30)
        self.audio_tracks.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.audio_tracks.setEnabled(False)
        track_row.addWidget(self.audio_tracks, 1)
        self.track_hint = QLabel('Select the English dub track for both playback and transcription.')
        self.track_hint.setWordWrap(True)
        choose_layout.addWidget(self.track_hint)
        self.audio_tracks.currentIndexChanged.connect(self.audio_track_changed)
        self.player.tracksChanged.connect(self.sync_playback_audio)
        self.player.mediaStatusChanged.connect(self.replay_media_status)
        self.replay_range = None
        self.replay_seeking = False
        self.replay_timer = QTimer(self)
        self.replay_timer.setInterval(25)
        self.replay_timer.timeout.connect(self.check_replay)
        # Insert before the existing stretch so controls stay together.
        self.replay_button = self.add_button(controls, 'Replay selected (F4)', self.replay_selected)
        self.replay_button.setShortcut('F4')
        self.stop_replay_button = self.add_button(controls, 'Stop replay', lambda: self.stop_replay())
        self.loop_replay = QCheckBox('Loop')
        controls.addWidget(self.loop_replay)
        controls.addWidget(QLabel('Lead / tail:'))
        self.replay_context = QDoubleSpinBox()
        self.replay_context.setRange(0, 5)
        self.replay_context.setSingleStep(0.25)
        self.replay_context.setDecimals(2)
        self.replay_context.setValue(0.5)
        self.replay_context.setSuffix(' s')
        controls.addWidget(self.replay_context)
        self.player.durationChanged.connect(lambda _: self.refresh_actions())

    def load_video(self, path, preferred_audio_index=None):
        self.stop_replay()
        self.video_path = path
        self.preferred_audio_index = preferred_audio_index
        self.video_label.setText(Path(path).name)
        self.video_label.setToolTip(path)
        self.audio_ready = False
        self.audio_track_list = []
        self.audio_tracks.blockSignals(True)
        self.audio_tracks.clear()
        self.audio_tracks.addItem('Reading audio tracks…', None)
        self.audio_tracks.blockSignals(False)
        self.track_hint.setText('Reading available audio tracks…')
        self.player.setSource(QUrl.fromLocalFile(path))
        self.start_track_probe(path)

    def start_track_probe(self, path):
        worker = TrackProbe(path, self)
        self.track_probe = worker
        worker.completed.connect(lambda tracks: self.tracks_found(path, tracks))
        worker.failed.connect(lambda error: self.tracks_failed(path, error))
        worker.finished.connect(self.track_probe_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        self.refresh_actions()

    def track_probe_finished(self):
        self.track_probe = None
        self.refresh_actions()

    def tracks_found(self, path, tracks):
        if path != self.video_path:
            return
        self.audio_track_list = tracks
        self.audio_tracks.blockSignals(True)
        self.audio_tracks.clear()
        for track in tracks:
            description = f'Track {track["index"] + 1} · {track["language"] or "language unspecified"} · {track["codec"].upper()} · {track["channels"]} ch'
            if track['title']:
                description += f' · {track["title"]}'
            self.audio_tracks.addItem(description, track['index'])
        preferred = self.preferred_audio_index
        index = preferred if preferred in [track['index'] for track in tracks] else default_audio_track(tracks)
        if index is None:
            self.audio_tracks.addItem('No audio tracks found', None)
        else:
            self.audio_tracks.setCurrentIndex(self.audio_tracks.findData(index))
        self.audio_tracks.blockSignals(False)
        self.audio_ready = bool(tracks)
        self.audio_track_changed()
        self.refresh_actions()

    def tracks_failed(self, path, message):
        if path != self.video_path:
            return
        self.audio_ready = False
        self.audio_tracks.clear()
        self.audio_tracks.addItem('Could not read audio tracks', None)
        self.track_hint.setText(f'Could not read this video’s audio: {message}. Try another local video.')
        self.refresh_actions()

    def audio_track_changed(self, *_):
        self.stop_replay()
        self.sync_playback_audio()
        if self.dirty:
            self.autosave_timer.start()

    def sync_playback_audio(self):
        index = self.audio_tracks.currentData()
        if index is None:
            if self.audio_ready is False and self.audio_track_list == [] and self.audio_tracks.count() and self.audio_tracks.itemText(0) == 'No audio tracks found':
                self.track_hint.setText('This video has no audio track. Import an SRT or choose another video.')
            return
        preview_tracks = self.player.audioTracks()
        if len(preview_tracks) == len(self.audio_track_list) and index < len(preview_tracks):
            if self.player.activeAudioTrack() != index:
                self.player.setActiveAudioTrack(index)
            self.audio.setMuted(False)
            self.track_hint.setText('Selected track is used for both preview and transcription. Listen to confirm it contains the English dub.')
        else:
            # Never let an unsupported preview silently play a different track.
            self.audio.setMuted(True)
            self.track_hint.setText('Selected track is used for transcription. Preview audio is unavailable until the player can match this file’s tracks.')

    def replay_selected(self):
        self.finish_cell_edit()
        self.stop_replay()
        row = self.table.currentRow()
        if not self.video_path or row < 0 or not self.table.selectedIndexes():
            return
        try:
            from main import parse_timestamp
            start = parse_timestamp(self.table.item(row, 0).text())
            end = parse_timestamp(self.table.item(row, 1).text())
            self.replay_range = replay_bounds(start, end, self.player.duration(), round(self.replay_context.value() * 1000))
        except (ValueError, AttributeError) as exc:
            QMessageBox.warning(self, 'Cannot replay subtitle', str(exc))
            return
        self.replay_seeking = True
        self.player.setPosition(self.replay_range[0])
        self.player.play()
        self.replay_timer.start()
        self.refresh_actions()

    def stop_replay(self, pause=True):
        if self.replay_range is not None and pause:
            self.player.pause()
        self.replay_range = None
        self.replay_seeking = False
        self.replay_timer.stop()
        self.stop_replay_button.setEnabled(False)

    def manual_seek(self, position):
        self.stop_replay(pause=False)
        self.player.setPosition(max(0, position))

    def check_replay(self):
        if self.replay_range is None:
            return
        start, end = self.replay_range
        position = self.player.position()
        if self.replay_seeking:
            if position < start:
                return
            self.replay_seeking = False
        if position >= end:
            self.replay_boundary()

    def replay_boundary(self):
        if self.replay_range is None:
            return
        start, end = self.replay_range
        if self.loop_replay.isChecked():
            self.replay_seeking = True
            self.player.setPosition(start)
            self.player.play()
        else:
            self.stop_replay()
            self.player.setPosition(end)

    def replay_media_status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self.replay_boundary()
