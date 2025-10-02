# main.py
"""
Kivy app: Press-and-hold recorder that writes 16 kHz mono PCM_16 WAV (pcm_s16le).
Works on Android (AudioRecord via pyjnius) and on desktop (sounddevice fallback).
Sends WAV to SarvamAI wrapper function (same flow as your core) and displays returned text.
"""

import os
import tempfile
import threading
import time
import wave
import struct
import json

from kivy.app import App
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.clock import mainthread

KV = '''
<RootWidget>:
    orientation: 'vertical'
    padding: 12
    spacing: 8

    BoxLayout:
        size_hint_y: None
        height: '40dp'
        spacing: 8
        Label:
            text: 'SarvamAI API key:'
            size_hint_x: None
            width: '130dp'
        TextInput:
            id: api_key
            multiline: False

    TextInput:
        id: output_box
        text: ''
        multiline: True
        readonly: False
        size_hint_y: 0.78

    BoxLayout:
        size_hint_y: None
        height: '64dp'
        spacing: 8
        Button:
            id: record_btn
            text: '⏺ Hold to Record'
            on_touch_down: root.on_record_press(args[1])
            on_touch_up: root.on_record_release(args[1])
        Button:
            text: 'Reset'
            on_release: root.ids.output_box.text = ''
'''

# Try to detect Android environment and import pyjnius if available
ANDROID = False
try:
    # pyjnius modules only exist on Android build with pyjnius available
    from jnius import autoclass, jarray
    ANDROID = True
except Exception:
    ANDROID = False

# Desktop fallback imports
if not ANDROID:
    try:
        import sounddevice as sd
        import numpy as np
        import soundfile as sf
        HAVE_DESKTOP_AUDIO = True
    except Exception:
        HAVE_DESKTOP_AUDIO = False

# SarvamAI wrapper (adapted from your core snippet)
def translate_audio_with_sarvamai(wav_path, api_key="", model="saaras:v2.5", prompt="casual chat"):
    """
    Call SarvamAI flow with given wav file path.
    Returns (success: bool, message: str)
    """
    try:
        # Local import to avoid failing on devices where sarvamai isn't available
        from sarvamai import SarvamAI
    except Exception as e:
        return False, f"sarvamai lib not available on runtime: {e}"

    try:
        client = SarvamAI(api_subscription_key=api_key)

        job = client.speech_to_text_translate_job.create_job(
            model=model,
            with_diarization=False,
            num_speakers=1,
            prompt=prompt
        )

        job.upload_files(file_paths=[wav_path])
        job.start()
        final_status = job.wait_until_complete()

        if job.is_failed():
            return False, "STT job failed."

        output_dir = os.path.join(os.getcwd(), "sarvamai_output")
        os.makedirs(output_dir, exist_ok=True)
        job.download_outputs(output_dir=output_dir)

        # Try to extract text from outputs
        aggregated = []
        for root, _, files in os.walk(output_dir):
            for fname in files:
                if fname.lower().endswith('.txt'):
                    with open(os.path.join(root, fname), 'r', encoding='utf-8') as f:
                        txt = f.read().strip()
                    if txt:
                        aggregated.append(f"--- {fname} ---\n{txt}")
                elif fname.lower().endswith('.json'):
                    try:
                        with open(os.path.join(root, fname), 'r', encoding='utf-8') as f:
                            j = json.load(f)
                        for k in ('text', 'transcript', 'translation', 'translated_text'):
                            if k in j and isinstance(j[k], str) and j[k].strip():
                                aggregated.append(f"--- {fname}:{k} ---\n{j[k].strip()}")
                    except Exception:
                        pass

        if aggregated:
            return True, "\n\n".join(aggregated)
        else:
            return True, f"Output downloaded to: {output_dir} (no text/json translation found)."
    except Exception as e:
        return False, f"Translation error: {repr(e)}"


