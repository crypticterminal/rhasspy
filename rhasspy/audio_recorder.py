#!/usr/bin/env python3
import os
import logging
import subprocess
import threading
import time
import wave
import io
import re
import audioop
from queue import Queue
from typing import Dict, Any, Callable, Optional
from collections import defaultdict

from .actor import RhasspyActor
from .utils import convert_wav
from .mqtt import MqttSubscribe, MqttMessage

# -----------------------------------------------------------------------------
# Events
# -----------------------------------------------------------------------------

class AudioData:
    def __init__(self, data: bytes):
        self.data = data

class StartStreaming:
    def __init__(self, receiver):
        self.receiver = receiver

class StopStreaming:
    def __init__(self, receiver):
        self.receiver = receiver

class StartRecordingToBuffer:
    def __init__(self, buffer_name):
        self.buffer_name = buffer_name

class StopRecordingToBuffer:
    def __init__(self, buffer_name, receiver=None):
        self.buffer_name = buffer_name
        self.receiver = receiver

# -----------------------------------------------------------------------------
# Dummy audio recorder
# -----------------------------------------------------------------------------

class DummyAudioRecorder:
    '''Does nothing'''
    pass

# -----------------------------------------------------------------------------
# PyAudio based audio recorder
# https://people.csail.mit.edu/hubert/pyaudio/
# -----------------------------------------------------------------------------

