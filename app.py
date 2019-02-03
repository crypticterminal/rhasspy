#!/usr/bin/env python3
import logging
logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)

import os
import sys
import subprocess
import json
import re
import gzip
import time
import io
import wave
import tempfile
import threading
import functools
import argparse
import shlex
import time
import atexit
from uuid import uuid4
from collections import defaultdict

from flask import Flask, request, Response, jsonify, send_file, send_from_directory
from flask_cors import CORS
import requests
import pydash
from thespian.actors import ActorSystem

from rhasspy.profiles import Profile
from rhasspy.core import RhasspyCore
from rhasspy.dialogue import ProfileTrainingFailed
from rhasspy.utils import recursive_update, buffer_to_wav, load_phoneme_examples

# -----------------------------------------------------------------------------
# Flask Web App Setup
# -----------------------------------------------------------------------------

app = Flask('rhasspy')
app.secret_key = str(uuid4())
CORS(app)

# -----------------------------------------------------------------------------
# Parse Arguments
# -----------------------------------------------------------------------------

parser = argparse.ArgumentParser('Rhasspy')
parser.add_argument('--profile', '-p', type=str,
                    help='Name of profile to load',
                    default=None)

parser.add_argument('--set', '-s', nargs=2,
                    action='append',
                    help='Set a profile setting value',
                    default=[])

arg_str = os.environ.get('RHASSPY_ARGS', '')
args = parser.parse_args(shlex.split(arg_str))
logger.debug(args)

# -----------------------------------------------------------------------------
# Dialogue Manager Setup
# -----------------------------------------------------------------------------

core = None

# We really, *really* want shutdown to be called
@atexit.register
def shutdown(*args, **kwargs):
    global core
    if core is not None:
        core.shutdown()
        core = None

# Like PATH, searched in reverse order
profiles_dirs = [path for path in
                os.environ.get('RHASSPY_PROFILES', 'profiles')\
                .split(':') if len(path.strip()) > 0]

profiles_dirs.reverse()

def start_rhasspy():
    global core

    default_settings = Profile.load_defaults(profiles_dirs)

    # Get name of profile
    profile_name = args.profile \
        or os.environ.get('RHASSPY_PROFILE', None) \
        or pydash.get(default_settings, 'rhasspy.default_profile', 'en')

    # Load core
    core = RhasspyCore(profile_name, profiles_dirs)
    core.start()

    # Add profile settings from the command line
    extra_settings = {}
    for key, value in args.set:
        try:
            value = json.loads(value)
        except:
            pass

        logger.debug('Profile: {0}={1}'.format(key, value))
        extra_settings[key] = value
        core.profile.set(key, value)

# -----------------------------------------------------------------------------

start_rhasspy()

# -----------------------------------------------------------------------------
# HTTP API
# -----------------------------------------------------------------------------

@app.route('/api/profiles')
def api_profiles():
    '''Get list of available profiles'''
    profile_names = set()
    for profiles_dir in profiles_dirs:
        if not os.path.exists(profiles_dir):
            continue

        for name in os.listdir(profiles_dir):
            profile_dir = os.path.join(profiles_dir, name)
            if os.path.isdir(profile_dir):
                profile_names.add(name)

    return jsonify({
        'default_profile': core.profile.name,
        'profiles': sorted(list(profile_names))
    })

# -----------------------------------------------------------------------------

@app.route('/api/microphones', methods=['GET'])
def api_microphones():
    '''Get a dictionary of available recording devices'''
    system = request.args.get('system', None)
    return jsonify(core.get_microphones(system))

# -----------------------------------------------------------------------------

@app.route('/api/test-microphones', methods=['GET'])
def api_test_microphones():
    '''Get a dictionary of available, functioning recording devices'''
    system = request.args.get('system', None)
    return jsonify(core.test_microphones(system))

# -----------------------------------------------------------------------------

@app.route('/api/listen-for-wake', methods=['POST'])
def api_listen_for_wake():
    # no_hass = request.args.get('nohass', 'false').lower() == 'true'
    core.listen_for_wake()
    return 'OK'

# -----------------------------------------------------------------------------

@app.route('/api/listen-for-command', methods=['POST'])
def api_listen_for_command():
    no_hass = request.args.get('nohass', 'false').lower() == 'true'
    return jsonify(core.listen_for_command(handle=not no_hass))

# -----------------------------------------------------------------------------

@app.route('/api/profile', methods=['GET', 'POST'])
def api_profile():
    '''Read or write profile JSON directly'''
    layers = request.args.get('layers', 'all')

    if request.method == 'POST':
        # Ensure that JSON is valid
        json.loads(request.data)

        if layers == 'defaults':
            # Write default settings
            for profiles_dir in profiles_dirs:
                profile_path = os.path.join(profiles_dir, 'defaults.json')
                try:
                    with open(profile_path, 'wb') as profile_file:
                        profile_file.write(request.data)
                    break
                except:
                    pass
        else:
            # Write local profile settings
            profile_path = core.profile.write_path('profile.json')
            with open(profile_path, 'wb') as profile_file:
                profile_file.write(request.data)

        msg = 'Wrote %d byte(s) to %s' % (len(request.data), profile_path)
        logger.debug(msg)
        return msg

    if layers == 'defaults':
        # Read default settings
        return jsonify(core.defaults)
    elif layers == 'profile':
        # Local settings only
        profile_path = core.profile.read_path('profile.json')
        return send_file(open(profile_path, 'rb'),
                         mimetype='application/json')
    else:
        return jsonify(core.profile.json)

