FROM fedora:26


RUN dnf install -y python3-pip qemu-img libguestfs-tools-c virt-install

ADD . /vocker.d/

RUN cd /vocker.d && pip3 install -rrequirements.txt && python3 setup.py install

CMD cd /vocker.d/contrib/ && bash -x vocker-job