class PyAudioRecorder(RhasspyActor):
    '''Records from microphone using pyaudio'''
    def __init__(self):
        RhasspyActor.__init__(self)
        self.mic = None
        self.audio = None
        self.receivers = []
        self.buffers = defaultdict(bytes)

    def to_started(self, from_state):
        self.device_index = self.config.get('device') \
            or self.profile.get('microphone.pyaudio.device')

        if self.device_index is not None:
            try:
                self.device_index = int(self.device_index)
            except:
                self.device_index = -1

            if self.device_index < 0:
                # Default device
                self.device_index = None

        self.frames_per_buffer = int(self.profile.get(
            'microphone.pyaudio.frames_per_buffer', 480))

    def in_started(self, message, sender):
        if isinstance(message, StartStreaming):
            self.receivers.append(message.receiver)
            self.transition('recording')
        elif isinstance(message, StartRecordingToBuffer):
            self.buffers[message.buffer_name] = bytes()
            self.transition('recording')

    def to_recording(self, from_state):
        import pyaudio

        # Start audio system
        def stream_callback(data, frame_count, time_info, status):
            if len(data) > 0:
                # Send to this actor to avoid threading issues
                self.send(self.myAddress, AudioData(data))

            return (data, pyaudio.paContinue)

        self.audio = pyaudio.PyAudio()
        data_format = self.audio.get_format_from_width(2)  # 16-bit
        self.mic = self.audio.open(format=data_format,
                                    channels=1,
                                    rate=16000,
                                    input_device_index=self.device_index,
                                    input=True,
                                    stream_callback=stream_callback,
                                    frames_per_buffer=self.frames_per_buffer)

        self.mic.start_stream()
        self._logger.debug('Recording from microphone (PyAudio, device=%s)' % self.device_index)

    # -------------------------------------------------------------------------

    def in_recording(self, message, sender):
        if isinstance(message, AudioData):
            # Forward to subscribers
            for receiver in self.receivers:
                self.send(receiver, message)

            # Append to buffers
            for receiver in self.buffers:
                self.buffers[receiver] += message.data
        elif isinstance(message, StartStreaming):
            self.receivers.append(message.receiver)
        elif isinstance(message, StartRecordingToBuffer):
            self.buffers[message.buffer_name] = bytes()
        elif isinstance(message, StopStreaming):
            if message.receiver is None:
                # Clear all receivers
                self.receivers.clear()
            else:
                self.receivers.remove(message.receiver)
        elif isinstance(message, StopRecordingToBuffer):
            if message.buffer_name is None:
                # Clear all buffers
                self.buffers.clear()
            else:
                # Respond with buffer
                buffer = self.buffers.pop(message.buffer_name, bytes())
                self.send(message.receiver or sender, AudioData(buffer))

        # Check to see if anyone is still listening
        if (len(self.receivers) == 0) and (len(self.buffers) == 0):
            # Terminate audio recording
            self.mic.stop_stream()
            self.audio.terminate()
            self.transition('started')
            self._logger.debug('Stopped recording from microphone (PyAudio)')

    def to_stopped(self, from_state):
        if self.mic is not None:
            self.mic.stop_stream()
            self.mic = None
            self._logger.debug('Stopped recording from microphone (PyAudio)')

        if self.audio is not None:
            self.audio.terminate()
            self.audio = None

    # -------------------------------------------------------------------------

    @classmethod
    def get_microphones(self) -> Dict[Any, Any]:
        import pyaudio

        mics: Dict[Any, Any] = {}
        audio = pyaudio.PyAudio()
        default_name = audio.get_default_input_device_info().get('name')
        for i in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(i)
            mics[i] = info['name']

            if mics[i] == default_name:
                mics[i] = mics[i] + '*'

        audio.terminate()

        return mics

    # -------------------------------------------------------------------------

    @classmethod
    def test_microphones(self, chunk_size:int) -> Dict[Any, Any]:
        import pyaudio

        # Thanks to the speech_recognition library!
        # https://github.com/Uberi/speech_recognition/blob/master/speech_recognition/__init__.py
        result = {}
        audio = pyaudio.PyAudio()
        try:
            default_name = audio.get_default_input_device_info().get('name')
            for device_index in range(audio.get_device_count()):
                device_info = audio.get_device_info_by_index(device_index)
                device_name = device_info.get("name")
                if device_name == default_name:
                    device_name = device_name + '*'

                try:
                    # read audio
                    data_format = audio.get_format_from_width(2)  # 16-bit
                    pyaudio_stream = audio.open(
                        input_device_index=device_index,
                        channels=1,
                        format=pyaudio.paInt16,
                        rate=16000,
                        input=True)
                    try:
                        buffer = pyaudio_stream.read(chunk_size)
                        if not pyaudio_stream.is_stopped():
                            pyaudio_stream.stop_stream()
                    finally:
                        pyaudio_stream.close()
                except:
                    result[device_index] = '%s (error)' % device_name
                    continue

                # compute RMS of debiased audio
                energy = -audioop.rms(buffer, 2)
                energy_bytes = bytes([energy & 0xFF, (energy >> 8) & 0xFF])
                debiased_energy = audioop.rms(
                    audioop.add(buffer, energy_bytes * (len(buffer) // 2), 2), 2)

                if debiased_energy > 30:  # probably actually audio
                    result[device_index] = '%s (working!)' % device_name
                else:
                    result[device_index] = '%s (no sound)' % device_name
        finally:
            audio.terminate()

        return result

# -----------------------------------------------------------------------------
# ARecord based audio recorder
# -----------------------------------------------------------------------------

class ARecordAudioRecorder(RhasspyActor):
    '''Records from microphone using arecord'''
    def __init__(self):
        # Chunk size is set to 30 ms for webrtcvad
        RhasspyActor.__init__(self)
        self.record_proc = None
        self.receivers = []
        self.buffers = {}
        self.recording_thread = None
        self.is_recording = True

    def to_started(self, from_state):
        self.device_name = self.config.get('device') \
            or self.profile.get('microphone.arecord.device')

        if self.device_name is not None:
            self.device_name = str(self.device_name)
            if len(self.device_name) == 0:
                self.device_name = None

        self.chunk_size = int(self.profile.get(
            'microphone.arecord.chunk_size', 480*2))

    def in_started(self, message, sender):
        if isinstance(message, StartStreaming):
            self.receivers.append(message.receiver)
            self.transition('recording')
        elif isinstance(message, StartRecordingToBuffer):
            self.buffers[message.buffer_name] = bytes()
            self.transition('recording')

    def to_recording(self, from_state):
        # 16-bit 16Khz mono WAV
        arecord_cmd = ['arecord',
                      '-q',
                      '-r', '16000',
                      '-f', 'S16_LE',
                      '-c', '1',
                      '-t', 'raw']

        if self.device_name is not None:
            # Use specific ALSA device
            arecord_cmd.extend(['-D', self.device_name])

        self._logger.debug(arecord_cmd)

        def process_data():
            self.record_proc = subprocess.Popen(arecord_cmd, stdout=subprocess.PIPE)
            while self.is_recording:
                # Pull from process STDOUT
                data = self.record_proc.stdout.read(self.chunk_size)
                if len(data) > 0:
                    # Send to this actor to avoid threading issues
                    self.send(self.myAddress, AudioData(data))

        # Start recording
        self.is_recording = True
        self.recording_thread = threading.Thread(target=process_data, daemon=True)
        self.recording_thread.start()

        self._logger.debug('Recording from microphone (arecord)')

    def in_recording(self, message, sender):
        if isinstance(message, AudioData):
            # Forward to subscribers
            for receiver in self.receivers:
                self.send(receiver, message)

            # Append to buffers
            for receiver in self.buffers:
                self.buffers[receiver] += message.data
        elif isinstance(message, StartStreaming):
            self.receivers.append(message.receiver)
        elif isinstance(message, StartRecordingToBuffer):
            self.buffers[message.buffer_name] = bytes()
        elif isinstance(message, StopStreaming):
            if message.receiver is None:
                # Clear all receivers
                self.receivers.clear()
            else:
                self.receivers.remove(message.receiver)
        elif isinstance(message, StopRecordingToBuffer):
            if message.buffer_name is None:
                # Clear all buffers
                self.buffers.clear()
            else:
                # Respond with buffer
                buffer = self.buffers.pop(message.buffer_name, bytes())
                self.send(message.receiver or sender, AudioData(buffer))

        # Check to see if anyone is still listening
        if (len(self.receivers) == 0) and (len(self.buffers) == 0):
            # Terminate audio recording
            self.is_recording = False
            self.record_proc.terminate()
            self.record_proc = None
            self.transition('started')
            self._logger.debug('Stopped recording from microphone (arecord)')

    def to_stopped(self, from_state):
        if self.is_recording:
            self.is_recording = False
            if self.record_proc is not None:
                self.record_proc.terminate()
            self._logger.debug('Stopped recording from microphone (arecord)')

    # -------------------------------------------------------------------------

    @classmethod
    def get_microphones(cls) -> Dict[Any, Any]:
        output = subprocess.check_output(['arecord', '-L'])\
                           .decode().splitlines()

        mics: Dict[Any, Any] = {}
        name, description = None, None

        # Parse output of arecord -L
        first_mic = True
        for line in output:
            line = line.rstrip()
            if re.match(r'^\s', line):
                description = line.strip()
                if first_mic:
                    description = description + '*'
                    first_mic = False
            else:
                if name is not None:
                    mics[name] = description

                name = line.strip()

        return mics

    # -------------------------------------------------------------------------

    @classmethod
    def test_microphones(cls, chunk_size:int) -> Dict[Any, Any]:
        # Thanks to the speech_recognition library!
        # https://github.com/Uberi/speech_recognition/blob/master/speech_recognition/__init__.py
        mics = ARecordAudioRecorder.get_microphones()
        result = {}
        for device_id, device_name in mics.items():
            try:
                # read audio
                arecord_cmd = ['arecord',
                              '-q',
                              '-D', device_id,
                              '-r', '16000',
                              '-f', 'S16_LE',
                              '-c', '1',
                              '-t', 'raw']

                proc = subprocess.Popen(arecord_cmd, stdout=subprocess.PIPE)
                buffer = proc.stdout.read(chunk_size * 2)
                proc.terminate()
            except:
                result[device_id] = '%s (error)' % device_name
                continue

            # compute RMS of debiased audio
            energy = -audioop.rms(buffer, 2)
            energy_bytes = bytes([energy & 0xFF, (energy >> 8) & 0xFF])
            debiased_energy = audioop.rms(
                audioop.add(buffer, energy_bytes * (len(buffer) // 2), 2), 2)

            if debiased_energy > 30:  # probably actually audio
                result[device_id] = '%s (working!)' % device_name
            else:
                result[device_id] = '%s (no sound)' % device_name

        return result

# -----------------------------------------------------------------------------
# WAV based audio "recorder"
# -----------------------------------------------------------------------------

class WavAudioRecorder(RhasspyActor):
    '''Pushes WAV data out instead of data from a microphone.'''
    def __init__(self):
        RhasspyActor.__init__(self)
        self.receivers = []
        self.buffers = {}
        self.wav_path = wav_path
        self.chunk_size = chunk_size
        self.is_recording = False

    def to_started(self, from_state):
        self.wav_path = self.profile.get('microphone.wav.path')
        self.chunk_size = self.config.get('microphone.wav.chunk_size', 480*2)

    def in_started(self, message, sender):
        if isinstance(message, StartStreaming):
            self.receivers.append(message.receiver)
            self.transition('recording')
        elif isinstance(message, StartRecordingToBuffer):
            self.buffers[message.buffer_name] = bytes()
            self.transition('recording')

    def to_recording(self, from_state):
        def process_data():
            with wave.open(self.wav_path, 'rb') as wav_file:
                rate, width, channels = wav_file.getframerate(), wav_file.getsampwidth(), wav_file.getnchannels()
                if (rate != 16000) or (width != 2) or (channels != 1):
                    audio_data = convert_wav(wav_file.read())
                else:
                    # Use original data
                    audio_data = wav_file.readframes(wav_file.getnframes())

            i = 0
            while (self.is_recording) and ((i+self.chunk_size) < len(audio_data)):
                data = audio_data[i:i+self.chunk_size]
                i += self.chunk_size

                # Send to this actor to avoid threading issues
                self.send(self.myAddress, AudioData(data))

        self.is_recording = True
        threading.Thread(target=process_data, daemon=True).start()
        self.transition('recording')

    def in_recording(self, message, sender):
        if isinstance(message, AudioData):
            # Forward to subscribers
            for receiver in self.receivers:
                self.send(receiver, message)

            # Append to buffers
            for receiver in self.buffers:
                self.buffers[receiver] += message.data
        elif isinstance(message, StartStreaming):
            self.receivers.append(message.receiver)
        elif isinstance(message, StartRecordingToBuffer):
            self.buffers[message.buffer_name] = bytes()
        elif isinstance(message, StopStreaming):
            if message.receiver is None:
                # Clear all receivers
                self.receivers.clear()
            else:
                self.receivers.remove(message.receiver)
        elif isinstance(message, StopRecordingToBuffer):
            if message.buffer_name is None:
                # Clear all buffers
                self.buffers.clear()
            else:
                # Respond with buffer
                buffer = self.buffers.pop(message.buffer_name, bytes())
                self.send(message.receiver or sender, AudioData(buffer))

        # Check to see if anyone is still listening
        if (len(self.receivers) == 0) and (len(self.buffers) == 0):
            # Terminate audio recording
            self.is_recording = False
            self.transition('started')

    def to_stopped(self, from_state):
        self.is_recording = False

    # -----------------------------------------------------------------------------

    @classmethod
    def get_microphones(self, chunk_size:int) -> Dict[Any, Any]:
        return {}

    @classmethod
    def test_microphones(self, chunk_size:int) -> Dict[Any, Any]:
        return {}

# -----------------------------------------------------------------------------
# MQTT based audio "recorder" for Snips.AI Hermes Protocol
# https://docs.snips.ai/ressources/hermes-protocol
# -----------------------------------------------------------------------------

class HermesAudioRecorder(RhasspyActor):
    '''Receives audio data from MQTT via Hermes protocol.'''
    def __init__(self):
        RhasspyActor.__init__(self)
        self.receivers = []
        self.buffers = {}

    def to_started(self, from_state):
        self.mqtt = self.config['mqtt']
        self.site_id = self.profile.get('mqtt.site_id')
        self.chunk_size = self.config.get('microphone.hermes.chunk_size', 480*2)
        self.topic_audio_frame = 'hermes/audioServer/%s/audioFrame' % self.site_id
        self.send(self.mqtt, MqttSubscribe(self.topic_audio_frame))

    def in_started(self, message, sender):
        if isinstance(message, StartStreaming):
            self.receivers.append(message.receiver)
            self.transition('recording')
        elif isinstance(message, StartRecordingToBuffer):
            self.buffers[message.buffer_name] = bytes()
            self.transition('recording')

    def to_recording(self, from_state):
        self._logger.debug('Recording from microphone (hermes)')

    def in_recording(self, message, sender):
        if isinstance(message, MqttMessage):
            if message.topic == self.topic_audio_frame:
                # Extract audio data
                with io.BytesIO(message.payload) as wav_buffer:
                    with wave.open(wav_buffer, mode='rb') as wav_file:
                        rate, width, channels = wav_file.getframerate(), wav_file.getsampwidth(), wav_file.getnchannels()
                        if (rate != 16000) or (width != 2) or (channels != 1):
                            audio_data = convert_wav(message.payload)
                        else:
                            # Use original data
                            audio_data = wav_file.readframes(wav_file.getnframes())

                        data_message = AudioData(audio_data)

                # Forward to subscribers
                for receiver in self.receivers:
                    self.send(receiver, data_message)

                # Append to buffers
                for receiver in self.buffers:
                    self.buffers[receiver] += audio_data.data
        elif isinstance(message, StartStreaming):
            self.receivers.append(message.receiver)
        elif isinstance(message, StartRecordingToBuffer):
            self.buffers[message.buffer_name] = bytes()
        elif isinstance(message, StopStreaming):
            if message.receiver is None:
                # Clear all receivers
                self.receivers.clear()
            else:
                self.receivers.remove(message.receiver)
        elif isinstance(message, StopRecordingToBuffer):
            if message.buffer_name is None:
                # Clear all buffers
                self.buffers.clear()
            else:
                # Respond with buffer
                buffer = self.buffers.pop(message.buffer_name, bytes())
                self.send(message.receiver or sender, AudioData(buffer))

    # -----------------------------------------------------------------------------

    @classmethod
    def get_microphones(self, chunk_size:int) -> Dict[Any, Any]:
        return {}

    @classmethod
    def test_microphones(self, chunk_size:int) -> Dict[Any, Any]:
        return {}
