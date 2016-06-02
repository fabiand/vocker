FROM fedora:23

MAINTAINER "Roman Mohr" <rmohr@redhat.com>

ENV HELLO="Hello World"

RUN pip3 install --no-cache-dir static3

RUN mkdir -p /html && echo "$HELLO" > /html/index.html

EXPOSE 8080

CMD /usr/bin/static /html 0.0.0.0:8080
