#!/usr/bin/env python3
import os
import threading
import logging
from uuid import uuid4

from .actor import RhasspyActor
from .profiles import Profile
from .audio_recorder import StartStreaming, StopStreaming, AudioData

# -----------------------------------------------------------------------------

class ListenForWakeWord:
    def __init__(self, receiver=None):
        self.receiver = receiver

class StopListeningForWakeWord:
    def __init__(self, receiver=None):
        self.receiver = receiver

class WakeWordDetected:
    def __init__(self, name: str):
        self.name = name

# -----------------------------------------------------------------------------
# Pocketsphinx based wake word listener
# https://github.com/cmusphinx/pocketsphinx
# -----------------------------------------------------------------------------

class PocketsphinxWakeListener(RhasspyActor):
    '''Listens for a wake word with pocketsphinx.'''
    def __init__(self):
        RhasspyActor.__init__(self)
        self.receivers = []
        self.decoder = None
        self.decoder_started = False

    def to_started(self, from_state):
        self.recorder = self.config['recorder']
        self.preload = self.config.get('preload', False)
        if self.preload:
            self.load_decoder()

        self.transition('loaded')

    def in_loaded(self, message, sender):
        if isinstance(message, ListenForWakeWord):
            self.load_decoder()
            self.receivers.append(message.receiver or sender)
            self.transition('listening')

            if not self.decoder_started:
                self.decoder.start_utt()
                self.decoder_started = True

            self.send(self.recorder, StartStreaming(self.myAddress))

    def in_listening(self, message, sender):
        if isinstance(message, AudioData):
            result = self.process_data(message.data)
            if result is not None:
                self._logger.debug('Hotword detected (%s)' % self.keyphrase)
                result = WakeWordDetected(self.keyphrase)
                for receiver in self.receivers:
                    self.send(receiver, result)
        elif isinstance(message, StopListeningForWakeWord):
            self.receivers.remove(message.receiver or sender)
            if len(self.receivers) == 0:
                if self.decoder_started:
                    self.decoder.end_utt()
                    self.decoder_started = False

                self.send(self.recorder, StopStreaming(self.myAddress))
                self.transition('loaded')

    # -------------------------------------------------------------------------

    def process_data(self, data):
        self.decoder.process_raw(data, False, False)
        hyp = self.decoder.hyp()
        if hyp:
            self.decoder.end_utt()
            self.decoder_started = False
            return hyp.hypstr()

        return None

    # -------------------------------------------------------------------------

    def load_decoder(self):
        '''Loads speech decoder if not cached.'''
        if self.decoder is None:
            import pocketsphinx

            # Load decoder settings (use speech-to-text configuration as a fallback)
            hmm_path = self.profile.read_path(
                self.profile.get('wake.pocketsphinx.acoustic_model', None) \
                or self.profile.get('speech_to_text.pocketsphinx.acoustic_model'))

            dict_path = self.profile.read_path(
                self.profile.get('wake.pocketsphinx.dictionary', None) \
                or self.profile.get('speech_to_text.pocketsphinx.dictionary'))

            self.threshold = float(self.profile.get('wake.pocketsphinx.threshold', 1e-40))
            self.keyphrase = self.profile.get('wake.pocketsphinx.keyphrase', '')
            assert len(self.keyphrase) > 0, 'No wake keyphrase'

            self._logger.debug('Loading wake decoder with hmm=%s, dict=%s' % (hmm_path, dict_path))

            decoder_config = pocketsphinx.Decoder.default_config()
            decoder_config.set_string('-hmm', hmm_path)
            decoder_config.set_string('-dict', dict_path)
            decoder_config.set_string('-keyphrase', self.keyphrase)
            decoder_config.set_string('-logfn', '/dev/null')
            decoder_config.set_float('-kws_threshold', self.threshold)

            mllr_path = self.profile.read_path(
                self.profile.get('wake.pocketsphinx.mllr_matrix'))

            if os.path.exists(mllr_path):
                self._logger.debug('Using tuned MLLR matrix for acoustic model: %s' % mllr_path)
                decoder_config.set_string('-mllr', mllr_path)

            self.decoder = pocketsphinx.Decoder(decoder_config)

# -----------------------------------------------------------------------------
# Snowboy wake listener
# https://snowboy.kitt.ai
# -----------------------------------------------------------------------------

