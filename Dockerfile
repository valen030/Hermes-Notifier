FROM docker.io/nousresearch/hermes-agent:main

WORKDIR /opt/notifier
COPY requirements.txt /opt/notifier/requirements.txt
RUN python3 -m venv /opt/notifier/.venv && /opt/notifier/.venv/bin/python -m pip install --no-cache-dir -r /opt/notifier/requirements.txt
COPY app.py notifications.py schedule.json /opt/notifier/

ENTRYPOINT ["/opt/notifier/.venv/bin/python", "/opt/notifier/app.py"]
CMD []