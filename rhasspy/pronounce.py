#!/usr/bin/env python3
import os
import re
import logging
import subprocess
import tempfile
from typing import Dict, Tuple, List, Optional, Any

from thespian.actors import ActorAddress

from .actor import RhasspyActor
from .utils import read_dict, load_phoneme_map
from .profiles import Profile

# -----------------------------------------------------------------------------
# Events
# -----------------------------------------------------------------------------

class SpeakWord:
    def __init__(self, word: str, receiver: Optional[ActorAddress]=None) -> None:
        self.word = word
        self.receiver = receiver

class WordSpoken:
    def __init__(self, word: str, wav_data: bytes, phonemes: str) -> None:
        self.word = word
        self.wav_data = wav_data
        self.phonemes = phonemes

class GetWordPhonemes:
    def __init__(self, word: str, receiver: Optional[ActorAddress]=None) -> None:
        self.word = word
        self.receiver = receiver

class WordPhonemes:
    def __init__(self, word: str, phonemes: str) -> None:
        self.word = word
        self.phonemes = phonemes

class GetWordPronunciations:
    def __init__(self, word: str, n: int=5, receiver: Optional[ActorAddress]=None) -> None:
        self.word = word
        self.n = n
        self.receiver = receiver

class WordPronunciation:
    def __init__(self, word: str,
                 pronunciations: List[str],
                 in_dictionary: bool,
                 phonemes: str) -> None:
        self.word = word
        self.pronunciations = pronunciations
        self.in_dictionary = in_dictionary
        self.phonemes = phonemes

# -----------------------------------------------------------------------------
# Dummy word pronouncer
# -----------------------------------------------------------------------------

class DummyWordPronounce:
    '''Returns junk.'''

# -----------------------------------------------------------------------------
# Phonetisaurus based word pronouncer
# https://github.com/AdolfVonKleist/Phonetisaurus
# -----------------------------------------------------------------------------

class PhonetisaurusPronounce(RhasspyActor):
    '''Uses phonetisaurus/espeak to pronounce words.'''
    def __init__(self) -> None:
        RhasspyActor.__init__(self)
        self.speed = 80  # wpm for speaking

    def in_started(self, message: Any, sender: ActorAddress) -> None:
        if isinstance(message, SpeakWord):
            espeak_phonemes, wav_data = self.speak(message.word)
            self.send(message.receiver or sender,
                      WordSpoken(message.word, wav_data, espeak_phonemes))
        elif isinstance(message, GetWordPronunciations):
            in_dictionary, pronunciations, espeak_str = \
                self.pronounce(message.word, message.n)

            self.send(message.receiver or sender,
                      WordPronunciation(message.word,
                                        pronunciations,
                                        in_dictionary,
                                        espeak_str))
        elif isinstance(message, GetWordPhonemes):
            phonemes = self.translate_phonemes(message.word)
            self.send(message.receiver or sender,
                      WordPhonemes(message.word, phonemes))

    # -------------------------------------------------------------------------

    def speak(self,
              espeak_str: str,
              voice: Optional[str] = None) -> Tuple[str, bytes]:

        # Use eSpeak to pronounce word
        espeak_command = ['espeak',
                          '-s', str(self.speed),
                          '-x']

        voice = self._get_voice(voice)

        if voice is not None:
            espeak_command.extend(['-v', str(voice)])

        espeak_command.append(espeak_str)

        # Write WAV to temporary file
        with tempfile.NamedTemporaryFile(suffix='.wav', mode='wb+') as wav_file:
            espeak_command.extend(['-w', wav_file.name])
            self._logger.debug(espeak_command)

            # Generate WAV data
            espeak_phonemes = subprocess.check_output(espeak_command).decode().strip()
            wav_file.seek(0)
            wav_data = wav_file.read()

        return espeak_phonemes, wav_data

    # -------------------------------------------------------------------------

    def translate_phonemes(self, phonemes: str) -> str:
        # Load map from Sphinx to eSpeak phonemes
        map_path = self.profile.read_path(
            self.profile.get('text_to_speech.espeak.phoneme_map'))

        phoneme_map = load_phoneme_map(map_path)

        # Convert from Sphinx to espeak phonemes
        espeak_str = "[['%s]]" % ''.join(phoneme_map.get(p, p)
                                         for p in phonemes.split())

        return espeak_str

    # -------------------------------------------------------------------------

    def pronounce(self, word: str, n: int = 5) -> Tuple[bool, List[str], str]:
        assert n > 0, 'No pronunciations requested'
        assert len(word) > 0, 'No word to look up'

        self._logger.debug('Getting pronunciations for %s' % word)

        # Load base and custom dictionaries
        base_dictionary_path = self.profile.read_path(
            self.profile.get('speech_to_text.pocketsphinx.base_dictionary'))

        custom_path = self.profile.read_path(
            self.profile.get('speech_to_text.pocketsphinx.custom_words'))

        word_dict: Dict[str, List[str]] = {}
        for word_dict_path in [base_dictionary_path, custom_path]:
            if os.path.exists(word_dict_path):
                with open(word_dict_path, 'r') as dictionary_file:
                    read_dict(dictionary_file, word_dict)

        in_dictionary, pronunciations = self._lookup_word(word, word_dict, n)

        # Get phonemes from eSpeak
        espeak_command = ['espeak', '-q', '-x']

        voice = self._get_voice()
        if voice is not None:
            espeak_command.extend(['-v', voice])

        espeak_command.append(word)

        self._logger.debug(espeak_command)
        espeak_str = subprocess.check_output(espeak_command).decode().strip()

        return in_dictionary, pronunciations, espeak_str

    # -------------------------------------------------------------------------

    def _lookup_word(self,
                     word: str,
                     word_dict: Dict[str, List[str]],
                     n:int=5) -> Tuple[bool, List[str]]:
        '''Look up or guess word pronunciations.'''

        # Dictionary uses upper-case letters
        dictionary_upper = self.profile.get(
            'speech_to_text.dictionary_upper', False)

        if dictionary_upper:
            word = word.upper()
        else:
            word = word.lower()

        pronounces = list(word_dict.get(word, []))
        in_dictionary = (len(pronounces) > 0)
        if not in_dictionary:
            # Guess pronunciation
            # Path to phonetisaurus FST
            g2p_path = self.profile.read_path(
                self.profile.get('speech_to_text.g2p_model'))

            g2p_upper = self.profile.get(
                'speech_to_text.g2p_upper', False)

            if g2p_upper:
                # FST was trained with upper-case letters
                word = word.upper()
            else:
                # FST was trained with loser-case letters
                word = word.lower()

            # Output phonetisaurus results to temporary file
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.txt') as pronounce_file:
                # Use phonetisaurus to guess pronunciations
                g2p_command = ['phonetisaurus-g2p',
                                '--model=' + g2p_path,
                                '--input=' + word,  # case sensitive
                                '--nbest=' + str(n),
                                '--words']

                self._logger.debug(g2p_command)
                subprocess.check_call(g2p_command, stdout=pronounce_file)

                pronounce_file.seek(0)

                # Read results
                ws_pattern = re.compile(r'\s+')

                for line in pronounce_file:
                    parts = ws_pattern.split(line)
                    phonemes = ' '.join(parts[2:]).strip()
                    pronounces.append(phonemes)

        return in_dictionary, pronounces

    # -------------------------------------------------------------------------

    def _get_voice(self, voice: Optional[str] = None) -> Optional[str]:
        '''Uses either the provided voice, the profile's text to speech voice,
        or the profile's language.'''
        return voice \
            or self.profile.get('text_to_speech.espeak.voice') \
            or self.profile.get('language')
