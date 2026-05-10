#!/usr/bin/env python3
"""
VidSubKh — AI Translator Pipeline

Dependencies:
  pip install openai google-cloud-translate elevenlabs moviepy \
              deepfilternet srt pydub torch torchaudio

External tools needed:
  - ffmpeg (in PATH)
  - wav2lip model weights (for lip sync)
"""

import sys
import json
import os
import tempfile
import subprocess
import shutil
from pathlib import Path


def step(name: str, pct: int):
    print(f'STEP:{name}:{pct}', flush=True)


def err(msg: str):
    print(f'ERROR:{msg}', file=sys.stderr, flush=True)


# ─── Step 1: Extract audio from video ─────────────────────────────────────────
def extract_audio(video_path: str, workdir: str) -> str:
    audio_path = os.path.join(workdir, 'extracted_audio.wav')
    subprocess.run([
        'ffmpeg', '-y', '-i', video_path,
        '-vn', '-ar', '16000', '-ac', '1',
        '-f', 'wav', audio_path
    ], check=True, capture_output=True)
    return audio_path


# ─── Step 2: Noise removal (DeepFilterNet) ────────────────────────────────────
def remove_noise(audio_path: str, workdir: str) -> str:
    try:
        from df.enhance import enhance, init_df, load_audio, save_audio
        model, df_state, _ = init_df()
        audio, _ = load_audio(audio_path, sr=df_state.sr())
        enhanced = enhance(model, df_state, audio)
        cleaned_path = os.path.join(workdir, 'cleaned_audio.wav')
        save_audio(cleaned_path, enhanced, df_state.sr())
        return cleaned_path
    except ImportError:
        print('STEP:noise_skipped:0', flush=True)
        return audio_path


# ─── Step 3: Separate background music (Demucs) ───────────────────────────────
def separate_music(audio_path: str, workdir: str) -> tuple:
    """Returns (vocals_path, music_path)"""
    try:
        subprocess.run([
            'python3', '-m', 'demucs',
            '-n', 'htdemucs',
            '--two-stems=vocals',
            '-o', workdir,
            audio_path
        ], check=True, capture_output=True)
        stem_dir = Path(workdir) / 'htdemucs' / Path(audio_path).stem
        vocals = str(stem_dir / 'vocals.wav')
        music  = str(stem_dir / 'no_vocals.wav')
        return vocals, music
    except Exception:
        return audio_path, None


