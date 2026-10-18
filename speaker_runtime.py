"""CPU-only neural speaker turns. Models are local and hash-pinned; no downloads."""
import hashlib
from model_runtime import app_directory

SPEAKER_HASHES = {
    'segmentation.onnx': '220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079',
    'embedding.onnx': 'c46fad10b5f81e1aa4a60c162714208577093655076c5450f8c469e522ec54ef',
}
SEGMENTATION_URL = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2'
SEGMENTATION_ARCHIVE_HASH = '24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488'
EMBEDDING_URL = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/wespeaker_en_voxceleb_CAM%2B%2B.onnx'


def speaker_directory():
    return app_directory() / 'models' / 'speakers'


def load_speakers():
    import sherpa_onnx as sherpa
    root = speaker_directory()
    for name, expected in SPEAKER_HASHES.items():
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Speaker models are missing or damaged. Extract the full Offline ZIP again, or turn off “Split at voice changes” and retry.')
    config = sherpa.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(root / 'segmentation.onnx'), window_shift_ratio=0.1), num_threads=2),
        embedding=sherpa.SpeakerEmbeddingExtractorConfig(model=str(root / 'embedding.onnx'), num_threads=2),
        clustering=sherpa.FastClusteringConfig(num_clusters=-1, threshold=0.5),
        min_duration_on=0.2, min_duration_off=0.25,
    )
    if not config.validate():
        raise RuntimeError('The offline speaker configuration is invalid.')
    return sherpa.OfflineSpeakerDiarization(config)


def detect_speaker_turns(audio, phase):
    phase('Loading offline speaker models…', -1)
    detector = load_speakers()
    if detector.sample_rate != 16000:
        raise RuntimeError('Speaker model sample rate must be 16000 Hz.')

    def progress(done, total):
        phase(f'Detecting voice changes — {done} / {total} analysis windows', min(99, int(100 * done / total)) if total else -1)
        return 0

    result = detector.process(audio, callback=progress)
    phase('Grouping voices into speaker turns…', -1)
    return [(turn.start, turn.end, turn.speaker) for turn in result.sort_by_start_time()]
