import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from subtitle_timing import make_cues
from transcription_options import normalize_options, recognition_hints, correct_text
from transcription_job import run_job
from speaker_runtime import load_speakers
from recovery import read_snapshot
from PySide6.QtWidgets import QApplication, QMessageBox
from main import MainWindow

APP = QApplication.instance() or QApplication([])


def segment(*words):
    words = [NS(start=start, end=end, word=text) for start, end, text in words]
    return NS(start=words[0].start, end=words[-1].end, text=''.join(w.word for w in words), words=words)


class TimingTests(unittest.TestCase):
    def test_cue_never_bridges_a_quiet_region(self):
        result = make_cues([segment((1, 1.5, ' Hello'), (4, 4.5, ' again.'))], [(0.9, 1.6), (3.9, 4.6)])
        self.assertEqual(result, [(1000, 1500, 'Hello'), (4000, 4500, 'again.')])

    def test_voice_change_splits_one_recognition_segment(self):
        words = segment((0.1, 0.7, ' Ready?'), (0.8, 1.3, ' Yes!'))
        self.assertEqual(make_cues([words], [(0, 2)], [(0, 0.75, 0), (0.75, 2, 1)]),
                         [(100, 700, 'Ready?'), (800, 1300, 'Yes!')])
        self.assertEqual(len(make_cues([words], [(0, 2)], [(0, 2, 0)])), 1)

    def test_word_gap_splits_even_with_continuous_background_speech(self):
        words = segment((0.1, 0.5, ' Hello'), (1.1, 1.5, ' again'))
        self.assertEqual(len(make_cues([words], [(0, 2)])), 2)

    def test_silence_hallucination_is_removed_and_edges_clamped(self):
        words = segment((0.1, 0.5, ' Intro'), (1, 1.6, ' Real'), (3, 3.4, ' Fake'))
        self.assertEqual(make_cues([words], [(1.1, 1.5)]), [(1100, 1500, 'Real')])

    def test_silence_and_invalid_word_times_cannot_produce_cues(self):
        words = segment((0, 0, ' Zero'), (float('nan'), 1, ' Bad'), (1, 2, ' Hello'))
        self.assertEqual(make_cues([words], []), [])
        self.assertEqual(make_cues([words], [(0, 3)]), [(1000, 2000, 'Hello')])

    def test_readability_limits_and_no_overlaps(self):
        words = segment(*[(i * .6, i * .6 + .5, ' volleyball') for i in range(25)])
        cues = make_cues([words], [(0, 20)])
        self.assertGreater(len(cues), 2)
        self.assertEqual(' '.join(c[2] for c in cues), words.text.strip())
        self.assertTrue(all(end - start <= 6000 and len(text) <= 84 for start, end, text in cues))
        overlap = make_cues([segment((0, 1, ' A')), segment((.8, 1.5, ' B'))], [(0, 2)])
        self.assertEqual(overlap, [(0, 1000, 'A'), (1000, 1500, 'B')])

    def test_missing_alignment_cannot_span_silence(self):
        self.assertEqual(make_cues([NS(start=0, end=5, text='unsplittable')], [(0, 1), (4, 5)]), [])

    def test_returning_speaker_and_overlapping_voice_intervals(self):
        words = segment((0, .4, ' A'), (.5, .9, ' B'), (1, 1.4, ' A'))
        turns = [(0, .45, 3), (.45, .95, 7), (1, 1.5, 3), (.7, .8, 3)]
        self.assertEqual(len(make_cues([words], [(0, 2)], turns)), 3)


