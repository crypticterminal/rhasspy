ARG BUILD_CPU
FROM $BUILD_CPU/python:3.6-stretch
LABEL maintainer="Michael Hansen <hansen.mike@gmail.com>"

ARG BUILD_ARCH
ENV LANG C.UTF-8

ARG MAKE_THREADS=4

WORKDIR /

RUN apt-get update && \
    apt-get install -y bash jq \
        build-essential portaudio19-dev swig \
        libatlas-base-dev \
        sox espeak alsa-utils \
        cmake git \
        autoconf libtool automake bison \
        sphinxbase-utils sphinxtrain

# Install phonetisaurus (with openfst 1.3.4)
COPY etc/openfst-1.3.4.tar.gz /
RUN cd / && tar -xvf openfst-1.3.4.tar.gz && \
    cd /openfst-1.3.4/ && \
    ./configure --enable-compact-fsts --enable-const-fsts \
                --enable-far --enable-lookahead-fsts \
                --enable-pdt && \
    make -j $MAKE_THREADS

COPY etc/phonetisaurus-2013.tar.gz /
RUN cd / && tar -xvf phonetisaurus-2013.tar.gz && \
    cd /phonetisaurus-2013/src && \
    mkdir -p bin && \
    CPPFLAGS=-I/openfst-1.3.4/src/include LDFLAGS=-L/openfst-1.3.4/src/lib/.libs/ make -j $MAKE_THREADS bin/phonetisaurus-g2p && \
    cp bin/phonetisaurus-g2p /usr/bin/ && \
    cp /openfst-1.3.4/src/lib/.libs/libfst.* /usr/local/lib/ && \
    rm -rf /openfst-1.3.4* && \
    rm -rf /phonetisaurus-2013*

# Install mitlm
COPY etc/mitlm-0.4.2.tar.xz /
RUN cd / && tar -xf mitlm-0.4.2.tar.xz && cd mitlm-0.4.2/ && \
    ./configure && \
    make -j $MAKE_THREADS && \
    make install && \
    rm -rf /mitlm-0.4.2*

# Install Python dependencies
RUN python3 -m pip install --no-cache-dir wheel
COPY requirements.txt /requirements.txt
RUN python3 -m pip install --no-cache-dir -r /requirements.txt

# Install Pocketsphinx Python module with no sound
COPY etc/pocketsphinx-python.tar.gz /
RUN python3 -m pip install --no-cache-dir /pocketsphinx-python.tar.gz && \
    rm -rf /pocketsphinx-python*

# Install snowboy
COPY etc/snowboy-1.3.0.tar.gz /
RUN if [ "$BUILD_ARCH" != "aarch64" ]; then pip3 install --no-cache-dir /snowboy-1.3.0.tar.gz; fi

# Install Mycroft Precise
RUN if [ "$BUILD_ARCH" = "amd64" ]; then wget -q -O /precise-engine.tar.gz https://github.com/MycroftAI/mycroft-precise/releases/download/v0.2.0/precise-engine_0.2.0_x86_64.tar.gz fi
RUN if [ "$BUILD_ARCH" = "armhf" ]; then wget -q -O /precise-engine.tar.gz https://github.com/MycroftAI/mycroft-precise/releases/download/v0.2.0/precise-engine_0.2.0_armv7l.tar.gz fi
RUN if [ -f /precise-engine.tar.gz ]; then cd / && tar -xzf /precise-engine.tar.gz && ln -s /precise-engine/precise-engine /usr/bin/precise-engine fi

RUN ldconfig

# Copy bw and mllr_solve to /usr/bin
RUN find / -name bw -exec cp '{}' /usr/bin/ \;
RUN find / -name mllr_solve -exec cp '{}' /usr/bin/ \;

# Copy my code
COPY profiles/de/ /usr/share/rhasspy/profiles/de/
COPY profiles/it/ /usr/share/rhasspy/profiles/it/
COPY profiles/es/ /usr/share/rhasspy/profiles/es/
COPY profiles/fr/ /usr/share/rhasspy/profiles/fr/
COPY profiles/it/ /usr/share/rhasspy/profiles/it/
COPY profiles/nl/ /usr/share/rhasspy/profiles/nl/
COPY profiles/en/ /usr/share/rhasspy/profiles/en/
COPY profiles/defaults.json /usr/share/rhasspy/profiles/
COPY docker/rhasspy /usr/share/rhasspy/bin/
COPY dist/ /usr/share/rhasspy/dist/
COPY etc/wav/* /usr/share/rhasspy/etc/wav/
COPY *.py /usr/share/rhasspy/
COPY rhasspy/*.py /usr/share/rhasspy/rhasspy/

# Copy script to run
COPY docker/run.sh /run.sh
RUN chmod a+x /run.sh

ENV CONFIG_PATH /data/options.json

CMD ["/run.sh"]