# -----------------------------------------------------------------------------

@app.route('/api/lookup', methods=['POST'])
def api_lookup():
    '''Get CMU phonemes from dictionary or guessed pronunciation(s)'''
    n = int(request.args.get('n', 5))
    assert n > 0, 'No pronunciations requested'

    word = request.data.decode('utf-8').strip().lower()
    assert len(word) > 0, 'No word to look up'

    result = core.get_word_pronunciations(word, n)
    pronunciations = result.pronunciations
    in_dictionary = result.in_dictionary
    espeak_str = result.phonemes

    return jsonify({
        'in_dictionary': in_dictionary,
        'pronunciations': pronunciations,
        'espeak_phonemes': espeak_str
    })

# -----------------------------------------------------------------------------

@app.route('/api/pronounce', methods=['POST'])
def api_pronounce():
    '''Pronounce CMU phonemes or word using eSpeak'''
    download = request.args.get('download', 'false').lower() == 'true'

    pronounce_str = request.data.decode('utf-8').strip()
    assert len(pronounce_str) > 0, 'No string to pronounce'

    # phonemes or word
    pronounce_type = request.args.get('type', 'phonemes')

    if pronounce_type == 'phonemes':
        # Convert from Sphinx to espeak phonemes
        result = core.get_word_phonemes(pronounce_str)
        espeak_str = result.phonemes
    else:
        # Speak word directly
        espeak_str = pronounce_str

    result = core.speak_word(espeak_str)
    wav_data = result.wav_data
    espeak_phonemes = result.phonemes

    if download:
        # Return WAV
        return Response(wav_data, mimetype='audio/wav')
    else:
        # Play through speakers
        core.play_wav_data(wav_data)
        return espeak_phonemes

# -----------------------------------------------------------------------------

@app.route('/api/phonemes')
def api_phonemes():
    '''Get phonemes and example words for a profile'''
    examples_path = core.profile.read_path(
        core.profile.get('text_to_speech.phoneme_examples'))

    # phoneme -> { word, phonemes }
    logger.debug('Loading phoneme examples from %s' % examples_path)
    examples_dict = load_phoneme_examples(examples_path)

    return jsonify(examples_dict)

# -----------------------------------------------------------------------------

@app.route('/api/sentences', methods=['GET', 'POST'])
def api_sentences():
    '''Read or write sentences for a profile'''

    if request.method == 'POST':
        # Update sentences
        sentences_path = core.profile.write_path(
            core.profile.get('speech_to_text.sentences_ini'))

        with open(sentences_path, 'wb') as sentences_file:
            sentences_file.write(request.data)
            return 'Wrote %s byte(s) to %s' % (len(request.data), sentences_path)

    # Return sentences
    sentences_path = core.profile.read_path(
        core.profile.get('speech_to_text.sentences_ini'))

    if not os.path.exists(sentences_path):
        return ''  # no sentences yet

    # Return file contents
    return send_file(open(sentences_path, 'rb'), mimetype='text/plain')

# -----------------------------------------------------------------------------

@app.route('/api/custom-words', methods=['GET', 'POST'])
def api_custom_words():
    '''Read or write custom word dictionary for a profile'''
    if request.method == 'POST':
        custom_words_path = core.profile.write_path(
            core.profile.get('speech_to_text.pocketsphinx.custom_words'))

        # Update custom words
        lines_written = 0
        with open(custom_words_path, 'w') as custom_words_file:
            lines = request.data.decode().splitlines()
            for line in lines:
                line = line.strip()
                if len(line) == 0:
                    continue

                print(line, file=custom_words_file)
                lines_written += 1

            return 'Wrote %s line(s) to %s' % (lines_written, custom_words_path)

    custom_words_path = core.profile.read_path(
        core.profile.get('speech_to_text.pocketsphinx.custom_words'))

    # Return custom_words
    if not os.path.exists(custom_words_path):
        return ''  # no custom_words yet

    # Return file contents
    return send_file(open(custom_words_path, 'rb'), mimetype='text/plain')

# -----------------------------------------------------------------------------

@app.route('/api/train', methods=['POST'])
def api_train():
    start_time = time.time()
    logger.info('Starting training')

    result = core.train()
    if isinstance(result, ProfileTrainingFailed):
        raise Exception('Training failed due to unknown words')

    end_time = time.time()

    return 'Training completed in %0.2f second(s)' % (end_time - start_time)

# -----------------------------------------------------------------------------

@app.route('/api/restart', methods=['POST'])
def api_restart():
    logger.debug('Restarting Rhasspy')

    # Stop
    core.shutdown()

    # Start
    start_rhasspy()
    logger.info('Restarted Rhasspy')

    return 'Restarted Rhasspy'

