# Nexus Supervisor Profiles

These files are production-oriented templates for process-level supervision of
Nexus middleware. They assume the repository is installed at `/opt/nexus` and
logs are written to `/var/log/nexus`.

Supervisor provides local process restart and watchdog-driven recovery only. It
does not replace database replication, RabbitMQ clustering, Redis Sentinel or
Cluster, MinIO distributed erasure coding, or Elasticsearch multi-node cluster
design.

Recommended deployment steps:

1. Copy or symlink `deploy/conf/*-prod.conf` into the service-specific config
   location expected by the installed package.
   For RabbitMQ, copy `deploy/conf/rabbitmq-definitions.json` to
   `/etc/rabbitmq/definitions.json` so the `nexus` vhost and deletion
   protection metadata are imported at startup.
   If a vhost is created manually with `rabbitmqctl add_vhost`, RabbitMQ only
   creates the vhost and built-in exchanges; it does not create NEXUS exchanges
   such as `nexus.jobs` and `nexus.dlx`. Import the definitions or run
   `deploy/scripts/bootstrap-rabbitmq-vhost.sh .env.prod` on the RabbitMQ host
   after creating the service user. The NEXUS vhost name is `nexus`; in an AMQP
   URL, `/nexus` means the vhost named `nexus`, not a vhost named `/nexus`.
2. Create service users: `postgres`, `redis`, `minio`, `rabbitmq`,
   `elasticsearch`.
3. Create `/var/log/nexus` and grant write permission to the relevant service
   users.
4. Place secrets in OS secret files or service-native ACL/definition files.
   Do not commit secrets into this repository.
5. Copy `deploy/supervisor/*-prod.conf` into `/etc/supervisor/conf.d/`.
6. Run `supervisorctl reread`, `supervisorctl update`, and then verify
   `supervisorctl status`.

Health checks support secret files for authenticated services:

- Redis: `REDIS_PASSWORD_FILE=/run/secrets/redis_health_password`
- Elasticsearch: `ES_USERNAME=elastic`,
  `ES_PASSWORD_FILE=/run/secrets/elasticsearch_health_password`
