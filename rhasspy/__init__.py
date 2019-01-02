#!/usr/bin/env python3
import os
import sys
import json
import argparse

def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Rhasspy Voice Assistant')
    parser.add_argument('--profile', type=str, help='Name of profile to use', default=None)
    sub_parsers = parser.add_subparsers(dest='command')
    sub_parsers.required = True

    # info
    info_parser = sub_parsers.add_parser('info', help='Profile information')
    info_parser.add_argument('--defaults', action='store_true', help='Only print default settings')

    # wav2text
    wav2text_parser = sub_parsers.add_parser('wav2text', help='WAV file to text transcription')
    wav2text_parser.add_argument('wav_files', nargs='*', help='Paths to WAV files')

    # text2intent
    text2intent_parser = sub_parsers.add_parser('text2intent', help='Text parsed to intent')
    text2intent_parser.add_argument('sentences', nargs='*', help='Sentences to parse')

    # wav2intent
    wav2intent_parser = sub_parsers.add_parser('wav2intent', help='WAV file to parsed intent')
    wav2intent_parser.add_argument('wav_files', nargs='*', help='Paths to WAV files')

    # train
    train_parser = sub_parsers.add_parser('train', help='Re-train profile')

    # mic2wav
    mic2wav_parser = sub_parsers.add_parser('mic2wav', help='Voice command to WAV data')

    # mic2text
    mic2text_parser = sub_parsers.add_parser('mic2text', help='Voice command to text transcription')

    # mic2intent
    mic2intent_parser = sub_parsers.add_parser('mic2intent', help='Voice command to parsed intent')

    # word2phonemes
    word2phonemes_parser = sub_parsers.add_parser('word2phonemes', help='Get pronunciation(s) for word(s)')
    word2phonemes_parser.add_argument('words', nargs='*', help='Word(s) to pronounce')
    word2phonemes_parser.add_argument('-n', type=int, default=1, help='Maximum number of pronunciations')

    # word2wav
    word2wav_parser = sub_parsers.add_parser('word2wav', help='Pronounce word')
    word2wav_parser.add_argument('word', help='Word to pronounce')

    # -------------------------------------------------------------------------

    args = parser.parse_args()

    # Like PATH, searched in reverse order
    profiles_dirs = [path for path in
                     os.environ.get('RHASSPY_PROFILES', 'profiles')\
                     .split(':') if len(path.strip()) > 0]

    profiles_dirs.reverse()

    # Create rhasspy core
    from .core import Rhasspy
    core = Rhasspy(profiles_dirs)

    # Load profile
    if args.profile is not None:
        profile = core.profiles[args.profile]
    else:
        profile = core.default_profile

    # Execute command
    command_funcs = {
        'info': info,
        'wav2text': wav2text,
        'text2intent': text2intent,
        'wav2intent': wav2intent,
        'train': train,
        'mic2text': mic2text,
        'mic2intent': mic2intent,
        'mic2wav': mic2wav,
        'word2phonemes': word2phonemes,
        'word2wav': word2wav
    }

    command_funcs[args.command](core, profile, args)

# -----------------------------------------------------------------------------
# info: print profile JSON
# -----------------------------------------------------------------------------

def info(core, profile, args):
    if args.defaults:
        # Print default settings
        json.dump(core.defaults_json, sys.stdout, indent=4)
    else:
        # Print profile settings
        json.dump(profile.json, sys.stdout, indent=4)

# -----------------------------------------------------------------------------
# wav2text: transcribe WAV file(s) to text
# -----------------------------------------------------------------------------

def wav2text(core, profile, args):
    decoder = core.get_speech_decoder(profile.name)

    if len(args.wav_files) > 0:
        # Read WAV paths from argument list
        transcriptions = {}
        for wav_path in args.wav_files:
            with open(wav_path, 'rb') as wav_file:
                text = decoder.transcribe_wav(wav_file.read())
                transcriptions[wav_path] = text

        # Output JSON
        json.dump(transcriptions, sys.stdout, indent=4)
    else:
        # Read WAV data from stdin
        text = decoder.transcribe_wav(sys.stdin.buffer.read())

        # Output text
        print(text)

# -----------------------------------------------------------------------------
# text2intent: parse text into intent(s)
# -----------------------------------------------------------------------------