class HintsTests(unittest.TestCase):
    def test_name_hints_go_to_recognizer_without_automatic_rewriting(self):
        options = normalize_options({'context': 'Haikyuu', 'names': 'Seijou, Aoba Johsai'})
        hints = recognition_hints(options)
        self.assertIn('Haikyuu', hints['initial_prompt'])
        self.assertEqual(hints['hotwords'], 'Seijou, Aoba Johsai')
        self.assertEqual(correct_text('Say Joe is here.', options), 'Say Joe is here.')

    def test_explicit_rules_preserve_punctuation_and_word_boundaries(self):
        options = normalize_options({'replacements': 'say joe => Seijou; A+B => Team'})
        self.assertEqual(correct_text('“SAY JOE,” says joey; A+B!', options), '“Seijou,” says joey; Team!')
        self.assertEqual(correct_text('unsay joe and say joey', options), 'unsay joe and say joey')

    def test_rules_do_not_cascade_and_input_is_bounded(self):
        self.assertEqual(correct_text('A B', normalize_options({'replacements': 'A => B; B => C'})), 'B C')
        for options in ({'replacements': 'broken'}, {'replacements': 'a =>'}, {'context': 'x' * 201}, {'speaker_changes': 'yes'}):
            with self.assertRaises(ValueError):
                normalize_options(options)


class JobTests(unittest.TestCase):
    def job(self, speech, options=None, turns=()):
        model, connection = Mock(), Mock()
        model.transcribe.return_value = ([segment((1, 1.4, ' Say'), (1.4, 1.8, ' Joe'))], NS(duration=3))
        with patch('transcription_job.decode_audio_track', return_value=[0]), patch('transcription_job.detect_speech', return_value=speech), patch('transcription_job.detect_speaker_turns', return_value=turns) as speakers, patch('transcription_job.load_model', return_value=model) as loader:
            run_job(connection, 'test', 'base.en', False, 0, options)
        return connection, model, speakers, loader

    def test_quiet_audio_skips_models_and_returns_no_cues(self):
        connection, model, speakers, loader = self.job([])
        connection.send.assert_called_with(('completed', []))
        model.transcribe.assert_not_called()
        speakers.assert_not_called()
        loader.assert_not_called()

    def test_hints_word_timing_and_voice_toggle_reach_job(self):
        connection, model, speakers, _ = self.job([(0, 3)], {'names': 'Seijou', 'replacements': 'say joe => Seijou', 'speaker_changes': False})
        speakers.assert_not_called()
        self.assertTrue(model.transcribe.call_args.kwargs['word_timestamps'])
        self.assertEqual(model.transcribe.call_args.kwargs['hotwords'], 'Seijou')
        connection.send.assert_called_with(('completed', [(1000, 1800, 'Seijou')]))

    def test_speaker_model_failure_cannot_apply_partial_transcript(self):
        connection = Mock()
        with patch('transcription_job.decode_audio_track', return_value=[0]), patch('transcription_job.detect_speech', return_value=[(0, 1)]), patch('transcription_job.detect_speaker_turns', side_effect=RuntimeError('Bad speaker model')):
            run_job(connection, 'test', 'base.en', False, 0)
        connection.send.assert_called_with(('failed', 'Bad speaker model'))
        connection.close.assert_called_once()

    def test_missing_or_corrupt_speaker_assets_fail_locally(self):
        with tempfile.TemporaryDirectory() as temp, patch('speaker_runtime.speaker_directory', return_value=Path(temp)):
            with self.assertRaisesRegex(RuntimeError, 'turn off'):
                load_speakers()
            (Path(temp) / 'segmentation.onnx').write_bytes(b'bad')
            with self.assertRaisesRegex(RuntimeError, 'damaged'):
                load_speakers()


class ContextUITests(unittest.TestCase):
    def test_preset_busy_lock_and_recovery_of_draft_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            window = MainWindow(recovery_directory=temp, offer_recovery=False)
            try:
                window.apply_context_preset(1)
                self.assertIn('Seijou', window.name_hints.text())
                self.assertEqual(window.exact_replacements.text(), '')
                window.set_rows([(0, 1000, 'Keep')])
                window.exact_replacements.setText('unfinished rule')
                window.save_recovery()
                data = read_snapshot(window.recovery_path)
                self.assertEqual(data['transcription_options']['replacements'], 'unfinished rule')
                window.restore_transcription_options(data['transcription_options'])
                with patch.object(QMessageBox, 'warning') as warning:
                    window.transcribe()
                    warning.assert_called_once()
                window.busy = True
                window.refresh_actions()
                self.assertFalse(window.name_hints.isEnabled())
                self.assertFalse(window.speaker_changes.isEnabled())
            finally:
                window.busy = False
                window.mark_saved()
                window.close()


if __name__ == '__main__':
    unittest.main()
