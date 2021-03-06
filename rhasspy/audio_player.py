#!/usr/bin/env python3
import os
import logging
import subprocess
import tempfile
import uuid
from typing import Any

from thespian.actors import ActorAddress

from .actor import RhasspyActor
from .mqtt import MqttPublish

# -----------------------------------------------------------------------------
# Events
# -----------------------------------------------------------------------------

class PlayWavFile:
    def __init__(self, wav_path: str) -> None:
        self.wav_path = wav_path

class PlayWavData:
    def __init__(self, wav_data: bytes) -> None:
        self.wav_data = wav_data

# -----------------------------------------------------------------------------
# Dummy audio player
# -----------------------------------------------------------------------------

class DummyAudioPlayer(RhasspyActor):
    '''Does nothing'''
    def in_started(self, message: Any, sender: ActorAddress) -> None:
        pass

# -----------------------------------------------------------------------------
# APlay based audio player
# -----------------------------------------------------------------------------

class APlayAudioPlayer(RhasspyActor):
    '''Plays WAV files using aplay'''
    def to_started(self, from_state:str) -> None:
        self.device = self.config.get('device') \
            or self.profile.get('sounds.aplay.device')

    def in_started(self, message: Any, sender: ActorAddress) -> None:
        if isinstance(message, PlayWavFile):
            self.play_file(message.wav_path)
        elif isinstance(message, PlayWavData):
            self.play_data(message.wav_data)

    # -------------------------------------------------------------------------

    def play_file(self, path: str) -> None:
        if not os.path.exists(path):
            self._logger.warn('Path does not exist: %s', path)
            return

        aplay_cmd = ['aplay', '-q']

        if self.device is not None:
            aplay_cmd.extend(['-D', str(self.device)])

        # Play file
        aplay_cmd.append(path)

        self._logger.debug(aplay_cmd)
        subprocess.run(aplay_cmd)

    def play_data(self, wav_data: bytes) -> None:
        aplay_cmd = ['aplay', '-q']

        if self.device is not None:
            aplay_cmd.extend(['-D', str(self.device)])

        self._logger.debug(aplay_cmd)

        # Play data
        subprocess.run(aplay_cmd, input=wav_data)

# -----------------------------------------------------------------------------
# MQTT audio player for Snips.AI Hermes Protocol
# https://docs.snips.ai/ressources/hermes-protocol
# -----------------------------------------------------------------------------

class HermesAudioPlayer(RhasspyActor):
    '''Sends audio data over MQTT via Hermes protocol'''
    def to_started(self, from_state:str) -> None:
        self.site_id = self.profile.get('mqtt.site_id')
        self.mqtt = self.config['mqtt']

    def in_started(self, message: Any, sender: ActorAddress) -> None:
        if isinstance(message, PlayWavFile):
            self.play_file(message.wav_path)
        elif isinstance(message, PlayWavData):
            self.play_data(message.wav_data)

    # -------------------------------------------------------------------------

    def play_file(self, path: str) -> None:
        if not os.path.exists(path):
            self._logger.warn('Path does not exist: %s', path)
            return

        with open(path, 'rb') as wav_file:
            self.play_data(wav_file.read())

    def play_data(self, wav_data: bytes) -> None:
        request_id = str(uuid.uuid4())
        topic = 'hermes/audioServer/%s/playBytes/%s' % (self.site_id, request_id)
        self.send(self.mqtt, MqttPublish(topic, wav_data))
