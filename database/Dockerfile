FROM postgres:18.6-trixie AS vector-build
ARG PGVECTOR_VERSION=0.8.7
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates curl postgresql-server-dev-18 \
    && curl --fail --location --retry 3 "https://github.com/pgvector/pgvector/archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz" -o /tmp/vector.tar.gz \
    && mkdir /tmp/vector \
    && tar -xzf /tmp/vector.tar.gz --strip-components=1 -C /tmp/vector \
    && make -C /tmp/vector OPTFLAGS="" \
    && make -C /tmp/vector install DESTDIR=/opt/vector

FROM postgres:18.6-trixie
COPY --from=vector-build /opt/vector/ /
COPY init/ /docker-entrypoint-initdb.d/
# PG18 uses /var/lib/postgresql/18/docker inside this parent volume.
