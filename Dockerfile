FROM centos:latest as build
RUN yum install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm
RUN yum groups install -y 'Development Tools'
RUN yum install -y python36 python3-pip python36-devel nodejs npm \
        libuuid libuuid-devel libcap-devel openssl-devel uwsgi uwsgi-devel

WORKDIR /app
ADD ./requirements.txt package.json  /app/


RUN python36 -m venv /venv \
    && /venv/bin/pip3.6 install -r requirements.txt --no-cache-dir \
    && PYTHON=/usr/bin/python3.6 uwsgi --build-plugin "/usr/src/uwsgi/2.0.16/plugins/python python36"


RUN npm install --prefix /app --only=dev

COPY ./ /app

RUN rm -f ./bin/test_wrapper.sh && \
    ln -s /usr/bin/python3.6 /usr/bin/python3
RUN ./bin/deploy /deploy


FROM centos:latest
WORKDIR /app

RUN yum install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm \
    && yum install -y python36 uwsgi\
    && yum clean all \
    && rm -rf /var/cache/yum \
    && ln -s /usr/bin/python3.6 /usr/bin/python3 \
    && mkdir /usr/lib64/uwsgi


COPY --from=build /deploy /app
COPY --from=build /venv /venv
COPY --from=build /app/python36_plugin.so /usr/lib64/uwsgi/

#RUN ln -s /venv/bin/uwsgi /usr/sbin/uwsgi && \
#RUN adduser -U -M uwsgi


RUN mv ./bin/shell /usr/local/bin

ENV PYTHONPATH=/app/lib/

VOLUME [ "/app/data", "/app/conf/minter.conf", "/app/conf/ico_info.conf" ]

# start app
ENTRYPOINT [ "./bin/start-service.sh" ]
CMD [ "wsgi_app.py" ]