# -----------------------------------------------------------------------------

# Get text from a WAV file
@app.route('/api/speech-to-text', methods=['POST'])
def api_speech_to_text():
    # Prefer 16-bit 16Khz mono, but will convert with sox if needed
    wav_data = request.data
    return core.transcribe_wav(wav_data).text

# -----------------------------------------------------------------------------

# Get intent from text
@app.route('/api/text-to-intent', methods=['POST'])
def api_text_to_intent():
    text = request.data.decode()
    no_hass = request.args.get('nohass', 'false').lower() == 'true'

    # Convert text to intent
    start_time = time.time()
    intent = core.recognize_intent(text).intent

    intent_sec = time.time() - start_time
    intent['time_sec'] = intent_sec

    if not no_hass:
        # Send intent to Home Assistant
        intent = core.handle_intent(intent).intent

    return jsonify(intent)

# -----------------------------------------------------------------------------

# Get intent from a WAV file
@app.route('/api/speech-to-intent', methods=['POST'])
def api_speech_to_intent():
    no_hass = request.args.get('nohass', 'false').lower() == 'true'

    # Prefer 16-bit 16Khz mono, but will convert with sox if needed
    wav_data = request.data

    # speech -> text
    start_time = time.time()
    text = core.transcribe_wav(wav_data).text
    logger.debug(text)

    # text -> intent
    intent = core.recognize_intent(text).intent

    intent_sec = time.time() - start_time
    intent['time_sec'] = intent_sec

    logger.debug(intent)

    if not no_hass:
        # Send intent to Home Assistant
        intent = core.handle_intent(intent).intent

    return jsonify(intent)

# -----------------------------------------------------------------------------

# Start recording a WAV file to a temporary buffer
@app.route('/api/start-recording', methods=['POST'])
def api_start_recording():
    buffer_name = request.args.get('name', '')
    core.start_recording_wav(buffer_name)

    return 'OK'

# Stop recording WAV file, transcribe, and get intent
@app.route('/api/stop-recording', methods=['POST'])
def api_stop_recording():
    no_hass = request.args.get('nohass', 'false').lower() == 'true'

    buffer_name = request.args.get('name', '')
    audio_data = core.stop_recording_wav(buffer_name).data

    wav_data = buffer_to_wav(audio_data)
    logger.debug('Recorded %s byte(s) of audio data' % len(wav_data))

    text = core.transcribe_wav(wav_data).text
    logger.debug(text)

    intent = core.recognize_intent(text).intent
    logger.debug(intent)

    if not no_hass:
        # Send intent to Home Assistant
        intent = core.handle_intent(intent).intent

    return jsonify(intent)

# -----------------------------------------------------------------------------

@app.route('/api/unknown_words', methods=['GET'])
def api_unknown_words():
    unknown_words = {}
    unknown_path = core.profile.read_path(
        core.profile.get('speech_to_text.pocketsphinx.unknown_words'))

    if os.path.exists(unknown_path):
        for line in open(unknown_path, 'r'):
            line = line.strip()
            if len(line) > 0:
                word, pronunciation = re.split(r'\s+', line, maxsplit=1)
                unknown_words[word] = pronunciation

    return jsonify(unknown_words)

# -----------------------------------------------------------------------------

@app.errorhandler(Exception)
def handle_error(err):
    logger.exception(err)
    return (str(err), 500)

# ---------------------------------------------------------------------
# Static Routes
# ---------------------------------------------------------------------

web_dir = os.path.join(os.path.dirname(__file__), 'dist')

@app.route('/css/<path:filename>', methods=['GET'])
def css(filename):
    return send_from_directory(os.path.join(web_dir, 'css'), filename)

@app.route('/js/<path:filename>', methods=['GET'])
def js(filename):
    return send_from_directory(os.path.join(web_dir, 'js'), filename)

@app.route('/img/<path:filename>', methods=['GET'])
def img(filename):
    return send_from_directory(os.path.join(web_dir, 'img'), filename)

@app.route('/webfonts/<path:filename>', methods=['GET'])
def webfonts(filename):
    return send_from_directory(os.path.join(web_dir, 'webfonts'), filename)

# ----------------------------------------------------------------------------
# HTML Page Routes
# ----------------------------------------------------------------------------

@app.route('/', methods=['GET'])
def index():
    return send_file(os.path.join(web_dir, 'index.html'))

@app.route('/swagger.yaml', methods=['GET'])
def swagger_yaml():
    return send_file(os.path.join(web_dir, 'swagger.yaml'))

# -----------------------------------------------------------------------------

# Swagger/OpenAPI documentation
from flask_swagger_ui import get_swaggerui_blueprint

SWAGGER_URL = '/api'
API_URL = '/swagger.yaml'

swaggerui_blueprint = get_swaggerui_blueprint(
    SWAGGER_URL, API_URL,
    config={'app_name': 'Rhasspy API'})

app.register_blueprint(swaggerui_blueprint, url_prefix=SWAGGER_URL)

# -----------------------------------------------------------------------------