class RootWidget(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.audio_thread = None
        self.recording = False
        self.wav_path = None

        # Android-specific audio objects
        self._ar = None  # AudioRecord instance (pyjnius) on Android
        self._buffer_size = 0

    def append_output(self, txt):
        # Must run on UI thread
        @mainthread
        def _do():
            self.ids.output_box.text += str(txt) + "\n"
        _do()

    def on_record_press(self, touch):
        # ensure it's a press on button
        if not self.ids.record_btn.collide_point(*touch.pos):
            return
        self.ids.record_btn.text = "Recording..."
        self.ids.output_box.text = self.ids.output_box.text  # ensure widget exists
        # Start recording thread
        self.audio_thread = threading.Thread(target=self._record_worker, daemon=True)
        self.recording = True
        self.audio_thread.start()

    def on_record_release(self, touch):
        if not self.ids.record_btn.collide_point(*touch.pos):
            return
        self.recording = False
        self.ids.record_btn.text = "⏺ Hold to Record"
        # Upload and translate in separate thread so UI remains responsive
        t = threading.Thread(target=self._post_process_and_translate, daemon=True)
        t.start()

    def _record_worker(self):
        # Create temp wav path
        fd, path = tempfile.mkstemp(prefix="rec_", suffix=".wav")
        os.close(fd)
        self.wav_path = path

        sample_rate = 16000
        channels = 1
        sampwidth = 2  # bytes per sample (16-bit)

        if ANDROID:
            try:
                self.append_output("Starting Android AudioRecord capture (16kHz, mono, 16-bit).")
                self._record_android_pcm(path, sample_rate, channels)
            except Exception as e:
                self.append_output("Android record error: " + str(e))
        else:
            # Desktop fallback using sounddevice
            if not HAVE_DESKTOP_AUDIO:
                self.append_output("Desktop audio libs not available (sounddevice/soundfile). Cannot record.")
                return
            try:
                self.append_output("Starting desktop capture (sounddevice). Speak now...")
                duration = 600  # max seconds guard; we'll stop earlier when user releases
                frames = []
                def callback(indata, frames_count, time_info, status):
                    if not self.recording:
                        raise sd.CallbackStop()
                    frames.append(indata.copy())
                with sd.InputStream(samplerate=sample_rate, channels=channels, dtype='int16', callback=callback):
                    while self.recording:
                        time.sleep(0.05)
                data = b''.join([f.tobytes() for f in frames])
                # write wav
                with wave.open(path, 'wb') as wf:
                    wf.setnchannels(channels)
                    wf.setsampwidth(sampwidth)
                    wf.setframerate(sample_rate)
                    wf.writeframes(data)
                self.append_output(f"Saved WAV to: {path}")
            except Exception as e:
                self.append_output("Desktop record error: " + str(e))
                return

    def _record_android_pcm(self, out_wav_path, sample_rate=16000, channels=1):
        """
        Use Android AudioRecord via pyjnius to capture raw PCM 16-bit and write WAV.
        """
        # pyjnius classes
        AudioRecord = autoclass('android.media.AudioRecord')
        AudioFormat = autoclass('android.media.AudioFormat')
        AudioManager = autoclass('android.media.AudioManager')
        AudioTrack = autoclass('android.media.AudioTrack')
        MediaRecorder = autoclass('android.media.MediaRecorder')
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        activity = PythonActivity.mActivity

        # constants
        AUDIO_SOURCE_MIC = MediaRecorder.AudioSource.MIC
        CHANNEL_IN_MONO = AudioFormat.CHANNEL_IN_MONO
        ENCODING_PCM_16BIT = AudioFormat.ENCODING_PCM_16BIT

        # Determine min buffer size
        min_buf = AudioRecord.getMinBufferSize(sample_rate, CHANNEL_IN_MONO, ENCODING_PCM_16BIT)
        # We read in chunks of min_buf/2 typically
        if min_buf <= 0:
            min_buf = sample_rate * 2  # fallback
        self._buffer_size = int(min_buf)

        # Create AudioRecord instance
        ar = AudioRecord(AUDIO_SOURCE_MIC, sample_rate, CHANNEL_IN_MONO, ENCODING_PCM_16BIT, self._buffer_size)
        if ar.getState() != AudioRecord.STATE_INITIALIZED:
            raise RuntimeError("AudioRecord initialization failed (state != INITIALIZED)")

        # Prepare WAV file for writing
        wf = wave.open(out_wav_path, 'wb')
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)

        # Create Java short[] buffer
        # jnius.jarray('h', size) is used to create Java short array
        chunk_size = int(self._buffer_size // 2)  # buffer_size is in bytes; shorts are 2 bytes
        java_buffer = jarray('h', chunk_size)

        ar.startRecording()
        self.append_output("Recording (Android) ... speak now")

        try:
            while self.recording:
                read = ar.read(java_buffer, 0, chunk_size)
                if read > 0:
                    # convert Java short[] to Python bytes little-endian
                    # java_buffer is iterable; iterate first `read` elements
                    b = bytearray()
                    for i in range(read):
                        # short value may be Python int already
                        sval = int(java_buffer[i])
                        # pack as little-endian signed short
                        b.extend(struct.pack('<h', sval))
                    wf.writeframes(b)
                else:
                    time.sleep(0.01)
        finally:
            try:
                ar.stop()
                ar.release()
            except Exception:
                pass
            wf.close()
            self.append_output(f"Saved WAV to: {out_wav_path}")

    def _post_process_and_translate(self):
        # Small pause to ensure file closed
        time.sleep(0.2)
        path = self.wav_path
        if not path or not os.path.exists(path):
            self.append_output("No recorded file found.")
            return

        self.append_output("Starting translation upload...")
        api_key = self.ids.api_key.text.strip()

        success, message = translate_audio_with_sarvamai(path, api_key=api_key, model="saaras:v2.5")
        if success:
            self.append_output("Translation result:")
            self.append_output(message)
        else:
            self.append_output("Translation failed: " + message)


class SpeechTranslatorApp(App):
    def build(self):
        Builder.load_string(KV)
        return RootWidget()


if __name__ == '__main__':
    SpeechTranslatorApp().run()