def text2intent(core, profile, args):
    recognizer = core.get_intent_recognizer(profile.name)

    # Parse sentences from command line or stdin
    intents = {}
    sentences = args.sentences if len(args.sentences) > 0 else sys.stdin
    for sentence in sentences:
        sentence = sentence.strip()
        intent = recognizer.recognize(sentence)
        intents[sentence] = intent

    # Output JSON
    json.dump(intents, sys.stdout, indent=4)

# -----------------------------------------------------------------------------
# wav2intent: transcribe WAV file(s) to text and parse into intent(s)
# -----------------------------------------------------------------------------

def wav2intent(core, profile, args):
    decoder = core.get_speech_decoder(profile.name)
    recognizer = core.get_intent_recognizer(profile.name)

    if len(args.wav_files) > 0:
        # Read WAV paths from argument list
        transcriptions = {}
        for wav_path in args.wav_files:
            with open(wav_path, 'rb') as wav_file:
                text = decoder.transcribe_wav(wav_file.read())
                transcriptions[wav_path] = text

        # Parse intents
        intents = {}
        for wav_path, sentence in transcriptions.items():
            intent = recognizer.recognize(sentence)
            intents[wav_path] = intent

        # Output JSON
        json.dump(intents, sys.stdout, indent=4)
    else:
        # Read WAV data from stdin
        sentence = decoder.transcribe_wav(sys.stdin.buffer.read())
        intent = recognizer.recognize(sentence)

        # Output JSON
        json.dump(intent, sys.stdout, indent=4)

# -----------------------------------------------------------------------------
# train: re-train profile speech/intent recognizers
# -----------------------------------------------------------------------------

def train(core, profile, args):
    core.train_profile(profile.name)

# -----------------------------------------------------------------------------
# mic2wav: record voice command and output WAV data
# -----------------------------------------------------------------------------

def mic2wav(core, profile, args):
    # Listen until silence
    command_listener = core.get_command_listener()
    wav_data = command_listener.listen_for_command()

    # Output WAV data
    sys.stdout.buffer.write(wav_data)

# -----------------------------------------------------------------------------
# mic2text: record voice command, then transcribe
# -----------------------------------------------------------------------------

def mic2text(core, profile, args):
    # Listen until silence
    command_listener = core.get_command_listener()
    wav_data = command_listener.listen_for_command()

    # Transcribe
    decoder = core.get_speech_decoder(profile.name)
    text = decoder.transcribe_wav(wav_data)

    # Output text
    print(text)

# -----------------------------------------------------------------------------
# mic2intent: record voice command, then transcribe/parse
# -----------------------------------------------------------------------------

def mic2intent(core, profile, args):
    # Listen until silence
    command_listener = core.get_command_listener()
    wav_data = command_listener.listen_for_command()

    # Transcribe
    decoder = core.get_speech_decoder(profile.name)
    sentence = decoder.transcribe_wav(wav_data)

    # Parse
    recognizer = core.get_intent_recognizer(profile.name)
    intent = recognizer.recognize(sentence)

    # Output JSON
    json.dump(intent, sys.stdout, indent=4)

# -----------------------------------------------------------------------------
# word2phonemes: get pronunciation(s) for a word
# -----------------------------------------------------------------------------

def word2phonemes(core, profile, args):
    word_pron = core.get_word_pronouncer(profile.name)

    words = args.words if len(args.words) > 0 else sys.stdin
    all_pronunciations = {}

    # Get pronunciations for all words
    for word in words:
        word = word.strip()
        _, word_pronunciations, _ = word_pron.pronounce(word, n=args.n)
        all_pronunciations[word] = word_pronunciations

    # Output JSON
    json.dump(all_pronunciations, sys.stdout, indent=4)

# -----------------------------------------------------------------------------
# word2wav: pronounce word as WAV data
# -----------------------------------------------------------------------------

def word2wav(core, profile, args):
    word_pron = core.get_word_pronouncer(profile.name)

    # Get pronunciation for word
    _, word_pronunciations, _ = word_pron.pronounce(args.word, n=1)

    # Convert from CMU phonemes to eSpeak phonemes
    espeak_str = word_pron.translate_phonemes(word_pronunciations[0])

    # Pronounce as WAV
    _, wav_data = word_pron.speak(espeak_str)

    # Output WAV data
    sys.stdout.buffer.write(wav_data)

# -----------------------------------------------------------------------------

if __name__ == '__main__':
    main()
