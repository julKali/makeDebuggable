FROM debian
ARG UID GID
RUN echo "makedebuggable:x:$GID:" >>/etc/group && useradd --uid $UID --gid makedebuggable makedebuggable
RUN apt-get update && apt-get install -y python3 zipalign apksigner
WORKDIR /home/makedebuggable
