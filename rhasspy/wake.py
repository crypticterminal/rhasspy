#!/usr/bin/env python3
import os
import threading
import logging
from typing import Callable

from profiles import Profile
from audio_recorder import AudioRecorder

# -----------------------------------------------------------------------------

logger = logging.getLogger(__name__)

class WakeListener:
    '''Base class for all wake/hot word listeners.'''

    def __init__(self, audio_recorder: AudioRecorder, profile: Profile) -> None:
        self.audio_recorder = audio_recorder
        self.profile = profile
        self._is_listening = False

    def preload(self):
        '''Cache important stuff up front.'''
        pass

    @property
    def is_listening(self) -> bool:
        '''True if wake system is currently recording.'''
        return self._is_listening

    def start_listening(self, **kwargs):
        '''Start wake system listening in the background and return immedately.'''
        pass

# -----------------------------------------------------------------------------
# Pocketsphinx based wake word listener
# https://github.com/cmusphinx/pocketsphinx
# -----------------------------------------------------------------------------

class PocketsphinxWakeListener(WakeListener):
    def __init__(self, audio_recorder: AudioRecorder, profile: Profile,
                 detected_callback: Callable[[str, str], None]) -> None:
        '''Listens for a keyphrase using pocketsphinx.
        Calls detected_callback when keyphrase is detected and stops.'''

        WakeListener.__init__(self, audio_recorder, profile)
        self.callback = detected_callback
        self.decoder = None
        self.keyphrase = ''

    def preload(self):
        self._maybe_load_decoder()

    # -------------------------------------------------------------------------

    def start_listening(self, **kwargs):
        if self.is_listening:
            logger.warn('Already listening')
            return

        self._maybe_load_decoder()

        def process_data():
            self.decoder.start_utt()

            try:
                while True:
                    # Block until audio data comes in
                    data = self.audio_recorder.get_queue().get()
                    if len(data) == 0:
                        self.decoder.end_utt()
                        logger.debug('Listening cancelled')
                        break

                    self.decoder.process_raw(data, False, False)
                    hyp = self.decoder.hyp()
                    if hyp:
                        self.decoder.end_utt()
                        logger.debug('Keyphrase detected (%s)!' % self.keyphrase)
                        self.callback(self.profile.name, self.keyphrase, **kwargs)
                        break
            except Exception as e:
                logger.exception('process_data')

            self._is_listening = False

        # Start audio recording
        self.audio_recorder.start_recording(False, True)

        # Decoder runs in a separate thread
        thread = threading.Thread(target=process_data, daemon=True)
        thread.start()
        self._is_listening = True

        logging.debug('Listening for wake word with pocketsphinx (keyphrase=%s)' % self.keyphrase)

    # -------------------------------------------------------------------------

    def _maybe_load_decoder(self):
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

            kws_threshold = self.profile.get('wake.pocketsphinx.threshold', 1e-40)
            self.keyphrase = self.profile.get('wake.pocketsphinx.keyphrase', '')
            assert len(self.keyphrase) > 0, 'No wake keyphrase'

            logger.debug('Loading wake decoder with hmm=%s, dict=%s' % (hmm_path, dict_path))

            decoder_config = pocketsphinx.Decoder.default_config()
            decoder_config.set_string('-hmm', hmm_path)
            decoder_config.set_string('-dict', dict_path)
            decoder_config.set_string('-keyphrase', self.keyphrase)
            decoder_config.set_float('-kws_threshold', kws_threshold)

            self.decoder = pocketsphinx.Decoder(decoder_config)

