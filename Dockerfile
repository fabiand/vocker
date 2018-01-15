FROM fedora:26


RUN dnf install -y python3-pip qemu-img libguestfs-tools-c virt-install
RUN curl -L http://download.libguestfs.org/binaries/appliance/appliance-1.36.1.tar.xz | tar -C $(guestfish get-path) -xJf -

ADD . /vocker.d/

RUN cd /vocker.d && pip3 install -rrequirements.txt && python3 setup.py install

ENV LIBGUESTFS_BACKEND=direct
ENV LIBGUESTFS_PATH=$(guestfish get-path)/appliance
CMD cd /vocker.d/contrib/ && bash -x vocker-job
