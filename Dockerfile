FROM fedora:26


RUN dnf install -y python2-pip qemu-img libguestfs-tools-c

ADD . /vocker.d/

RUN cd /vocker.d && pip install -rrequirements.txt && python setup.py install

CMD cd /vocker.d/contrib/ && bash -x vocker-job
