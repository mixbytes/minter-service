FROM centos:latest as build
RUN yum install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm
RUN yum groups install -y 'Development Tools'
RUN yum install -y python34 python34-pip python34-devel nodejs npm

WORKDIR /app
ADD ./requirements.txt package.json  /app/


RUN python3 -m venv /venv \
	&& /venv/bin/pip3 install -r requirements.txt --no-cache-dir
RUN npm install --prefix /app --only=dev

COPY ./ /app

RUN rm -f ./bin/test_wrapper.sh
RUN ./bin/deploy /deploy


FROM centos:latest
WORKDIR /app

RUN yum install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm \
	&& yum install -y python34 uwsgi uwsgi-plugin-python3 \
	&& yum clean all \
	&& rm -rf /var/cache/yum 
	

COPY --from=build /deploy /app
COPY --from=build /venv /venv

RUN mv ./bin/shell /usr/local/bin
        
ENV PYTHONPATH=/app/lib/
VOLUME [ "/app/data", "/app/conf/minter.conf", "/app/conf/ico_info.conf" ]

# start app
ENTRYPOINT [ "./bin/start-service.sh" ]
CMD [ "wsgi_app.py" ]

