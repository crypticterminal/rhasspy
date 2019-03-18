#!/usr/bin/env bash
if [[ -z "$(which phonetisaurus-train)" ]]; then
    echo "Phonetisaurus not installed!"
    exit 1
fi

if [[ -z "$2" ]]; then
    echo "Usage: make-g2p.sh DICTIONARY MODEL"
    exit 1
fi

dict_path=$(realpath "$1")
model_path=$(realpath "$2")

temp_dir="$(mktemp -d)"
function finish {
    rm -rf "$temp_dir"
}

trap finish EXIT

cd "$temp_dir"
cat "$dict_path" | \
    perl -pe 's/\([0-9]+\)//;
              s/\s+/ /g; s/^\s+//;
              s/\s+$//; @_ = split (/\s+/);
              $w = shift (@_);
              $_ = $w."\t".join (" ", @_)."\n";' | sed -e '/_/d' > formatted.dict

phonetisaurus-train --lexicon formatted.dict --seq2_del --verbose
cp train/model.fst "$model_path"
