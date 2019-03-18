#!/usr/bin/env bash

# Directory of *this* script
DIR="$( cd "$( dirname "$0" )" && pwd )"
template="$DIR/Dockerfile.template"
out="$DIR/dockerfiles"
mkdir -p "$out"

# -----------------------------------------------------------------------------

# Uppercases an input string
function upper {
    tr '[[:lower:]]' '[[:upper:]]'
}

# Creates m4 "define" statements from text files in one or more directories.
# The contents of dir/file.txt will be the value of variable FILE.
function set_variables {
    echo "divert(-1)"
    while [[ ! -z "$1" ]]; do
        if [[ -d "$1" ]]; then
            for var_file in $(find "$1" -type f -name "*.txt"); do
                var_name=$(basename "$var_file" .txt | upper)
                echo "define(\`$var_name', \`$(cat $var_file)')"
            done
        elif [[ -f "$1" ]]; then
            var_file="$1"
            var_name=$(basename "$var_file" .txt | upper)
            echo "define(\`$var_name', \`$(cat $var_file)')"
        fi

        shift
    done
    echo "divert(0)dnl"
}

# -----------------------------------------------------------------------------

#-----------
# Pre-built
#-----------
set_variables "$DIR/shared/" "$DIR/prebuilt/" \
              "$DIR/alsa/" "$DIR/en_profile/" \
    | cat - "$template" | m4 > "$out/Dockerfile.prebuilt.alsa.en"

set_variables "$DIR/shared/" "$DIR/prebuilt/" \
              "$DIR/pulseaudio/" "$DIR/en_profile/" \
    | cat - "$template" | m4 > "$out/Dockerfile.prebuilt.pulseaudio.en"

set_variables "$DIR/shared/" "$DIR/prebuilt/" \
              "$DIR/alsa/" "$DIR/all_profiles/" \
    | cat - "$template" | m4 > "$out/Dockerfile.prebuilt.alsa.all"
