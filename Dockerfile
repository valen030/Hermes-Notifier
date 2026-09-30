FROM docker.io/nousresearch/hermes-agent:main

COPY app.py notifications.py schedule.json /opt/notifier/

ENV HERMES_DASHBOARD=0 HERMES_GATEWAY_NO_SUPERVISE=1 PYTHONPATH=/opt/hermes
RUN rm -f /etc/cont-init.d/02-reconcile-profiles

CMD ["/opt/hermes/.venv/bin/python", "/opt/notifier/app.py"]