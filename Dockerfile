FROM docker.io/nousresearch/hermes-agent:main

WORKDIR /opt/notifier
COPY app.py notifications.py schedule.json test_notifications.py /opt/notifier/

ENV HERMES_DASHBOARD=0 HERMES_GATEWAY_NO_SUPERVISE=1
RUN test -x /opt/hermes/docker/entrypoint-dispatch.sh \
	&& /opt/hermes/.venv/bin/python -c "from cron.scheduler_provider import InProcessCronScheduler; from cron.scheduler import create_job_with_scheduler_registration; import dotenv, yaml" \
	&& /opt/hermes/.venv/bin/python -m unittest test_notifications -v \
	&& rm -f /etc/cont-init.d/02-reconcile-profiles

CMD ["/opt/hermes/.venv/bin/python", "/opt/notifier/app.py"]