# ─── Step 4: Transcribe with Whisper ──────────────────────────────────────────
def transcribe(audio_path: str, source_lang: str, api_key: str) -> list:
    """Returns list of {start, end, text} segments."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    with open(audio_path, 'rb') as f:
        kwargs = {'file': f, 'model': 'whisper-1', 'response_format': 'verbose_json', 'timestamp_granularities': ['segment']}
        if source_lang and source_lang.lower() not in ('auto', 'auto-detect'):
            kwargs['language'] = source_lang[:2].lower()
        transcript = client.audio.transcriptions.create(**kwargs)

    return [{'start': s.start, 'end': s.end, 'text': s.text.strip()} for s in transcript.segments]


# ─── Step 5: Translate segments ───────────────────────────────────────────────
def translate_segments(segments: list, target_lang: str, google_key: str) -> list:
    from google.cloud import translate_v2 as googletrans
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = google_key  # path to service account JSON
    client = googletrans.Client()

    lang_map = {
        'Khmer (ខ្មែរ)': 'km', 'English': 'en', 'Chinese': 'zh',
        'Japanese': 'ja', 'Korean': 'ko', 'French': 'fr',
        'Spanish': 'es', 'German': 'de', 'Thai': 'th', 'Vietnamese': 'vi',
    }
    target_code = lang_map.get(target_lang, 'km')

    texts = [s['text'] for s in segments]
    results = client.translate(texts, target_language=target_code)

    translated = []
    for seg, res in zip(segments, results):
        translated.append({**seg, 'translated': res['translatedText']})
    return translated


# ─── Step 6: Generate translated voice (ElevenLabs) ───────────────────────────
def synthesize_voice(segments: list, gender: str, voice_clone: bool,
                     original_audio: str, api_key: str, workdir: str) -> list:
    from elevenlabs import ElevenLabs, VoiceSettings

    client = ElevenLabs(api_key=api_key)

    # Pick voice based on gender
    voice_map = {
        'Male':   'pNInz6obpgDQGcFmaJgB',  # Adam
        'Female': 'EXAVITQu4vr4xnSDxMaL',  # Bella
        'Both':   'pNInz6obpgDQGcFmaJgB',   # Default to male, switch per segment
    }
    voice_id = voice_map.get(gender, voice_map['Male'])

    audio_segments = []
    for i, seg in enumerate(segments):
        audio_path = os.path.join(workdir, f'seg_{i:04d}.mp3')
        audio = client.generate(
            text=seg['translated'],
            voice=voice_id,
            voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.8),
            model='eleven_multilingual_v2',
        )
        with open(audio_path, 'wb') as f:
            for chunk in audio:
                f.write(chunk)
        audio_segments.append({**seg, 'audio_file': audio_path})

    return audio_segments


# ─── Step 7: Assemble final video with ffmpeg ──────────────────────────────────
def assemble_video(video_path: str, segments: list, music_path: str,
                   options: dict, output_path: str, workdir: str):
    """Mix translated audio segments back onto the video with optional music."""
    from pydub import AudioSegment

    # Get video duration
    probe = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', video_path],
        capture_output=True, text=True
    )
    duration_ms = int(float(json.loads(probe.stdout)['format']['duration']) * 1000)

    # Build timeline
    timeline = AudioSegment.silent(duration=duration_ms)
    for seg in segments:
        if not os.path.exists(seg.get('audio_file', '')):
            continue
        audio_clip = AudioSegment.from_file(seg['audio_file'])
        start_ms = int(seg['start'] * 1000)
        timeline = timeline.overlay(audio_clip, position=start_ms)

    # Mix with background music if available
    if music_path and options.get('backgroundMusic') and os.path.exists(music_path):
        music = AudioSegment.from_file(music_path)
        music = music - 6  # lower music volume by 6dB
        timeline = timeline.overlay(music)

    mixed_audio = os.path.join(workdir, 'mixed_audio.wav')
    timeline.export(mixed_audio, format='wav')

    # Build ffmpeg command
    cmd = ['ffmpeg', '-y', '-i', video_path, '-i', mixed_audio]

    if options.get('subtitles'):
        srt_path = os.path.join(workdir, 'subtitles.srt')
        write_srt(segments, srt_path)
        cmd += ['-vf', f'subtitles={srt_path}']

    cmd += [
        '-c:v', 'libx264', '-crf', '18',
        '-c:a', 'aac', '-b:a', '192k',
        '-map', '0:v', '-map', '1:a',
        '-shortest', output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)


# ─── SRT file writer ──────────────────────────────────────────────────────────
def write_srt(segments: list, srt_path: str):
    def fmt_time(secs):
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        s = int(secs % 60)
        ms = int((secs - int(secs)) * 1000)
        return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'

    with open(srt_path, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments, 1):
            text = seg.get('translated', seg.get('text', ''))
            f.write(f'{i}\n')
            f.write(f'{fmt_time(seg["start"])} --> {fmt_time(seg["end"])}\n')
            f.write(f'{text}\n\n')


# ─── Main pipeline: translate ─────────────────────────────────────────────────
def run_translate(file_path, source_lang, target_lang, gender, options, api_keys, job_id):
    workdir = tempfile.mkdtemp(prefix=f'vidsubkh_{job_id}_')
    try:
        step('analyzing', 5)
        is_video = file_path.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm'))

        if is_video:
            step('extracting_audio', 10)
            audio_path = extract_audio(file_path, workdir)
        else:
            audio_path = file_path

        if options.get('noiseRemoval'):
            step('noise_removal', 18)
            audio_path = remove_noise(audio_path, workdir)

        music_path = None
        if options.get('backgroundMusic') and is_video:
            step('separating_music', 25)
            audio_path, music_path = separate_music(audio_path, workdir)

        step('transcribing', 35)
        segments = transcribe(audio_path, source_lang, api_keys.get('openai', ''))

        step('translating', 55)
        segments = translate_segments(segments, target_lang, api_keys.get('google', ''))

        step('generating_voice', 70)
        segments = synthesize_voice(
            segments, gender,
            options.get('voiceCloning', False),
            audio_path,
            api_keys.get('elevenlabs', ''),
            workdir
        )

        if options.get('srtExport'):
            srt_path = os.path.join(os.path.dirname(file_path), 'subtitles_translated.srt')
            write_srt(segments, srt_path)

        step('done', 100)

        result = {
            'segments': [
                {
                    'start': s['start'],
                    'end': s['end'],
                    'original': s['text'],
                    'translated': s['translated'],
                    'audio_file': s.get('audio_file', ''),
                }
                for s in segments
            ],
            'workdir': workdir,
            'original_file': file_path,
            'music_path': music_path or '',
        }
        print(f'RESULT:{json.dumps(result)}', flush=True)

    except Exception as e:
        import traceback
        err(f'{e}\n{traceback.format_exc()}')
        shutil.rmtree(workdir, ignore_errors=True)
        sys.exit(1)


# ─── Main pipeline: render ────────────────────────────────────────────────────
def run_render(video_path, subtitles_json, options_json, output_path, job_id):
    subtitles = json.loads(subtitles_json)
    options   = json.loads(options_json)
    workdir   = tempfile.mkdtemp(prefix=f'vidsubkh_render_{job_id}_')
    try:
        print('RENDER:10', flush=True)
        assemble_video(video_path, subtitles, subtitles[0].get('music_path', ''),
                       options, output_path, workdir)
        print('RENDER:100', flush=True)
        print(f'RESULT:{json.dumps({"output": output_path})}', flush=True)
    except Exception as e:
        import traceback
        err(f'{e}\n{traceback.format_exc()}')
        sys.exit(1)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ─── Entrypoint ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    cmd = sys.argv[1]

    if cmd == 'translate':
        _, _, file_path, source_lang, target_lang, gender, options_json, api_keys_json, job_id = sys.argv
        run_translate(file_path, source_lang, target_lang, gender,
                      json.loads(options_json), json.loads(api_keys_json), job_id)

    elif cmd == 'render':
        _, _, video_path, subtitles_json, options_json, output_path, job_id = sys.argv
        run_render(video_path, subtitles_json, options_json, output_path, job_id)
