#!/usr/bin/env bash
DIR="$( cd "$( dirname "$0" )" && pwd )"
rhasspy_dir="${DIR}/../../"
download_dir="${DIR}/download"
mkdir -p "${download_dir}"

echo "Downloading Greek (el) profile (sphinx)"

#------------------------------------------------------------------------------
# Acoustic Model
#------------------------------------------------------------------------------

acoustic_url='https://github.com/synesthesiam/rhasspy-profiles/releases/download/v1.0-el/cmusphinx-el-gr-5.2.tar.gz'
acoustic_file="${download_dir}/cmusphinx-el-5.2.tar.gz"
acoustic_output="${DIR}/acoustic_model"

if [[ ! -f "${acoustic_file}" ]]; then
    echo "Downloading acoustic model"
    wget -q -O "${acoustic_file}" "${acoustic_url}"
fi

echo "Extracting acoustic model (${acoustic_file})"
rm -rf "${acoustic_output}"
tar -xf "${acoustic_file}" "cmusphinx-el-gr-5.2/el-gr.cd_cont_5000/" && mv "${DIR}/cmusphinx-el-gr-5.2/el-gr.cd_cont_5000" "${acoustic_output}" && rm -rf "${DIR}/cmusphinx-el-gr-5.2" || exit 1

#------------------------------------------------------------------------------
# G2P
#------------------------------------------------------------------------------

g2p_url='https://github.com/synesthesiam/rhasspy-profiles/releases/download/v1.0-el/el-g2p.tar.gz'
g2p_file="${download_dir}/el-g2p.tar.gz"
g2p_output="${DIR}/g2p.fst"

if [[ ! -f "${g2p_file}" ]]; then
    echo "Downloading g2p model"
    wget -q -O "${g2p_file}" "${g2p_url}"
fi

echo "Extracting g2p model (${g2p_file})"
tar --to-stdout -xzf "${g2p_file}" 'g2p.fst' > "${g2p_output}" || exit 1

#------------------------------------------------------------------------------
# Dictionary
#------------------------------------------------------------------------------

dict_output="${DIR}/base_dictionary.txt"
echo "Extracting dictionary (${acoustic_file})"
tar --to-stdout -xzf "${acoustic_file}" 'cmusphinx-el-gr-5.2/el-gr.dic' > "${dict_output}" || exit 1

#------------------------------------------------------------------------------
# Language Model
#------------------------------------------------------------------------------

lm_output="${DIR}/base_language_model.txt"
echo "Extracting language model (${acoustic_file})"
tar --to-stdout -xzf "${acoustic_file}" 'cmusphinx-el-gr-5.2/el-gr.lm.gz' | zcat > "${lm_output}" || exit 1
