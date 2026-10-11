FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git openssh-client \
    && rm -rf /var/lib/apt/lists/*

# The app lives in the private fzoll/ncore-streamer repo, which the Supervisor
# build cannot authenticate to. run.sh clones the commit pinned in REVISION at
# container start, using a deploy key generated under /data.
COPY REVISION /REVISION
COPY run.sh /run.sh
RUN chmod +x /run.sh

ENV PYTHONUNBUFFERED=1
CMD ["/run.sh"]