class SnowboyWakeListener(RhasspyActor):
    def __init__(self):
        RhasspyActor.__init__(self)
        self.receivers = []
        self.detector = None

    def to_started(self, from_state):
        self.recorder = self.config['recorder']
        self.preload = self.config.get('preload', False)
        if self.preload:
            self.load_detector()

        self.transition('loaded')

    def in_loaded(self, message, sender):
        if isinstance(message, ListenForWakeWord):
            self.load_detector()
            self.receivers.append(message.receiver or sender)
            self.transition('listening')
            self.send(self.recorder, StartStreaming(self.myAddress))

    def in_listening(self, message, sender):
        if isinstance(message, AudioData):
            index = self.process_data(message.data)
            if index > 0:
                self._logger.debug('Hotword detected (%s)' % self.model_name)
                result = WakeWordDetected(self.model_name)
                for receiver in self.receivers:
                    self.send(receiver, result)
        elif isinstance(message, StopListeningForWakeWord):
            self.receivers.remove(message.receiver or sender)
            if len(self.receivers) == 0:
                self.send(self.recorder, StopStreaming(self.myAddress))
                self.transition('loaded')

    # -------------------------------------------------------------------------

    def process_data(self, data: bytes):
        try:
            # Return is:
            # -2 silence
            # -1 error
            #  0 voice
            #  n index n-1
            return self.detector.RunDetection(data)
        except Exception as e:
            self._logger.exception('process_data')

        return -2

    # -------------------------------------------------------------------------

    def load_detector(self):
        if self.detector is None:
            from snowboy import snowboydetect, snowboydecoder

            self.model_name = self.profile.get('wake.snowboy.model')
            model_path = self.profile.read_path(self.model_name)

            sensitivity = float(self.profile.get('wake.snowboy.sensitivity', 0.5))
            audio_gain = float(self.profile.get('wake.snowboy.audio_gain', 1.0))

            self.detector = snowboydetect.SnowboyDetect(
                snowboydecoder.RESOURCE_FILE.encode(), model_path.encode())

            sensitivity_str = str(sensitivity).encode()
            self.detector.SetSensitivity(sensitivity_str)
            self.detector.SetAudioGain(audio_gain)

            self._logger.debug('Loaded snowboy (model=%s, sensitivity=%s, audio_gain=%s)' \
                              % (model_path, sensitivity, audio_gain))

# -----------------------------------------------------------------------------
# Mycroft Precise wake listener
# https://github.com/MycroftAI/mycroft-precise
# -----------------------------------------------------------------------------

class PreciseWakeListener(RhasspyActor):
    '''Listens for a wake word using Mycroft Precise.'''
    def __init__(self):
        RhasspyActor.__init__(self)
        self.receivers = []
        self.stream:ByteStream = None
        self.engine = None
        self.runner = None

    def to_started(self, from_state):
        self.recorder = self.config['recorder']
        self.preload = self.config.get('preload', False)
        if self.preload:
            self.load_runner()

        self.transition('loaded')

    def in_loaded(self, message, sender):
        if isinstance(message, ListenForWakeWord):
            self.load_runner()
            self.receivers.append(message.receiver or sender)
            self.transition('listening')
            self.send(self.recorder, StartStreaming(self.myAddress))

    def in_listening(self, message, sender):
        if isinstance(message, AudioData):
            self.process_data(message.data)
            if self.detected:
                self._logger.debug('Hotword detected (%s)' % self.model_name)
                result = WakeWordDetected(self.model_name)
                for receiver in self.receivers:
                    self.send(receiver, result)
                self.detected = False # reset
        elif isinstance(message, StopListeningForWakeWord):
            self.receivers.remove(message.receiver or sender)
            if len(self.receivers) == 0:
                self.send(self.recorder, StopStreaming(self.myAddress))
                self.transition('loaded')

    def to_stopped(self, from_state):
        if self.stream is not None:
            self.stream.close()

        if self.runner is not None:
            self.runner.stop()

    # -------------------------------------------------------------------------

    def process_data(data: bytes) -> None:
        self.stream.write(data)

    # -------------------------------------------------------------------------

    def load_runner(self):
        if self.engine is None:
            from precise_runner import PreciseEngine
            self.model_name = self.profile.get('wake.precise.model')
            self.model_path = self.profile.read_path(self.model_name)
            self.engine = PreciseEngine('precise-engine', self.model_path)

        if self.runner is None:
            from precise_runner import PreciseRunner
            from utils import ByteStream

            self.stream = ByteStream()

            sensitivity = float(self.profile.get('wake.precise.sensitivity', 0.5))
            trigger_level = int(self.profile.get('wake.precise.trigger_level', 3))

            def on_activation():
                self.detected = True

            self.runner = PreciseRunner(self.engine, stream=self.stream,
                                        sensitivity=sensitivity,
                                        trigger_level=trigger_level,
                                        on_activation=on_activation)

            self.runner.start()

            logger.debug('Loaded Mycroft Precise (model=%s, sensitivity=%s, trigger_level=%s)' \
                         % (self.model_path, sensitivity, trigger_level))
