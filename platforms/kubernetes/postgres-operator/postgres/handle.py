import logging
import kopf
import paramiko
import os
import string
import time
import random
import tempfile
from kubernetes import client, config
from kubernetes.stream import stream
from config import operator_config
from typed import LabelType, InstanceConnection, InstanceConnections, TypedDict, InstanceConnectionMachine, InstanceConnectionK8S, Tuple, Any, List

from constants import (
    VIP,
    RADONDB_POSTGRES,
    POSTGRES_OPERATOR,
    AUTOFAILOVER,
    POSTGRESQL,
    READWRITEINSTANCE,
    READONLYINSTANCE,
    MACHINES,
    ACTION,
    ACTION_START,
    ACTION_STOP,
    IMAGE,
    PODSPEC,
    SPEC,
    CONTAINERS,
    CONTAINER_NAME,
    POSTGRESQL_CONTAINER,
    PRIME_SERVICE_PORT_NAME,
    HBAS,
    CONFIGS,
    REPLICAS,
    VOLUMECLAIMTEMPLATES,
    AUTOCTL_NODE,
    PGAUTOFAILOVER_REPLICATOR,
    STREAMING,
    STREAMING_SYNC,
    STREAMING_ASYNC,
    DELETE_PVC,
    POSTGRESQL_PVC_NAME,
    SUCCESS,
    FAILED,
    SERVICES,
    SELECTOR,
    SERVICE_AUTOFAILOVER,
    SERVICE_PRIMARY,
    SERVICE_STANDBY,
    SERVICE_READONLY,
    SERVICE_STANDBY_READONLY,
    USERS,
    ADMIN_USER,
    NORMAL_USER,
    USER_NAME,
    USER_PASSWORD,
    API_GROUP,
    API_VERSION_V1,
    RESOURCE_POSTGRESQL,
    RESOURCE_KIND_POSTGRESQL,
    CLUSTER_CREATE_CLUSTER,
    CLUSTER_CREATE_BEGIN,
    CLUSTER_CREATE_ADD_FAILOVER,
    CLUSTER_CREATE_ADD_READWRITE,
    CLUSTER_CREATE_ADD_READONLY,
    CLUSTER_CREATE_FINISH,
    BASE_LABEL_PART_OF,
    BASE_LABEL_MANAGED_BY,
    BASE_LABEL_NAME,
    BASE_LABEL_NAMESPACE,
    LABEL_NODE,
    LABEL_NODE_AUTOFAILOVER,
    LABEL_NODE_POSTGRESQL,
    LABEL_NODE_USER_SERVICES,
    LABEL_NODE_STATEFULSET_SERVICES,
    LABEL_SUBNODE,
    LABEL_SUBNODE_READWRITE,
    LABEL_SUBNODE_AUTOFAILOVER,
    LABEL_SUBNODE_READONLY,
    LABEL_ROLE,
    LABEL_ROLE_PRIMARY,
    LABEL_ROLE_STANDBY,
    LABEL_STATEFULSET_NAME,
    MACHINE_MODE,
    K8S_MODE,
    DOCKER_COMPOSE_FILE,
    DOCKER_COMPOSE_FILE_DATA,
    DOCKER_COMPOSE_ENV,
    DOCKER_COMPOSE_ENV_DATA,
    DOCKER_COMPOSE_ENVFILE,
    DOCKER_COMPOSE_DIR,
    PGDATA_DIR,
    ASSIST_DIR,
    DATA_DIR,
    INIT_FINISH,
    PG_CONFIG_PREFIX,
    PG_HBA_PREFIX,
    RESTORE,
    RESTORE_FROMSSH,
    RESTORE_FROMSSH_PATH,
    RESTORE_FROMSSH_ADDRESS,
    RESTORE_FROMSSH_LOCAL,
    PG_DATABASE_DIR,
    LVS_BODY,
    LVS_REAL_MAIN_SERVER,
    LVS_REAL_READ_SERVER,
    LVS_SET_NET,
)

FIELD_DELIMITER = "-"
WAITING_POSTGRESQL_READY_COMMAND = ["pgtools", "-a"]
INIT_FINISH_MESSAGE = "init postgresql finish"
STOP_FAILED_MESSAGE = "stop auto_failover failed"
SWITCHOVER_FAILED_MESSAGE = "switchover failed"
AUTO_FAILOVER_PORT = 55555
DIFF_ADD = "add"
DIFF_CHANGE = "change"
DIFF_REMOVE = "remove"
DIFF_FIELD_ACTION = (SPEC, ACTION)
DIFF_FIELD_SERVICE = (SPEC, SERVICES)
DIFF_FIELD_AUTOFAILOVER_HBAS = (SPEC, AUTOFAILOVER, HBAS)
DIFF_FIELD_POSTGRESQL_HBAS = (SPEC, POSTGRESQL, HBAS)
DIFF_FIELD_AUTOFAILOVER_CONFIGS = (SPEC, AUTOFAILOVER, CONFIGS)
DIFF_FIELD_POSTGRESQL_CONFIGS = (SPEC, POSTGRESQL, CONFIGS)
DIFF_FIELD_POSTGRESQL_USERS = (SPEC, POSTGRESQL, USERS)
DIFF_FIELD_POSTGRESQL_USERS_ADMIN = (SPEC, POSTGRESQL, USERS, ADMIN_USER)
DIFF_FIELD_POSTGRESQL_USERS_NORMAL = (SPEC, POSTGRESQL, USERS, NORMAL_USER)
DIFF_FIELD_STREAMING = (SPEC, POSTGRESQL, READONLYINSTANCE, STREAMING)
DIFF_FIELD_READWRITE_REPLICAS = (SPEC, POSTGRESQL, READWRITEINSTANCE, REPLICAS)
DIFF_FIELD_READWRITE_MACHINES = (SPEC, POSTGRESQL, READWRITEINSTANCE, MACHINES)
DIFF_FIELD_READONLY_REPLICAS = (SPEC, POSTGRESQL, READONLYINSTANCE, REPLICAS)
DIFF_FIELD_READONLY_MACHINES = (SPEC, POSTGRESQL, READONLYINSTANCE, MACHINES)
DIFF_FIELD_AUTOFAILOVER_PODSPEC = (SPEC, AUTOFAILOVER, PODSPEC)
DIFF_FIELD_READWRITE_PODSPEC = (SPEC, POSTGRESQL, READWRITEINSTANCE, PODSPEC)
DIFF_FIELD_READONLY_PODSPEC = (SPEC, POSTGRESQL, READONLYINSTANCE, PODSPEC)
DIFF_FIELD_AUTOFAILOVER_VOLUME = (SPEC, AUTOFAILOVER, VOLUMECLAIMTEMPLATES)
DIFF_FIELD_READWRITE_VOLUME = (SPEC, POSTGRESQL, READWRITEINSTANCE,
                               VOLUMECLAIMTEMPLATES)
DIFF_FIELD_READONLY_VOLUME = (SPEC, POSTGRESQL, READONLYINSTANCE,
                              VOLUMECLAIMTEMPLATES)
STATEFULSET_REPLICAS = 1
PG_CONFIG_IGONRE = ("block_size", "data_checksums", "data_directory_mode",
                    "debug_assertions", "integer_datetimes", "lc_collate",
                    "lc_ctype", "max_function_args", "max_identifier_length",
                    "max_index_keys", "segment_size", "server_encoding",
                    "server_version", "server_version_num", "ssl_library",
                    "wal_block_size", "wal_segment_size")
PG_CONFIG_RESTART = (
    "allow_system_table_mods", "archive_mode", "autovacuum_freeze_max_age",
    "autovacuum_max_workers", "autovacuum_multixact_freeze_max_age", "bonjour",
    "bonjour_name", "cluster_name", "config_file", "data_directory",
    "data_sync_retry", "dynamic_shared_memory_type", "event_source",
    "external_pid_file", "hba_file", "hot_standby", "huge_pages", "ident_file",
    "jit_provider", "listen_addresses", "logging_collector", "max_connections",
    "max_files_per_process", "max_locks_per_transaction",
    "max_logical_replication_workers", "max_pred_locks_per_transaction",
    "max_prepared_transactions", "max_replication_slots", "max_wal_senders",
    "max_worker_processes", "old_snapshot_threshold", "pg_stat_statements.max",
    "port", "primary_conninfo", "primary_slot_name", "recovery_target",
    "recovery_target_action", "recovery_target_inclusive",
    "recovery_target_lsn", "recovery_target_name", "recovery_target_time",
    "recovery_target_timeline", "recovery_target_xid", "restore_command",
    "shared_buffers", "shared_memory_type")

POSTGRESQL_PAUSE = "pause"
POSTGRESQL_RESUME = "resume"
KEEPALIVED_CONF = "/etc/keepalived/keepalived.conf"
START_KEEPALIVED = "systemctl restart keepalived.service"
STOP_KEEPALIVED = "systemctl stop keepalived.service"
STATUS_KEEPALIVED = "systemctl status keepalived.service"


def set_create_cluster(patch, state: str) -> None:
    patch.status[CLUSTER_CREATE_CLUSTER] = state


def set_password(patch: kopf.Patch, status: kopf.Status) -> None:
    password_length = 8

    if status.get(AUTOCTL_NODE) == None:
        patch.status[AUTOCTL_NODE] = ''.join(
            random.sample(string.ascii_letters + string.digits,
                          password_length))

    if status.get(PGAUTOFAILOVER_REPLICATOR) == None:
        patch.status[PGAUTOFAILOVER_REPLICATOR] = ''.join(
            random.sample(string.ascii_letters + string.digits,
                          password_length))


def create_statefulset_service(
    name: str,
    external_name: str,
    namespace: str,
    labels: LabelType,
    #port: int,
    logger: logging.Logger,
    meta: kopf.Meta,
) -> None:
    core_v1_api = client.CoreV1Api()

    statefulset_service_body = {}
    statefulset_service_body["apiVersion"] = "v1"
    statefulset_service_body["kind"] = "Service"
    statefulset_service_body["metadata"] = {
        "name": name,
        "namespace": namespace
        #"labels": get_statefulset_service_labels(meta)
    }
    statefulset_service_body["spec"] = {
        "clusterIP": "None",
        "selector": labels
        # allow all port
        #"ports": [{
        #    "port": port,
        #    "targetPort": port
        #}]
    }

    logger.info(f"create statefulset service with {statefulset_service_body}")
    kopf.adopt(statefulset_service_body)
    core_v1_api.create_namespaced_service(namespace=namespace,
                                          body=statefulset_service_body)

    #service_body = {}
    #service_body["apiVersion"] = "v1"
    #service_body["kind"] = "Service"
    #service_body["metadata"] = {
    #    "name": external_name,
    #    "namespace": namespace
    #}
    #service_body["spec"] = {
    #    "type": "ClusterIP",
    #    "selector": labels,
    #    "ports": [{
    #        "port": port,
    #        "targetPort": port
    #    }]
    #}

    #logger.info(f"create statefulset external service with {service_body}")
    #kopf.adopt(service_body)
    #core_v1_api.create_namespaced_service(namespace=namespace,
    #                                      body=service_body)


def get_connhost(conn: InstanceConnection) -> str:

    if conn.get_k8s() != None:
        return pod_conn_get_pod_address(conn)
    if conn.get_machine() != None:
        return conn.get_machine().get_host()


def autofailover_switchover(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    auto_failover_conns = connections(spec, meta, patch,
                                      get_field(AUTOFAILOVER), False, None,
                                      logger, None, status, False)
    for conn in auto_failover_conns.get_conns():
        cmd = ["pgtools", "-o"]
        logger.info(f"switchover with cmd {cmd}")
        output = exec_command(conn, cmd, logger, interrupt=False)
        if output.find(SWITCHOVER_FAILED_MESSAGE) != -1:
            logger.error(f"switchover failed, {output}")
    auto_failover_conns.free_conns()


def get_primary_host(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> str:
    auto_failover_conns = connections(spec, meta, patch,
                                      get_field(AUTOFAILOVER), False, None,
                                      logger, None, status, False)
    for conn in auto_failover_conns.get_conns():
        cmd = [
            "pgtools", "-w", "0", "-Q", "pg_auto_failover", "-q",
            '''" select nodehost from pgautofailover.node where reportedstate = 'primary' or reportedstate = 'wait_primary' or reportedstate = 'single'  "'''
        ]
        output = exec_command(conn, cmd, logger, interrupt=False)
        break
    auto_failover_conns.free_conns()
    return output.strip()


def waiting_cluster_correct_status(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    # waiting for restart
    time.sleep(5)
    auto_failover_conns = connections(spec, meta, patch,
                                      get_field(AUTOFAILOVER), False, None,
                                      logger, None, status, False)
    for conn in auto_failover_conns.get_conns():
        not_correct_cmd = [
            "pgtools", "-w", "0", "-Q", "pg_auto_failover", "-q",
            '''" select count(*) from pgautofailover.node where reportedstate <> 'primary' and reportedstate <> 'secondary' and reportedstate <> 'single' and reportedstate <> 'wait_primary' and reportedstate <> 'catchingup' "'''
        ]
        primary_cmd = [
            "pgtools", "-w", "0", "-Q", "pg_auto_failover", "-q",
            '''" select count(*) from pgautofailover.node where reportedstate = 'primary' or reportedstate ='wait_primary'  "'''
        ]
        nodes_cmd = [
            "pgtools", "-w", "0", "-Q", "pg_auto_failover", "-q",
            '''" select count(*) from pgautofailover.node  "'''
        ]

        i = 0
        maxtry = 60
        while True:
            logger.info(
                f"waiting auto_failover correct cluster Status, {i} times. ")
            i += 1
            time.sleep(1)
            if i >= maxtry:
                logger.warning(
                    f"cluster maybe maybe not right. skip waitting.")
                break
            #total_nodes = int(
            #    spec[POSTGRESQL][READWRITEINSTANCE][REPLICAS]) + int(
            #        spec[POSTGRESQL][READONLYINSTANCE][REPLICAS]) # TODO machinemode len(machines)
            #output = exec_command(conn, nodes_cmd, logger, interrupt=False)
            #if output != str(total_nodes):
            #    logger.warning(
            #        f"there are {output} nodes in autofailover, expect {total_nodes} nodes"
            #    )
            #    continue
            output = exec_command(conn, primary_cmd, logger, interrupt=False)
            if output != '1':
                logger.warning(
                    f"not find primary node in autofailover, output is {output}"
                )
                continue
            output = exec_command(conn,
                                  not_correct_cmd,
                                  logger,
                                  interrupt=False)
            if output != '0':
                logger.warning(
                    f"there are {output} nodes is not primary/secondary/single/wait_primary/catchingup"
                )
                continue

            break
    auto_failover_conns.free_conns()


def waiting_postgresql_ready(conns: InstanceConnections,
                             logger: logging.Logger):
    for conn in conns.get_conns():
        i = 0
        maxtry = 300
        while True:
            output = exec_command(conn,
                                  WAITING_POSTGRESQL_READY_COMMAND,
                                  logger,
                                  interrupt=False)
            if output != INIT_FINISH_MESSAGE:
                i += 1
                time.sleep(1)
                logger.error(f"init is not finish. try {i} times. {output}")
                if i >= maxtry:
                    logger.warning(f"init is not finish. skip waitting.")
                    break
            else:
                break
    # wait service refresh endpoint
    time.sleep(10)


def waiting_instance_ready(conns: InstanceConnections, logger: logging.Logger):
    success_message = 'running success'
    for conn in conns.get_conns():
        i = 0
        maxtry = 300
        while True:
            output = exec_command(conn,
                                  "echo '%s'" % success_message,
                                  logger,
                                  interrupt=False)
            if output != success_message:
                i += 1
                time.sleep(1)
                logger.error(f"instance not start. try {i} times. {output}")
                if i >= maxtry:
                    logger.warning(f"instance not start. skip waitting.")
                    break
            else:
                break


def create_statefulset(
    name: str,
    namespace: str,
    labels: LabelType,
    podspec_need_copy: TypedDict,
    vct: TypedDict,
    env: TypedDict,
    logger: logging.Logger,
) -> None:

    apps_v1_api = client.AppsV1Api()
    statefulset_body = {}
    statefulset_body["apiVersion"] = "apps/v1"
    statefulset_body["kind"] = "StatefulSet"
    statefulset_body["metadata"] = {"name": name, "namespace": namespace}
    statefulset_body["spec"] = {}
    statefulset_body_spec_selector = {"matchLabels": labels}
    statefulset_body["spec"]["selector"] = statefulset_body_spec_selector
    statefulset_body["spec"]["replicas"] = STATEFULSET_REPLICAS
    statefulset_body["spec"][
        "serviceName"] = statefulset_name_get_service_name(name)
    podspec = podspec_need_copy.copy()
    podspec["restartPolicy"] = "Always"
    for container in podspec[CONTAINERS]:
        if container[CONTAINER_NAME] == POSTGRESQL_CONTAINER:
            container["args"] = ["auto_failover"]
            container["env"] = env
            container["readinessProbe"] = {
                "initialDelaySeconds": 20,
                "periodSeconds": 5,
                "exec": {
                    "command": WAITING_POSTGRESQL_READY_COMMAND
                }
            }
    statefulset_body["spec"]["template"] = {
        "metadata": {
            "labels": labels
        },
        "spec": podspec
    }
    statefulset_body["spec"]["volumeClaimTemplates"] = vct

    logger.info(f"create statefulset with {statefulset_body}")
    kopf.adopt(statefulset_body)
    apps_v1_api.create_namespaced_stateful_set(namespace=namespace,
                                               body=statefulset_body)


def get_statefulset_name(name: str, field: str, replica: int) -> str:
    return name + "-" + field + "-" + str(replica)


def get_statefulset_service_name(name: str, field: str, replica: int) -> str:
    return get_statefulset_name(name, field, replica)


def statefulset_name_get_service_name(name: str) -> str:
    return name


def statefulset_name_get_external_service_name(name: str) -> str:
    return name + "-external"


def statefulset_name_get_pod_name(name: str) -> str:
    return name + "-0"


def pod_name_get_statefulset_name(name: str) -> str:
    return name[0:-2]  # erase "-0"


def get_pvc_name(pod_name: str):
    return POSTGRESQL_PVC_NAME + "-" + pod_name


def get_pod_name(name: str, field: str, replica: int) -> str:
    return get_statefulset_name(name, field, replica) + "-0"


def pod_conn_get_pod_address(conn: InstanceConnection) -> str:
    #op-pg-lzzhang-autofailover-0-0.op-pg-lzzhang-autofailover-0.default.svc.cluster.local
    #podname.svcname.namespace.svc.cluster.local
    return conn.get_k8s().get_podname() + "." + pod_name_get_statefulset_name(
        conn.get_k8s().get_podname()) + "." + conn.get_k8s().get_namespace(
        ) + ".svc.cluster.local"


def get_pod_address(name: str, field: str, replica: int,
                    namespace: str) -> str:
    #op-pg-lzzhang-autofailover-0-0.op-pg-lzzhang-autofailover-0.default.svc.cluster.local
    #podname.svcname.namespace.svc.cluster.local
    return get_pod_name(
        name, field, replica) + "." + get_statefulset_service_name(
            name, field, replica) + "." + namespace + ".svc.cluster.local"
    #return statefulset_name_get_external_service_name(get_statefulset_service_name(name, field, replica))


def create_postgresql(
    mode: str,
    spec: kopf.Spec,
    meta: kopf.Meta,
    field: str,
    labels: LabelType,
    logger: logging.Logger,
    conns: InstanceConnections,
    patch: kopf.Patch,
    create_begin: int,
    status: kopf.Status,
    wait_primary: bool,
) -> None:

    logger.info("create postgresql on " + mode)

    if len(field.split(FIELD_DELIMITER)) == 1:
        localspec = spec.get(field)
        hbas = localspec[HBAS]
        configs = localspec[CONFIGS]
        machine_data_path = operator_config.DATA_PATH_AUTOFAILOVER
    else:
        if len(field.split(FIELD_DELIMITER)) != 2:
            raise kopf.PermanentError(
                "error parse field, only support one '.'" + field)
        localspec = spec.get(field.split(FIELD_DELIMITER)[0]).get(
            field.split(FIELD_DELIMITER)[1])
        hbas = spec[field.split(FIELD_DELIMITER)[0]][HBAS]
        configs = spec[field.split(FIELD_DELIMITER)[0]][CONFIGS]
        machine_data_path = operator_config.DATA_PATH_POSTGRESQL

    for container in localspec[PODSPEC][CONTAINERS]:
        if container[CONTAINER_NAME] == POSTGRESQL_CONTAINER:
            postgresql_image = container[IMAGE]

    if mode == MACHINE_MODE:
        replicas = conns.get_number()
        pgdata = os.path.join(machine_data_path, PGDATA_DIR)
        remotepath = os.path.join(machine_data_path, DOCKER_COMPOSE_DIR)
        machine_env = ""
    else:
        replicas = localspec.get(REPLICAS)
        if replicas == None:
            replicas = 1
        k8s_env = []
        #k8s_env.append({"name": "REFRESH_ENV", "value": "0"})

    for i, hba in enumerate(hbas):
        env_name = PG_HBA_PREFIX + str(i)
        env_value = hba
        if mode == MACHINE_MODE:
            machine_env += env_name + "=" + env_value + "\n"
        else:
            k8s_env.append({"name": env_name, "value": env_value})

    for config in configs:
        name = config.split("=")[0].strip()
        value = config[config.find("=") + 1:].strip()
        config = name + "=" + value
        if name in PG_CONFIG_IGONRE:
            continue
        if field == get_field(AUTOFAILOVER) and name == 'port':
            continue

        if mode == MACHINE_MODE:
            machine_env += PG_CONFIG_PREFIX + config + "\n"
        else:
            k8s_env.append({"name": PG_CONFIG_PREFIX + name, "value": value})
    if mode == MACHINE_MODE:
        machine_env += PG_CONFIG_PREFIX + 'log_truncate_on_rotation=true' + "\n"
        machine_env += PG_CONFIG_PREFIX + 'logging_collector=on' + "\n"
        machine_env += PG_CONFIG_PREFIX + "log_directory='log'" + "\n"
        machine_env += PG_CONFIG_PREFIX + "log_filename='postgresql_%d'" + "\n"
        machine_env += PG_CONFIG_PREFIX + "log_line_prefix='[%m][%r][%a][%u][%d][%x][%p]'" + "\n"
        machine_env += PG_CONFIG_PREFIX + "log_destination='csvlog'" + "\n"
        machine_env += PG_CONFIG_PREFIX + 'log_autovacuum_min_duration=-1' + "\n"
        machine_env += PG_CONFIG_PREFIX + "log_timezone='Asia/Shanghai'" + "\n"
        machine_env += PG_CONFIG_PREFIX + "datestyle='iso, ymd'" + "\n"
        machine_env += PG_CONFIG_PREFIX + "timezone='Asia/Shanghai'" + "\n"
    else:
        k8s_env.append({
            "name": PG_CONFIG_PREFIX + "log_truncate_on_rotation",
            "value": "true"
        })
        k8s_env.append({
            "name": PG_CONFIG_PREFIX + "logging_collector",
            "value": "on"
        })
        k8s_env.append({
            "name": PG_CONFIG_PREFIX + "log_directory",
            "value": "'log'"
        })
        k8s_env.append({
            "name": PG_CONFIG_PREFIX + "log_filename",
            "value": "'postgresql_%d'"
        })
        k8s_env.append({
            "name": PG_CONFIG_PREFIX + "log_line_prefix",
            "value": "'[%m][%r][%a][%u][%d][%x][%p]'"
        })
        k8s_env.append({
            "name": PG_CONFIG_PREFIX + "log_destination",
            "value": "'csvlog'"
        })
        k8s_env.append({
            "name": PG_CONFIG_PREFIX + "log_autovacuum_min_duration",
            "value": "-1"
        })
        k8s_env.append({
            "name": PG_CONFIG_PREFIX + "log_timezone",
            "value": "'Asia/Shanghai'"
        })
        k8s_env.append({
            "name": PG_CONFIG_PREFIX + "datestyle",
            "value": "'iso, ymd'"
        })
        k8s_env.append({
            "name": PG_CONFIG_PREFIX + "timezone",
            "value": "'Asia/Shanghai'"
        })
    for replica in range(create_begin, replicas):
        name = get_statefulset_name(meta["name"], field, replica)
        namespace = meta["namespace"]
        autoctl_node_password = patch.status.get(AUTOCTL_NODE)
        if autoctl_node_password == None:
            autoctl_node_password = status.get(AUTOCTL_NODE)
        autoctl_replicator_password = patch.status.get(
            PGAUTOFAILOVER_REPLICATOR)
        if autoctl_replicator_password == None:
            autoctl_replicator_password = status.get(PGAUTOFAILOVER_REPLICATOR)

        if field == get_field(AUTOFAILOVER):
            if mode == MACHINE_MODE:
                machine_env += "PG_MODE=monitor\n"
                machine_env += "AUTOCTL_NODE_PASSWORD=" + autoctl_node_password + "\n"
                machine_env += "EXTERNAL_HOSTNAME=" + conns.get_conns(
                )[replica].get_machine().get_host() + "\n"
            else:
                k8s_env.append({"name": "PG_MODE", "value": "monitor"})
                k8s_env.append({
                    "name": "AUTOCTL_NODE_PASSWORD",
                    "value": autoctl_node_password
                })
                k8s_env.append({
                    "name":
                    "EXTERNAL_HOSTNAME",
                    "value":
                    get_pod_address(meta["name"], field, replica, namespace)
                })

        if field == get_field(POSTGRESQL, READWRITEINSTANCE):
            if mode == MACHINE_MODE:
                auto_failover_conns = connections(spec, meta, patch,
                                                  get_field(AUTOFAILOVER),
                                                  False, None, logger, None,
                                                  status, False)
                auto_failover_host = auto_failover_conns.get_conns(
                )[0].get_machine().get_host()
                auto_failover_conns.free_conns()
                machine_env += "PG_MODE=readwrite\n"
                machine_env += "AUTOCTL_NODE_PASSWORD=" + autoctl_node_password + "\n"
                machine_env += "EXTERNAL_HOSTNAME=" + conns.get_conns(
                )[replica].get_machine().get_host() + "\n"
                machine_env += "AUTOCTL_REPLICATOR_PASSWORD=" + autoctl_replicator_password + "\n"
                machine_env += "MONITOR_HOSTNAME=" + auto_failover_host + "\n"
            else:
                k8s_env.append({"name": "PG_MODE", "value": "readwrite"})
                k8s_env.append({
                    "name": "AUTOCTL_NODE_PASSWORD",
                    "value": autoctl_node_password
                })
                k8s_env.append({
                    "name":
                    "EXTERNAL_HOSTNAME",
                    "value":
                    get_pod_address(meta["name"], field, replica, namespace)
                })
                k8s_env.append({
                    "name": "AUTOCTL_REPLICATOR_PASSWORD",
                    "value": autoctl_replicator_password
                })
                k8s_env.append({
                    "name":
                    "MONITOR_HOSTNAME",
                    "value":
                    get_pod_address(meta["name"], AUTOFAILOVER, 0, namespace)
                })
        if field == get_field(POSTGRESQL, READONLYINSTANCE):
            if mode == MACHINE_MODE:
                auto_failover_conns = connections(spec, meta, patch,
                                                  get_field(AUTOFAILOVER),
                                                  False, None, logger, None,
                                                  status, False)
                auto_failover_host = auto_failover_conns.get_conns(
                )[0].get_machine().get_host()
                auto_failover_conns.free_conns()
                machine_env += "PG_MODE=readonly\n"
                machine_env += "AUTOCTL_NODE_PASSWORD=" + autoctl_node_password + "\n"
                machine_env += "EXTERNAL_HOSTNAME=" + conns.get_conns(
                )[replica].get_machine().get_host() + "\n"
                machine_env += "AUTOCTL_REPLICATOR_PASSWORD=" + autoctl_replicator_password + "\n"
                machine_env += "PG_STREAMING=" + localspec[STREAMING] + "\n"
                machine_env += "MONITOR_HOSTNAME=" + auto_failover_host + "\n"
            else:
                k8s_env.append({"name": "PG_MODE", "value": "readonly"})
                k8s_env.append({
                    "name": "AUTOCTL_NODE_PASSWORD",
                    "value": autoctl_node_password
                })
                k8s_env.append({
                    "name":
                    "EXTERNAL_HOSTNAME",
                    "value":
                    get_pod_address(meta["name"], field, replica, namespace)
                })
                k8s_env.append({
                    "name": "AUTOCTL_REPLICATOR_PASSWORD",
                    "value": autoctl_replicator_password
                })
                k8s_env.append({
                    "name": "PG_STREAMING",
                    "value": localspec[STREAMING]
                })
                k8s_env.append({
                    "name":
                    "MONITOR_HOSTNAME",
                    "value":
                    get_pod_address(meta["name"], AUTOFAILOVER, 0, namespace)
                })

        if mode == MACHINE_MODE:
            logger.info("put docker-compose file to remote")
            machine_sftp_put(
                conns.get_conns()[replica].get_machine().get_sftp(),
                DOCKER_COMPOSE_FILE_DATA %
                (conns.get_conns()[replica].get_machine().get_role(),
                 conns.get_conns()[replica].get_machine().get_role()),
                os.path.join(remotepath, DOCKER_COMPOSE_FILE))
            machine_sftp_put(
                conns.get_conns()[replica].get_machine().get_sftp(),
                DOCKER_COMPOSE_ENV_DATA.format(
                    postgresql_image,
                    conns.get_conns()[replica].get_machine().get_host(),
                    pgdata), os.path.join(remotepath, DOCKER_COMPOSE_ENV))
            machine_sftp_put(
                conns.get_conns()[replica].get_machine().get_sftp(),
                machine_env, os.path.join(remotepath, DOCKER_COMPOSE_ENVFILE))

            logger.info("start with docker-compose")
            machine_exec_command(
                conns.get_conns()[replica].get_machine().get_ssh(),
                "cd " + os.path.join(machine_data_path, DOCKER_COMPOSE_DIR) +
                "; docker-compose up -d")
        else:
            create_statefulset_service(
                statefulset_name_get_service_name(name),
                statefulset_name_get_external_service_name(name), namespace,
                labels, logger, meta)
            create_statefulset(name, namespace, labels, localspec[PODSPEC],
                               localspec[VOLUMECLAIMTEMPLATES], k8s_env,
                               logger)

        # wait primary node create finish
        if wait_primary == True and field == get_field(
                POSTGRESQL, READWRITEINSTANCE) and replica == 0:
            # don't free the tmpconns
            tmpconn = conns.get_conns()[0]
            if is_restore_mode(meta, spec, patch, status, logger) == False:
                tmpconns: InstanceConnections = InstanceConnections()
                tmpconns.add(tmpconn)
                waiting_postgresql_ready(tmpconns, logger)

                create_log_table(
                    logger, tmpconn,
                    int(
                        postgresql_image.split(':')[1].split('-')[0].split('.')
                        [0]))

                create_users(meta, spec, patch, status, logger, tmpconns)
            else:
                restore_postgresql(meta, spec, patch, status, logger, tmpconn)


def restore_postgresql_fromssh(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    conn: InstanceConnection,
) -> None:
    path = spec[RESTORE][RESTORE_FROMSSH][RESTORE_FROMSSH_PATH]
    address = spec[RESTORE][RESTORE_FROMSSH][RESTORE_FROMSSH_ADDRESS]

    # create the new instance but use the old data.
    if path == PG_DATABASE_DIR and address == RESTORE_FROMSSH_LOCAL:
        # update password
        correct_user_password(meta, spec, patch, status, logger, conn)
        return

    # drop from autofailover and pause start postgresql
    cmd = ["pgtools", "-d", "-p", POSTGRESQL_PAUSE]
    exec_command(conn, cmd, logger, interrupt=True)

    # don't free the tmpconns
    tmpconns: InstanceConnections = InstanceConnections()
    tmpconns.add(conn)
    waiting_instance_ready(tmpconns)

    # remove old data
    cmd = ["rm", "-rf", PG_DATABASE_DIR]
    exec_command(conn, cmd, logger, interrupt=True)

    # copy data command
    if address == RESTORE_FROMSSH_LOCAL:
        ssh_conn = conn
        cmd = ["mv", path, PG_DATABASE_DIR]
    else:
        username = address.split(":")[0]
        password = address.split(":")[1]
        host = address.split(":")[2]
        port = int(address.split(":")[3])

        cmd = [
            "sshpass", "-p", password, "scp", "-P",
            str(port), "-o", '"StrictHostKeyChecking no"', '-r',
            "%s@%s:%s %s" % (username, host, path, PG_DATABASE_DIR)
        ]
        ssh_conn = connect_machine(address)

    # copy data
    exec_command(conn, cmd, logger, interrupt=True)

    # resume postgresql
    cmd = ["pgtools", "-p", POSTGRESQL_RESUME]
    exec_command(conn, cmd, logger, interrupt=True)

    # waiting posgresql ready
    waiting_postgresql_ready(tmpconns, logger)

    # update password
    correct_user_password(meta, spec, patch, status, logger, conn)

    if address == RESTORE_FROMSSH_LOCAL:
        pass
    else:
        ssh_conn.free_conn()


def is_restore_mode(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> bool:
    if spec.get(RESTORE) == None:
        return False

    if spec[RESTORE].get(RESTORE_FROMSSH) != None:
        return True

    return False


def restore_postgresql(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    conn: InstanceConnection,
) -> None:
    if spec[RESTORE].get(RESTORE_FROMSSH) != None:
        restore_postgresql_fromssh(meta, spec, patch, status, logger, conn)


def create_log_table(logger: logging.Logger, conn: InstanceConnection,
                     postgresql_major_version: int) -> None:
    logger.info("create postgresql log table")
    cmd = ["pgtools", "-q", '"create extension file_fdw"']
    output = exec_command(conn, cmd, logger, interrupt=False)
    if output.find("CREATE EXTENSION") == -1:
        logger.error(f"can't create file_fdw {cmd}, {output}")

    cmd = [
        "pgtools", "-q",
        '"create server pg_file_server foreign data wrapper file_fdw"'
    ]
    output = exec_command(conn, cmd, logger, interrupt=False)
    if output.find("CREATE SERVER") == -1:
        #logging.getLogger().error(
        logger.error(f"can't create pg_file_server {cmd}, {output}")

    for day in range(1, 32):
        table_name = 'log_postgresql_' + "%02d" % day
        log_filepath = "log/postgresql_" + "%02d" % day + '.csv'
        if postgresql_major_version == 12:
            query = """ CREATE foreign TABLE %s
                (
                     log_time timestamp(3) without time zone,
                     user_name text,
                     database_name text,
                     process_id integer,
                     connection_from text,
                     session_id text,
                     session_line_num bigint,
                     command_tag text,
                     session_start_time timestamp without time zone,
                     virtual_transaction_id text,
                     transaction_id bigint,
                     error_severity text,
                     sql_state_code text,
                     message text,
                     detail text,
                     hint text,
                     internal_query text,
                     internal_query_pos integer,
                     context text,
                     query text,
                     query_pos integer,
                     location text,
                     application_name text
                ) server pg_file_server options(filename '%s',format 'csv',header 'true') """ % (
                table_name, log_filepath)
        elif postgresql_major_version == 13:
            query = """ CREATE foreign TABLE %s
                (
                     log_time timestamp(3) with time zone,
                     user_name text,
                     database_name text,
                     process_id integer,
                     connection_from text,
                     session_id text,
                     session_line_num bigint,
                     command_tag text,
                     session_start_time timestamp with time zone,
                     virtual_transaction_id text,
                     transaction_id bigint,
                     error_severity text,
                     sql_state_code text,
                     message text,
                     detail text,
                     hint text,
                     internal_query text,
                     internal_query_pos integer,
                     context text,
                     query text,
                     query_pos integer,
                     location text,
                     application_name text,
                     backend_type text
                ) server pg_file_server options(filename '%s',format 'csv',header 'true') """ % (
                table_name, log_filepath)
        elif postgresql_major_version == 14:
            query = """ CREATE foreign TABLE %s
                (
                     log_time timestamp(3) with time zone,
                     user_name text,
                     database_name text,
                     process_id integer,
                     connection_from text,
                     session_id text,
                     session_line_num bigint,
                     command_tag text,
                     session_start_time timestamp with time zone,
                     virtual_transaction_id text,
                     transaction_id bigint,
                     error_severity text,
                     sql_state_code text,
                     message text,
                     detail text,
                     hint text,
                     internal_query text,
                     internal_query_pos integer,
                     context text,
                     query text,
                     query_pos integer,
                     location text,
                     application_name text,
                     backend_type text,
                     leader_pid integer,
                     query_id bigint
                ) server pg_file_server options(filename '%s',format 'csv',header 'true') """ % (
                table_name, log_filepath)
        else:
            logger.warning(
                f"no compatible postgresql version {postgresql_major_version}, create log with postgresql 14 query."
            )
            query = """ CREATE foreign TABLE %s
                (
                     log_time timestamp(3) with time zone,
                     user_name text,
                     database_name text,
                     process_id integer,
                     connection_from text,
                     session_id text,
                     session_line_num bigint,
                     command_tag text,
                     session_start_time timestamp with time zone,
                     virtual_transaction_id text,
                     transaction_id bigint,
                     error_severity text,
                     sql_state_code text,
                     message text,
                     detail text,
                     hint text,
                     internal_query text,
                     internal_query_pos integer,
                     context text,
                     query text,
                     query_pos integer,
                     location text,
                     application_name text,
                     backend_type text,
                     leader_pid integer,
                     query_id bigint
                ) server pg_file_server options(filename '%s',format 'csv',header 'true') """ % (
                table_name, log_filepath)

        logger.info(f"create postgresql log table {table_name} query {query}")
        cmd = ["pgtools", "-q", '"' + query + '"']
        output = exec_command(conn, cmd, logger, interrupt=False)
        if output.find("CREATE FOREIGN TABLE") == -1:
            logger.error(f"can't create table {cmd}, {output}")


def connect_pods(
    meta: kopf.Meta,
    spec: kopf.Spec,
    field: str,
) -> InstanceConnections:

    conns: InstanceConnections = InstanceConnections()

    if len(field.split(FIELD_DELIMITER)) == 1:
        localspec = spec.get(field)
        role = AUTOFAILOVER
    else:
        if len(field.split(FIELD_DELIMITER)) != 2:
            raise kopf.PermanentError(
                "error parse field, only support one '.'" + field)
        localspec = spec.get(field.split(FIELD_DELIMITER)[0]).get(
            field.split(FIELD_DELIMITER)[1])
        role = POSTGRESQL

    replicas = localspec.get(REPLICAS)
    if replicas == None:
        replicas = 1

    for replica in range(0, replicas):
        name = get_pod_name(meta["name"], field, replica)
        namespace = meta["namespace"]
        conn = InstanceConnection(None,
                                  InstanceConnectionK8S(name, namespace, role))
        conns.add(conn)

    return conns


def connect_machine(machine: str,
                    role: str = POSTGRESQL) -> InstanceConnection:
    username = machine.split(":")[0]
    password = machine.split(":")[1]
    host = machine.split(":")[2]
    port = int(machine.split(":")[3])

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    i = 0
    max_times = 600

    while True:
        try:
            ssh.connect(host, username=username, port=port, password=password)
            time.sleep(0.1)
            break
        except Exception as e:
            time.sleep(1)
            i += 1
            if i >= max_times:
                raise kopf.PermanentError(
                    f"ssh can't connect to machine {machine} : {e}")
                break

    trans = paramiko.Transport((host, port))
    try:
        trans.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(trans)
    except Exception as e:
        raise kopf.PermanentError(
            f"sftp can't connect to machine {machine} : {e}")

    conn = InstanceConnection(
        InstanceConnectionMachine(host, port, username, password, ssh, sftp,
                                  trans, role), None)
    cmd = "mkdir -p " + os.path.join(operator_config.DATA_PATH_AUTOFAILOVER,
                                     DOCKER_COMPOSE_DIR)
    machine_exec_command(conn.get_machine().get_ssh(), cmd)
    cmd = "mkdir -p " + os.path.join(operator_config.DATA_PATH_POSTGRESQL,
                                     DOCKER_COMPOSE_DIR)
    machine_exec_command(conn.get_machine().get_ssh(), cmd)
    return conn


def machine_sftp_put(sftp: paramiko.SFTPClient, buffer: str,
                     remotepath: str) -> None:
    try:
        tf = tempfile.NamedTemporaryFile()
        tf.write(buffer.encode('utf-8'))
        tf.flush()
        sftp.put(localpath=tf.name, remotepath=remotepath)
        tf.close()
    except Exception as e:
        raise kopf.PermanentError(
            f"can't put file to remote {remotepath} : {e}")


def machine_sftp_get(sftp: paramiko.SFTPClient, localpath: str,
                     remotepath: str) -> None:
    try:
        sftp.get(remotepath=remotepath, localpath=localpath)
    except Exception as e:
        raise kopf.PermanentError(
            f"can't get file from remote {remotepath} : {e}")


def exec_command(conn: InstanceConnection,
                 cmd: [str],
                 logger: logging.Logger,
                 interrupt: bool = True):
    if conn.get_k8s() != None:
        return pod_exec_command(conn.get_k8s().get_podname(),
                                conn.get_k8s().get_namespace(), cmd, logger,
                                interrupt)
    if conn.get_machine() != None:
        return docker_exec_command(conn.get_machine().get_role(),
                                   conn.get_machine().get_ssh(), cmd, logger,
                                   interrupt)


def pod_exec_command(name: str,
                     namespace: str,
                     cmd: [str],
                     logger: logging.Logger,
                     interrupt: bool = True) -> str:
    try:
        core_v1_api = client.CoreV1Api()
        # stderr stdout all in resp. don't have return code.
        resp = stream(core_v1_api.connect_get_namespaced_pod_exec,
                      name,
                      namespace,
                      command=["/bin/bash", "-c", " ".join(cmd)],
                      stderr=True,
                      stdin=False,
                      stdout=True,
                      tty=False)
        return resp.replace('\n', '')
    except Exception as e:
        if interrupt:
            raise kopf.PermanentError(
                f"pod {name} exec command({cmd}) failed {e}")
        else:
            logger.error(f"pod {name} exec command({cmd}) failed {e}")
            return FAILED

    return resp.replace('\n', '')


def docker_exec_command(role: str,
                        ssh: paramiko.SSHClient,
                        cmd: [str],
                        logger: logging.Logger,
                        interrupt: bool = True) -> str:
    if role == AUTOFAILOVER:
        machine_data_path = operator_config.DATA_PATH_AUTOFAILOVER
    if role == POSTGRESQL:
        machine_data_path = operator_config.DATA_PATH_POSTGRESQL
    try:
        workdir = os.path.join(machine_data_path, DOCKER_COMPOSE_DIR)
        #cmd = "cd " + workdir + "; docker-compose exec " + role + " " + " ".join(cmd)
        cmd = "docker exec " + role + " " + " ".join(cmd)
        logger.info(f"docker exec command {cmd}")
        ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command(cmd, get_pty=True)
    except Exception as e:
        if interrupt:
            raise kopf.PermanentError(f"can't run command: {cmd} , {e}")
        else:
            return FAILED

    # see pod_exec_command, don't check ret_code
    std_output = ssh_stdout.read().decode().strip()
    err_output = ssh_stderr.read().decode().strip()
    #ret_code = ssh_stdout.channel.recv_exit_status()
    #if ret_code != 0:
    #    if interrupt:
    #        raise kopf.PermanentError(
    #            f"docker {ssh} exec command {cmd}  failed, resp is: {err_output} {std_output}"
    #        )
    #    else:
    #        logger.error(
    #            f"docker {ssh} exec command {cmd}  failed, resp is: {err_output} {std_output}"
    #        )
    #        return FAILED

    #return str(ssh_stdout.read()).replace('\\r\\n', '').replace('\\n', '')[2:-1]
    return std_output + err_output


def machine_exec_command(ssh: paramiko.SSHClient,
                         cmd: str,
                         interrupt: bool = True) -> str:
    try:
        ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command(cmd)
    except Exception as e:
        raise kopf.PermanentError(f"can't run command: {cmd} , error {e}")

    err_output = ssh_stderr.read().decode()
    ret_code = ssh_stdout.channel.recv_exit_status()
    if ret_code != 0:
        if interrupt:
            raise kopf.TemporaryError(
                f"can't run command: {cmd} , error {err_output}")

    return ssh_stdout.read().decode().strip() + err_output


def connections(
    spec: kopf.Spec,
    meta: kopf.Meta,
    patch: kopf.Patch,
    field: str,
    create: bool,
    labels: LabelType,
    logger: logging.Logger,
    create_begin: int,
    status: kopf.Status,
    wait_primary: bool,
) -> InstanceConnections:

    conns: InstanceConnections = InstanceConnections()
    if len(field.split(FIELD_DELIMITER)) == 1:
        machines = spec.get(AUTOFAILOVER).get(MACHINES)
        role = AUTOFAILOVER
    else:
        if len(field.split(FIELD_DELIMITER)) != 2:
            raise kopf.PermanentError(
                "error parse field, only support one '-'" + field)
        machines = spec.get(field.split(FIELD_DELIMITER)[0]).get(
            field.split(FIELD_DELIMITER)[1]).get(MACHINES)
        role = POSTGRESQL

    if machines == None:
        logger.info("connect node in k8s mode")
        conns = connect_pods(meta, spec, field)
        if create:
            create_postgresql(K8S_MODE, spec, meta, field, labels, logger,
                              conns, patch, create_begin, status, wait_primary)
    else:
        for replica, machine in enumerate(machines):
            conn = connect_machine(machine, role)
            logger.info("connect node in machine mode, host is " +
                        conn.get_machine().get_host())
            conns.add(conn)
        if create:
            create_postgresql(MACHINE_MODE, spec, meta, field, labels, logger,
                              conns, patch, create_begin, status, wait_primary)
    return conns


def get_field(*fields):
    field = ""

    for i, f in enumerate(fields):
        if i > 0:
            field += FIELD_DELIMITER + f
        else:
            field = f

    return field


def create_autofailover(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    labels: LabelType,
) -> None:
    logger.info("create autofailover")
    conns = connections(spec, meta, patch, get_field(AUTOFAILOVER), True,
                        labels, logger, 0, status, False)
    conns.free_conns()


def connections_target(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    field: str,
    target_machines: List,
    target_k8s: List,
) -> InstanceConnections:

    conns: InstanceConnections = InstanceConnections()
    if len(field.split(FIELD_DELIMITER)) == 1:
        role = AUTOFAILOVER
    else:
        role = POSTGRESQL

    if target_machines != None:
        for replica, machine in enumerate(target_machines):
            conn = connect_machine(machine, role)
            logger.info("connect node in machine mode, host is " +
                        conn.get_machine().get_host())
            conns.add(conn)
    if target_k8s != None:
        for replica in range(target_k8s[0], target_k8s[1]):
            name = get_pod_name(meta["name"], field, replica)
            namespace = meta["namespace"]
            conn = InstanceConnection(
                None, InstanceConnectionK8S(name, namespace, role))
            logger.info("connect node in k8s mode, podname is " + name)
            conns.add(conn)

    return conns


def machine_postgresql_down(conn: InstanceConnection,
                            logger: logging.Logger) -> None:
    if conn.get_machine().get_role() == AUTOFAILOVER:
        machine_data_path = operator_config.DATA_PATH_AUTOFAILOVER
    if conn.get_machine().get_role() == POSTGRESQL:
        machine_data_path = operator_config.DATA_PATH_POSTGRESQL

    cmd = "cd " + os.path.join(machine_data_path,
                               DOCKER_COMPOSE_DIR) + "; docker-compose down"
    logger.info("delete postgresql instance from machine " +
                conn.get_machine().get_host())
    machine_exec_command(conn.get_machine().get_ssh(), cmd)


# only stop the instance not do pgtools -d/-D
def delete_postgresql(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    delete_disk: bool,
    conn: InstanceConnection,
) -> None:
    if delete_disk == True:
        logger.info("delete postgresql instance from autofailover")
        if get_primary_host(meta, spec, patch, status,
                            logger) == get_connhost(conn):
            autofailover_switchover(meta, spec, patch, status, logger)
        cmd = ["pgtools", "-D"]
        output = exec_command(conn, cmd, logger, interrupt=False)
        if output.find("ERROR") != -1:
            logger.error("can't delete postgresql instance " + output)
    else:
        cmd = ["pgtools", "-R"]
        logger.info(f"stop postgresql with cmd {cmd} ")
        output = exec_command(conn, cmd, logger, interrupt=False)
        if output.find(STOP_FAILED_MESSAGE) != -1:
            logger.warning(f"can't stop postgresql. {output}, force stop it")

    if conn.get_machine() != None:
        machine_postgresql_down(conn, logger)
    elif conn.get_k8s() != None:
        try:
            apps_v1_api = client.AppsV1Api()
            logger.info(
                "delete postgresql instance statefulset from k8s " +
                pod_name_get_statefulset_name(conn.get_k8s().get_podname()))
            api_response = apps_v1_api.delete_namespaced_stateful_set(
                pod_name_get_statefulset_name(conn.get_k8s().get_podname()),
                conn.get_k8s().get_namespace())
        except Exception as e:
            logger.error(
                f"Exception when calling AppsV1Api->delete_namespaced_stateful_set: {e} "
            )
        try:
            logger.info("delete postgresql instance service from k8s " +
                        statefulset_name_get_service_name(
                            pod_name_get_statefulset_name(
                                conn.get_k8s().get_podname())))
            core_v1_api = client.CoreV1Api()
            delete_response = core_v1_api.delete_namespaced_service(
                statefulset_name_get_service_name(
                    pod_name_get_statefulset_name(
                        conn.get_k8s().get_podname())),
                conn.get_k8s().get_namespace())
        except Exception as e:
            logger.error(
                "Exception when calling CoreV1Api->delete_namespaced_service: %s\n"
                % e)
        #try:
        #    logger.info("delete postgresql instance service from k8s " +
        #                statefulset_name_get_external_service_name(
        #                    pod_name_get_statefulset_name(
        #                        conn.get_k8s().get_podname())))
        #    core_v1_api = client.CoreV1Api()
        #    delete_response = core_v1_api.delete_namespaced_service(
        #        statefulset_name_get_external_service_name(
        #            pod_name_get_statefulset_name(
        #                conn.get_k8s().get_podname())),
        #        conn.get_k8s().get_namespace())
        #except Exception as e:
        #    logger.error(
        #        "Exception when calling CoreV1Api->delete_namespaced_service: %s\n"
        #        % e)

    if delete_disk == True:
        delete_storage(meta, spec, patch, status, logger, conn)


def delete_autofailover(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    field: str,
    target_machines: List,
    target_k8s: List,  #[begin:int, end: int]
    delete_disk: bool,
) -> None:
    logger.info("delete autofailover instance")
    conns = connections_target(meta, spec, patch, status, logger, field,
                               target_machines, target_k8s)
    for conn in conns.get_conns():
        delete_postgresql(meta, spec, patch, status, logger, delete_disk, conn)
    conns.free_conns()


def delete_postgresql_readwrite(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    field: str,
    target_machines: List,
    target_k8s: List,  #[begin:int, end: int]
    delete_disk: bool,
) -> None:
    logger.info("delete postgresql readwrite instance")
    conns = connections_target(meta, spec, patch, status, logger, field,
                               target_machines, target_k8s)
    for conn in conns.get_conns():
        delete_postgresql(meta, spec, patch, status, logger, delete_disk, conn)
    conns.free_conns()


def delete_postgresql_readonly(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    field: str,
    target_machines: List,
    target_k8s: List,  #[begin:int, end: int]
    delete_disk: bool,
) -> None:
    logger.info("delete postgresql readonly instance")
    conns = connections_target(meta, spec, patch, status, logger, field,
                               target_machines, target_k8s)
    for conn in conns.get_conns():
        delete_postgresql(meta, spec, patch, status, logger, delete_disk, conn)
    conns.free_conns()


def create_postgresql_readwrite(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    labels: LabelType,
    create_begin: int,
    wait_primary: bool,
) -> None:
    logger.info("create postgresql readwrite instance")
    conns = connections(spec, meta, patch,
                        get_field(POSTGRESQL, READWRITEINSTANCE), True, labels,
                        logger, create_begin, status, wait_primary)
    conns.free_conns()


def create_postgresql_readonly(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    labels: LabelType,
    create_begin: int,
) -> None:
    logger.info("create postgresql readonly instance")
    conns = connections(spec, meta, patch,
                        get_field(POSTGRESQL, READONLYINSTANCE), True, labels,
                        logger, create_begin, status, False)
    conns.free_conns()


def get_base_labels(meta: kopf.Meta) -> TypedDict:
    base_labels = {
        BASE_LABEL_MANAGED_BY: POSTGRES_OPERATOR,
        BASE_LABEL_PART_OF: RADONDB_POSTGRES,
        BASE_LABEL_NAME: meta["name"],
        BASE_LABEL_NAMESPACE: meta["namespace"],
    }
    return base_labels


def get_service_name(meta: kopf.Meta, service: TypedDict) -> str:
    return meta["name"] + "-" + service["metadata"]["name"]


def get_service_autofailover_labels(meta: kopf.Meta) -> TypedDict:
    labels = get_base_labels(meta)
    labels[LABEL_NODE] = LABEL_NODE_AUTOFAILOVER
    labels[LABEL_SUBNODE] = LABEL_SUBNODE_AUTOFAILOVER
    return labels


def get_service_primary_labels(meta: kopf.Meta) -> TypedDict:
    labels = get_base_labels(meta)
    labels[LABEL_NODE] = LABEL_NODE_POSTGRESQL
    labels[LABEL_SUBNODE] = LABEL_SUBNODE_READWRITE
    labels[LABEL_ROLE] = LABEL_ROLE_PRIMARY
    return labels


def dict_to_str(dicts: TypedDict) -> str:
    r = ""
    i = 0
    for d in dicts:
        i += 1
        if i > 1:
            r += ", "
        r += d + "=" + dicts[d]
    return r


def get_readwrite_labels(meta: kopf.Meta) -> TypedDict:
    labels = get_base_labels(meta)
    labels[LABEL_NODE] = LABEL_NODE_POSTGRESQL
    labels[LABEL_SUBNODE] = LABEL_SUBNODE_READWRITE
    return labels


def get_autofailover_labels(meta: kopf.Meta) -> TypedDict:
    labels = get_base_labels(meta)
    labels[LABEL_NODE] = LABEL_NODE_AUTOFAILOVER
    labels[LABEL_SUBNODE] = LABEL_SUBNODE_AUTOFAILOVER
    return labels


def get_readonly_labels(meta: kopf.Meta) -> TypedDict:
    labels = get_base_labels(meta)
    labels[LABEL_NODE] = LABEL_NODE_POSTGRESQL
    labels[LABEL_SUBNODE] = LABEL_SUBNODE_READONLY
    labels[LABEL_ROLE] = LABEL_ROLE_STANDBY
    return labels


def get_service_standby_labels(meta: kopf.Meta) -> TypedDict:
    labels = get_base_labels(meta)
    labels[LABEL_NODE] = LABEL_NODE_POSTGRESQL
    labels[LABEL_SUBNODE] = LABEL_SUBNODE_READWRITE
    labels[LABEL_ROLE] = LABEL_ROLE_STANDBY
    return labels


def get_service_readonly_labels(meta: kopf.Meta) -> TypedDict:
    labels = get_base_labels(meta)
    labels[LABEL_NODE] = LABEL_NODE_POSTGRESQL
    labels[LABEL_SUBNODE] = LABEL_SUBNODE_READONLY
    labels[LABEL_ROLE] = LABEL_ROLE_STANDBY
    return labels


def get_service_standby_readonly_labels(meta: kopf.Meta) -> TypedDict:
    labels = get_base_labels(meta)
    labels[LABEL_NODE] = LABEL_NODE_POSTGRESQL
    labels[LABEL_ROLE] = LABEL_ROLE_STANDBY
    return labels


def get_primary_conn(conns: InstanceConnections,
                     timeout: int,
                     logger: logging.Logger,
                     interrupt: bool = True) -> InstanceConnection:
    if timeout <= 1:
        timeout = 1

    for i in range(0, timeout):
        for conn in conns.get_conns():
            cmd = ["pgtools", "-w", "0", "-q", "'show transaction_read_only'"]
            output = exec_command(conn, cmd, logger, interrupt=False)
            if output == "off":
                return conn
        time.sleep(1)
        logger.warning(f"get primary conn failed. try again {i} times.")

    if interrupt:
        raise kopf.TemporaryError("can't find postgresql primary node")
    else:
        return None


def create_one_user(conn: InstanceConnection, name: str, password: str,
                    admin: bool, logger: logging.Logger) -> None:
    cmd = "create user " + name + " "
    if admin:
        cmd = cmd + " SUPERUSER CREATEROLE REPLICATION CREATEDB "
    cmd = cmd + " password '" + password + "'"
    cmd = ["pgtools", "-q", '"' + cmd + '"']

    logger.info(f"create postgresql user with cmd {cmd}")
    output = exec_command(conn, cmd, logger, interrupt=False)
    if output != "CREATE ROLE":
        logger.error(f"can't create user {cmd}, {output}")


def drop_one_user(conn: InstanceConnection, name: str,
                  logger: logging.Logger) -> None:
    cmd = "drop user if exists " + name + " "
    cmd = ["pgtools", "-q", '"' + cmd + '"']

    logger.info(f"drop postgresql user with cmd {cmd}")
    output = exec_command(conn, cmd, logger, interrupt=False)
    if output != "DROP ROLE":
        logger.error(f"can't drop user {cmd}, {output}")


def change_user_password(conn: InstanceConnection, name: str, password: str,
                         logger: logging.Logger) -> None:
    cmd = "alter user " + name + " "
    cmd = cmd + " password '" + password + "'"
    cmd = ["pgtools", "-q", '"' + cmd + '"']

    logger.info(f"alter postgresql user with cmd {cmd}")
    output = exec_command(conn, cmd, logger, interrupt=False)
    if output != "ALTER ROLE":
        logger.error(f"can't alter user {cmd}, {output}")


def create_users_admin(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    conns: InstanceConnections,
) -> None:
    if spec[POSTGRESQL].get(USERS) == None:
        return

    conn = get_primary_conn(conns, 0, logger)

    if spec[POSTGRESQL][USERS].get(ADMIN_USER) != None:
        admin_users = spec[POSTGRESQL][USERS][ADMIN_USER]
        for user in admin_users:
            create_one_user(conn, user[USER_NAME], user[USER_PASSWORD], True,
                            logger)


def create_users_normal(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    conns: InstanceConnections,
) -> None:
    if spec[POSTGRESQL].get(USERS) == None:
        return

    conn = get_primary_conn(conns, 0, logger)

    if spec[POSTGRESQL][USERS].get(NORMAL_USER) != None:
        normal_users = spec[POSTGRESQL][USERS][NORMAL_USER]
        for user in normal_users:
            create_one_user(conn, user[USER_NAME], user[USER_PASSWORD], False,
                            logger)


def create_users(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    conns: InstanceConnections,
) -> None:
    if spec[POSTGRESQL].get(USERS) == None:
        return

    create_users_admin(meta, spec, patch, status, logger, conns)
    create_users_normal(meta, spec, patch, status, logger, conns)


def get_statefulset_service_labels(meta: kopf.Meta) -> str:
    labels = get_base_labels(meta)
    labels[LABEL_NODE] = LABEL_NODE_STATEFULSET_SERVICES

    return labels


def get_service_labels(meta: kopf.Meta) -> str:
    labels = get_base_labels(meta)
    labels[LABEL_NODE] = LABEL_NODE_USER_SERVICES

    return labels


def get_postgresql_config_port(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> int:
    configs = spec[POSTGRESQL][CONFIGS]
    for i, config in enumerate(configs):
        name = config.split("=")[0].strip()
        value = config[config.find("=") + 1:].strip()
        if name == 'port':
            return int(value)

    return 5432


def create_services(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    autofailover_machines = spec.get(AUTOFAILOVER).get(MACHINES)
    # k8s mode
    if autofailover_machines == None:
        core_v1_api = client.CoreV1Api()
        autofailover = False

        for service in spec[SERVICES]:
            if service[SELECTOR] == SERVICE_AUTOFAILOVER:
                labels = get_service_autofailover_labels(meta)
                autofailover = True
            elif service[SELECTOR] == SERVICE_PRIMARY:
                labels = get_service_primary_labels(meta)
            elif service[SELECTOR] == SERVICE_STANDBY:
                labels = get_service_standby_labels(meta)
            elif service[SELECTOR] == SERVICE_READONLY:
                labels = get_service_readonly_labels(meta)
            elif service[SELECTOR] == SERVICE_STANDBY_READONLY:
                labels = get_service_standby_readonly_labels(meta)
            else:
                raise kopf.PermanentError("unknow the services selector " +
                                          service[SELECTOR])

            service_body = {}
            service_body["apiVersion"] = "v1"
            service_body["kind"] = "Service"
            service_body["metadata"] = {
                "name": get_service_name(meta, service),
                "namespace": meta["namespace"],
                "labels": get_service_labels(meta)
            }

            service_body["spec"] = service["spec"]
            if autofailover == False:
                for port in service_body["spec"]["ports"]:
                    if port["name"] == PRIME_SERVICE_PORT_NAME:
                        postgresql_config_port = int(port['port'])
                postgresql_config_port = get_postgresql_config_port(
                    meta, spec, patch, status, logger)
                for port in service_body["spec"]["ports"]:
                    if port["name"] == PRIME_SERVICE_PORT_NAME:
                        port["targetPort"] = postgresql_config_port
            else:
                for port in service_body["spec"]["ports"]:
                    if port["name"] == PRIME_SERVICE_PORT_NAME:
                        port["targetPort"] = AUTO_FAILOVER_PORT

            service_body["spec"]["selector"] = labels

            logger.info(f"create service with {service_body}")
            kopf.adopt(service_body)
            core_v1_api.create_namespaced_service(namespace=meta["namespace"],
                                                  body=service_body)

    else:
        real_main_servers = []
        real_read_servers = []
        main_vip = ""
        read_vip = ""

        for service in spec[SERVICES]:
            if service[SELECTOR] == SERVICE_PRIMARY:
                machines = spec.get(POSTGRESQL).get(READWRITEINSTANCE).get(
                    MACHINES)
                main_vip = service[VIP]
            elif service[SELECTOR] == SERVICE_READONLY:
                machines = spec.get(POSTGRESQL).get(READONLYINSTANCE).get(
                    MACHINES)
                read_vip = service[VIP]
            elif service[SELECTOR] == SERVICE_STANDBY_READONLY:
                machines = spec.get(POSTGRESQL).get(READWRITEINSTANCE).get(
                    MACHINES)
                machines += spec.get(POSTGRESQL).get(READONLYINSTANCE).get(
                    MACHINES)
                read_vip = service[VIP]
            else:
                logger.error(f"unsupport service {service}")
                continue

            for machine in machines:
                if service[SELECTOR] == SERVICE_PRIMARY:
                    real_main_servers.append(
                        LVS_REAL_MAIN_SERVER.format(
                            ip=machine.split(':')[2],
                            port=get_postgresql_config_port(
                                meta, spec, patch, status, logger)))
                else:
                    real_read_servers.append(
                        LVS_REAL_READ_SERVER.format(
                            ip=machine.split(':')[2],
                            port=get_postgresql_config_port(
                                meta, spec, patch, status, logger)))

        lvs_conf = LVS_BODY.format(
            net="eth0",
            main_vip=main_vip,
            read_vip=read_vip,
            port=get_postgresql_config_port(meta, spec, patch, status, logger),
            real_main_servers="\n".join(real_main_servers),
            real_read_servers="\n".join(real_read_servers))

        conns = connections(spec, meta, patch,
                            get_field(POSTGRESQL, READWRITEINSTANCE), False,
                            None, logger, None, status, False)
        for conn in conns.get_conns():
            machine_sftp_put(conn.get_machine().get_sftp(), lvs_conf,
                             KEEPALIVED_CONF)
            machine_exec_command(
                conn.get_machine().get_ssh(),
                LVS_SET_NET.format(main_vip=main_vip, read_vip=read_vip))
            machine_exec_command(conn.get_machine().get_ssh(),
                                 START_KEEPALIVED)
        conns.free_conns()


async def create_postgresql_cluster(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:

    logger.info("creating postgresql cluster")
    set_password(patch, status)

    # create services
    create_services(meta, spec, patch, status, logger)

    # create autofailover
    set_create_cluster(patch, CLUSTER_CREATE_ADD_FAILOVER)
    create_autofailover(meta, spec, patch, status, logger,
                        get_autofailover_labels(meta))
    conns = connections(spec, meta, patch, get_field(AUTOFAILOVER), False,
                        None, logger, None, status, False)
    waiting_postgresql_ready(conns, logger)
    conns.free_conns()

    # create postgresql & readwrite node
    set_create_cluster(patch, CLUSTER_CREATE_ADD_READWRITE)
    create_postgresql_readwrite(meta, spec, patch, status, logger,
                                get_readwrite_labels(meta), 0, True)
    #conns = connections(spec, meta, patch,
    #                    get_field(POSTGRESQL, READWRITEINSTANCE), False, None,
    #                    logger, None, status, False)
    #create_users(meta, spec, patch, status, logger, conns)
    #conns.free_conns()

    # create postgresql & readonly node
    set_create_cluster(patch, CLUSTER_CREATE_ADD_READONLY)
    create_postgresql_readonly(meta, spec, patch, status, logger,
                               get_readonly_labels(meta), 0)

    # finish
    set_create_cluster(patch, CLUSTER_CREATE_FINISH)


async def create_cluster(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    set_create_cluster(patch, CLUSTER_CREATE_BEGIN)

    autofailover_machines = spec.get(AUTOFAILOVER).get(MACHINES)
    readwrite_machines = spec.get(POSTGRESQL).get(READWRITEINSTANCE).get(
        MACHINES)
    readwrite_replicas = spec.get(POSTGRESQL).get(READWRITEINSTANCE).get(
        REPLICAS)
    readonly_machines = spec.get(POSTGRESQL).get(READONLYINSTANCE).get(
        MACHINES)
    readonly_replicas = spec.get(POSTGRESQL).get(READONLYINSTANCE).get(
        REPLICAS)

    if autofailover_machines != None or readwrite_machines != None or readonly_machines != None:
        logger.info("running on machines mode")
        if autofailover_machines == None:
            raise kopf.PermanentError("autofailover machines not set")
        if readwrite_machines == None:
            raise kopf.PermanentError("readwrite machines not set")
        if len(autofailover_machines) != 1:
            raise kopf.PermanentError("autofailover only support one machine.")
        if len(readwrite_machines) < 1:
            raise kopf.PermanentError(
                "readwrite machines must set at lease one machine")

    if spec[ACTION] == ACTION_STOP:
        raise kopf.PermanentError("can't set stop at init cluster.")
    if readwrite_replicas < 1:
        raise kopf.PermanentError("readwrite replicas must set at lease one")
    if readonly_replicas < 0:
        raise kopf.PermanentError("readonly replicas must large than zero")

    logger.info("parameters are correct")
    await create_postgresql_cluster(meta, spec, patch, status, logger)


async def delete_cluster(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:

    await delete_postgresql_cluster(meta, spec, patch, status, logger)


def delete_pvc(logger: logging.Logger, name: str, namespace: str) -> None:
    core_v1_api = client.CoreV1Api()

    logger.info(f"delete pvc {name}")
    core_v1_api.delete_namespaced_persistent_volume_claim(name, namespace)


def delete_storage(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    conn: InstanceConnection,
) -> None:

    if conn.get_k8s() != None:
        delete_pvc(logger, get_pvc_name(conn.get_k8s().get_podname()),
                   conn.get_k8s().get_namespace())
    if conn.get_machine() != None:
        machine_postgresql_down(conn, logger)
        logger.info("delete machine disk " + conn.get_machine().get_host())
        postgresql_action(meta, spec, patch, status, logger, conn, False)
        if conn.get_machine().get_role() == AUTOFAILOVER:
            machine_data_path = operator_config.DATA_PATH_AUTOFAILOVER
        if conn.get_machine().get_role() == POSTGRESQL:
            machine_data_path = operator_config.DATA_PATH_POSTGRESQL
        machine_exec_command(conn.get_machine().get_ssh(),
                             "rm -rf " + machine_data_path)


def delete_storages(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:

    conns = connections(spec, meta, patch, get_field(AUTOFAILOVER), False,
                        None, logger, None, status, False)
    for conn in conns.get_conns():
        delete_storage(meta, spec, patch, status, logger, conn)
    conns.free_conns()

    conns = connections(spec, meta, patch,
                        get_field(POSTGRESQL, READWRITEINSTANCE), False, None,
                        logger, None, status, False)
    for conn in conns.get_conns():
        delete_storage(meta, spec, patch, status, logger, conn)
    conns.free_conns()

    conns = connections(spec, meta, patch,
                        get_field(POSTGRESQL, READONLYINSTANCE), False, None,
                        logger, None, status, False)
    for conn in conns.get_conns():
        delete_storage(meta, spec, patch, status, logger, conn)
    conns.free_conns()


async def delete_postgresql_cluster(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    if spec[DELETE_PVC]:
        delete_storages(meta, spec, patch, status, logger)


def patch_statefulset_replicas(replicas: int) -> TypedDict:
    return {"spec": {"replicas": replicas}}


def patch_statefulset_restartPolicy(policy: str) -> TypedDict:
    # Always Never
    return {"spec": {"template": {"spec": {"restartPolicy": policy}}}}


def patch_role_body(role: str) -> TypedDict:
    role_body = {"metadata": {"labels": {"role": role}}}
    return role_body


def get_conn_role(conn: InstanceConnection) -> str:
    if conn.get_k8s() != None:
        return conn.get_k8s().get_role()
    if conn.get_machine() != None:
        return conn.get_machine().get_role()


def correct_user_password(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    conn: InstanceConnection,
) -> None:
    PASSWORD_FAILED_MESSAGEd = "password authentication failed for user"

    if get_conn_role(conn) == AUTOFAILOVER:
        port = 55555
        user = AUTOCTL_NODE
        password = status.get(AUTOCTL_NODE)
    elif get_conn_role(conn) == POSTGRESQL:
        port = get_postgresql_config_port(meta, spec, patch, status, logger)
        user = PGAUTOFAILOVER_REPLICATOR
        password = status.get(PGAUTOFAILOVER_REPLICATOR)

    if password == None:
        return

    cmd = [
        "bash", "-c",
        '''"PGPASSWORD=%s psql -h %s -d postgres -U %s -p %d -t -c 'select 1'"'''
        % (password, get_connhost(conn), user, port)
    ]
    logger.info(f"check password with cmd {cmd} ")
    output = exec_command(conn, cmd, logger, interrupt=False).strip()
    if output.find(PASSWORD_FAILED_MESSAGEd) != -1:
        logger.info(f"password error: {output}")
        change_user_password(conn, user, password, logger)


async def correct_postgresql_password(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    autofailover_conns = connections(spec, meta, patch,
                                     get_field(AUTOFAILOVER), False, None,
                                     logger, None, status, False)
    for conn in autofailover_conns.get_conns():
        correct_user_password(meta, spec, patch, status, logger, conn)
    autofailover_conns.free_conns()

    readwrite_conns = connections(spec, meta, patch,
                                  get_field(POSTGRESQL, READWRITEINSTANCE),
                                  False, None, logger, None, status, False)
    conn = get_primary_conn(readwrite_conns, 0, logger)
    correct_user_password(meta, spec, patch, status, logger, conn)
    readwrite_conns.free_conns()


async def correct_keepalived(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    readwrite_conns = connections(spec, meta, patch,
                                  get_field(POSTGRESQL, READWRITEINSTANCE),
                                  False, None, logger, None, status, False)
    for conn in readwrite_conns.get_conns():
        output = machine_exec_command(conn.get_machine().get_ssh(),
                                      STATUS_KEEPALIVED,
                                      interrupt=False)
        if output.find("Active: active (running)") == -1:
            delete_services(meta, spec, patch, status, logger)
            create_services(meta, spec, patch, status, logger)
            break
    readwrite_conns.free_conns()


async def correct_postgresql_role(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    core_v1_api = client.CoreV1Api()

    # we don't have pod on machine.
    try:
        pods = core_v1_api.list_namespaced_pod(meta['namespace'],
                                               watch=False,
                                               label_selector=dict_to_str(
                                                   get_readwrite_labels(meta)))
    except Exception as e:
        raise kopf.TemporaryError(
            "Exception when calling list_pod_for_all_namespaces: %s\n" % e)

    for pod in pods.items:
        cmd = ["pgtools", "-w", "0", "-q", "'show transaction_read_only'"]
        output = pod_exec_command(pod.metadata.name, pod.metadata.namespace,
                                  cmd, logger, False)
        role = pod.metadata.labels.get(LABEL_ROLE)

        patch_body = None
        if output == "off" and role != LABEL_ROLE_PRIMARY:
            logger.info("set pod " + pod.metadata.name + " to primary")
            patch_body = patch_role_body(LABEL_ROLE_PRIMARY)
        if output == "on" and role != LABEL_ROLE_STANDBY:
            logger.info("set pod " + pod.metadata.name + " to standby")
            patch_body = patch_role_body(LABEL_ROLE_STANDBY)

        if patch_body != None:
            try:
                core_v1_api.patch_namespaced_pod(pod.metadata.name,
                                                 pod.metadata.namespace,
                                                 patch_body)
            except Exception as e:
                logger.error(
                    "Exception when calling AppsV1Api->patch_namespaced_pod: %s\n"
                    % e)


async def timer_cluster(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:

    await correct_postgresql_role(meta, spec, patch, status, logger)
    await correct_postgresql_password(meta, spec, patch, status, logger)
    await correct_keepalived(meta, spec, patch, status, logger)


def update_streaming(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    AC: str,
    FIELD: Tuple,
    OLD: Any,
    NEW: Any,
) -> None:
    if FIELD == DIFF_FIELD_STREAMING:
        if AC != DIFF_CHANGE:
            logger.error(DIFF_FIELD_STREAMING + " only support " + DIFF_CHANGE)
        else:
            #pg_autoctl set node replication-quorum 0 --pgdata /var/lib/postgresql/data/pg_data/
            if NEW == STREAMING_SYNC:
                quorum = 1
            elif NEW == STREAMING_ASYNC:
                quorum = 0
            cmd = [
                "pgtools", "-S",
                "'node replication-quorum " + str(quorum) + "'"
            ]
            conns = connections(spec, meta, patch,
                                get_field(POSTGRESQL, READONLYINSTANCE), False,
                                None, logger, None, status, False).get_conns()
            for conn in conns:
                output = exec_command(conn, cmd, logger, interrupt=False)
                if output.find(SUCCESS) == -1:
                    logger.error(
                        f"set readonly streaming failed {cmd}  {output}")
            conns.free_conns()


def postgresql_action(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    conn: InstanceConnection,
    start: bool,
) -> None:
    if start == False:
        cmd = ["pgtools", "-R"]
        logger.info(f"stop postgresql with cmd {cmd} ")
        output = exec_command(conn, cmd, logger, interrupt=False)
        if output.find(STOP_FAILED_MESSAGE) != -1:
            logger.warning(f"can't stop postgresql. {output}, force stop it")
    if conn.get_k8s() != None:
        if start:
            replicas = STATEFULSET_REPLICAS
        else:
            replicas = 0

        try:
            apps_v1_api = client.AppsV1Api()

            name = pod_name_get_statefulset_name(conn.get_k8s().get_podname())
            namespace = conn.get_k8s().get_namespace()

            logger.info("set statefulset " + name + " replicas to " +
                        str(replicas))
            apps_v1_api.patch_namespaced_stateful_set(
                name, namespace, patch_statefulset_replicas(replicas))
        except Exception as e:
            logger.error(
                "Exception when calling AppsV1Api->patch_namespaced_stateful_set: %s\n"
                % e)
    if conn.get_machine() != None:
        if start:
            cmd = "start"
        else:
            cmd = "stop"

        logger.info("host " + conn.get_machine().get_host() + " postgresql " +
                    cmd)
        if conn.get_machine().get_role() == AUTOFAILOVER:
            machine_data_path = operator_config.DATA_PATH_AUTOFAILOVER
        if conn.get_machine().get_role() == POSTGRESQL:
            machine_data_path = operator_config.DATA_PATH_POSTGRESQL
        machine_exec_command(
            conn.get_machine().get_ssh(),
            "cd " + os.path.join(machine_data_path, DOCKER_COMPOSE_DIR) +
            "; docker-compose " + cmd)


def update_action(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    AC: str,
    FIELD: Tuple,
    OLD: Any,
    NEW: Any,
) -> None:
    if FIELD == DIFF_FIELD_ACTION:
        if AC != DIFF_CHANGE:
            #raise kopf.TemporaryError("Exception when calling list_pod_for_all_namespaces: %s\n" % e)
            logger.error(
                str(DIFF_FIELD_ACTION) + " only support " + DIFF_CHANGE)
        else:
            conns = []
            # stop autofailover first. protect readwrite switch failover.
            # start autofailover first, postgresql will connect it
            autofailover_conns = connections(spec, meta, patch,
                                             get_field(AUTOFAILOVER), False,
                                             None, logger, None, status, False)
            conns += autofailover_conns.get_conns()
            readwrite_conns = connections(
                spec, meta, patch, get_field(POSTGRESQL, READWRITEINSTANCE),
                False, None, logger, None, status, False)
            conns += readwrite_conns.get_conns()
            readonly_conns = connections(
                spec, meta, patch, get_field(POSTGRESQL, READONLYINSTANCE),
                False, None, logger, None, status, False)
            conns += readonly_conns.get_conns()
            if NEW == ACTION_STOP:
                start = False
            elif NEW == ACTION_START:
                start = True
            for conn in conns:
                postgresql_action(meta, spec, patch, status, logger, conn,
                                  start)
            autofailover_conns.free_conns()
            readwrite_conns.free_conns()
            readonly_conns.free_conns()


def update_podspec_volume(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    AC: str,
    FIELD: Tuple,
    OLD: Any,
    NEW: Any,
) -> None:

    if FIELD[0:len(DIFF_FIELD_AUTOFAILOVER_PODSPEC
                   )] == DIFF_FIELD_AUTOFAILOVER_PODSPEC or FIELD[
                       0:len(DIFF_FIELD_AUTOFAILOVER_VOLUME
                             )] == DIFF_FIELD_AUTOFAILOVER_VOLUME:
        autofailover_machines = spec.get(AUTOFAILOVER).get(MACHINES)
        if autofailover_machines != None:
            delete_autofailover(meta, spec, patch, status, logger,
                                get_field(AUTOFAILOVER), autofailover_machines,
                                None, False)
        else:
            delete_autofailover(meta, spec, patch, status, logger,
                                get_field(AUTOFAILOVER), None, [0, 1], False)
        create_autofailover(meta, spec, patch, status, logger,
                            get_autofailover_labels(meta))
    if FIELD[0:len(DIFF_FIELD_READWRITE_PODSPEC
                   )] == DIFF_FIELD_READWRITE_PODSPEC or FIELD[
                       0:len(DIFF_FIELD_READWRITE_VOLUME
                             )] == DIFF_FIELD_READWRITE_VOLUME:
        readwrite_machines = spec.get(POSTGRESQL).get(READWRITEINSTANCE).get(
            MACHINES)
        if readwrite_machines != None:
            delete_postgresql_readwrite(
                meta, spec, patch, status, logger,
                get_field(POSTGRESQL, READWRITEINSTANCE), readwrite_machines,
                None, False)
        else:
            delete_postgresql_readwrite(
                meta, spec, patch, status, logger,
                get_field(POSTGRESQL, READWRITEINSTANCE), None,
                [0, spec[POSTGRESQL][READWRITEINSTANCE][REPLICAS]], False)
        create_postgresql_readwrite(meta, spec, patch, status, logger,
                                    get_readwrite_labels(meta), 0, False)
    if FIELD[0:len(DIFF_FIELD_READONLY_PODSPEC
                   )] == DIFF_FIELD_READONLY_PODSPEC or FIELD[
                       0:len(DIFF_FIELD_READONLY_VOLUME
                             )] == DIFF_FIELD_READONLY_VOLUME:
        readonly_machines = spec.get(POSTGRESQL).get(READONLYINSTANCE).get(
            MACHINES)
        if readonly_machines != None:
            delete_postgresql_readonly(meta, spec, patch, status, logger,
                                       get_field(POSTGRESQL, READONLYINSTANCE),
                                       readonly_machines, None, False)
        else:
            delete_postgresql_readonly(
                meta, spec, patch, status, logger,
                get_field(POSTGRESQL, READONLYINSTANCE), None,
                [0, spec[POSTGRESQL][READONLYINSTANCE][REPLICAS]], False)
        create_postgresql_readonly(meta, spec, patch, status, logger,
                                   get_readonly_labels(meta), 0)


def update_replicas(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    AC: str,
    FIELD: Tuple,
    OLD: Any,
    NEW: Any,
) -> None:
    if FIELD == DIFF_FIELD_READWRITE_REPLICAS:
        if AC != DIFF_CHANGE:
            #raise kopf.TemporaryError("Exception when calling list_pod_for_all_namespaces: %s\n" % e)
            logger.error(
                str(DIFF_FIELD_ACTION) + " only support " + DIFF_CHANGE)
        else:
            if NEW > OLD:
                create_postgresql_readwrite(meta, spec, patch, status, logger,
                                            get_readwrite_labels(meta), OLD,
                                            False)
            else:
                delete_postgresql_readwrite(
                    meta, spec, patch, status, logger,
                    get_field(POSTGRESQL, READWRITEINSTANCE), None, [NEW, OLD],
                    True)

    if FIELD == DIFF_FIELD_READWRITE_MACHINES:
        if AC != DIFF_CHANGE:
            #raise kopf.TemporaryError("Exception when calling list_pod_for_all_namespaces: %s\n" % e)
            logger.error(
                str(DIFF_FIELD_ACTION) + " only support " + DIFF_CHANGE)
        else:
            if len(NEW) > len(OLD):
                create_postgresql_readwrite(meta, spec, patch, status, logger,
                                            get_readwrite_labels(meta),
                                            len(OLD), False)
            else:
                delete_postgresql_readwrite(
                    meta, spec, patch, status, logger,
                    get_field(POSTGRESQL, READWRITEINSTANCE),
                    [i for i in OLD if i not in NEW], None, True)
        delete_services(meta, spec, patch, status, logger)
        create_services(meta, spec, patch, status, logger)

    if FIELD == DIFF_FIELD_READONLY_REPLICAS:
        if NEW > OLD:
            create_postgresql_readonly(meta, spec, patch, status, logger,
                                       get_readonly_labels(meta), OLD)
        else:
            delete_postgresql_readonly(meta, spec, patch, status, logger,
                                       get_field(POSTGRESQL, READONLYINSTANCE),
                                       None, [NEW, OLD], True)

    if FIELD == DIFF_FIELD_READONLY_MACHINES:
        if OLD == None or (NEW != None and len(NEW) > len(OLD)):
            if OLD == None:
                begin = 0
            else:
                begin = len(OLD)
            create_postgresql_readonly(meta, spec, patch, status, logger,
                                       get_readonly_labels(meta), begin)
        else:
            if NEW == None:
                delete_machine = OLD
            else:
                delete_machine = [i for i in OLD if i not in NEW]
            delete_postgresql_readonly(meta, spec, patch, status, logger,
                                       get_field(POSTGRESQL, READONLYINSTANCE),
                                       delete_machine, None, True)
        delete_services(meta, spec, patch, status, logger)
        create_services(meta, spec, patch, status, logger)


def delete_services(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    autofailover_machines = spec.get(AUTOFAILOVER).get(MACHINES)
    # k8s mode
    if autofailover_machines == None:
        core_v1_api = client.CoreV1Api()
        try:
            api_response = core_v1_api.list_service_for_all_namespaces(
                label_selector=dict_to_str(get_service_labels(meta)),
                watch=False)
            for service in api_response.items:
                try:
                    logger.info("delete service " + service.metadata.name)
                    delete_response = core_v1_api.delete_namespaced_service(
                        service.metadata.name, service.metadata.namespace)
                except Exception as e:
                    logger.error(
                        "Exception when calling CoreV1Api->delete_namespaced_service: %s\n"
                        % e)
        except Exception as e:
            logger.error(
                "Exception when calling CoreV1Api->list_service_for_all_namespaces: %s\n"
                % e)
    else:
        conns = connections(spec, meta, patch,
                            get_field(POSTGRESQL, READWRITEINSTANCE), False,
                            None, logger, None, status, False)
        for conn in conns.get_conns():
            machine_exec_command(conn.get_machine().get_ssh(),
                                 "rm -rf " + KEEPALIVED_CONF)
            machine_exec_command(conn.get_machine().get_ssh(), STOP_KEEPALIVED)
        conns.free_conns()


def update_service(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    AC: str,
    FIELD: Tuple,
    OLD: Any,
    NEW: Any,
) -> None:
    if FIELD == DIFF_FIELD_SERVICE:
        delete_services(meta, spec, patch, status, logger)
        create_services(meta, spec, patch, status, logger)


def update_configs(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    AC: str,
    FIELD: Tuple,
    OLD: Any,
    NEW: Any,
) -> None:
    conns = []
    cmd = ["pgtools", "-c"]
    restart_postgresql = False
    port_change = False
    autofailover = False

    if FIELD == DIFF_FIELD_AUTOFAILOVER_CONFIGS:
        autofailover_conns = connections(spec, meta, patch,
                                         get_field(AUTOFAILOVER), False, None,
                                         logger, None, status, False)
        conns += autofailover_conns.get_conns()
        autofailover = True
    elif FIELD == DIFF_FIELD_POSTGRESQL_CONFIGS:
        readwrite_conns = connections(spec, meta, patch,
                                      get_field(POSTGRESQL, READWRITEINSTANCE),
                                      False, None, logger, None, status, False)
        conns += readwrite_conns.get_conns()

        readonly_conns = connections(spec, meta, patch,
                                     get_field(POSTGRESQL, READONLYINSTANCE),
                                     False, None, logger, None, status, False)
        conns += readonly_conns.get_conns()

    if len(conns) != 0:
        for i, config in enumerate(NEW):
            name = config.split("=")[0].strip()
            value = config[config.find("=") + 1:].strip()
            config = name + '="' + value + '"'
            if autofailover == True and name == 'port':
                continue
            if name in PG_CONFIG_IGONRE:
                continue
            if name in PG_CONFIG_RESTART:
                for oldi, oldconfig in enumerate(OLD):
                    oldname = oldconfig.split("=")[0].strip()
                    oldvalue = oldconfig[oldconfig.find("=") + 1:].strip()
                    oldconfig = oldname + "=" + oldvalue
                    if name == oldname and value != oldvalue:
                        logger.info(f" {name} is restart parameter ")
                        restart_postgresql = True
                        if name == 'port':
                            port_change = True
            cmd.append('-e')
            cmd.append(PG_CONFIG_PREFIX + config)

        if port_change == True:
            cmd.append('-d')
        elif restart_postgresql == True:
            cmd.append('-r')

        logger.info("update configs(" + str(cmd) + ")")
        for conn in conns:
            if get_primary_host(
                    meta, spec, patch, status,
                    logger) == get_connhost(conn) and int(
                        spec[POSTGRESQL][READWRITEINSTANCE][REPLICAS]) > 1:
                autofailover_switchover(meta, spec, patch, status, logger)

            output = exec_command(conn, cmd, logger, interrupt=False)
            if output.find(SUCCESS) == -1:
                logger.error(f"update configs {cmd} failed. {output}")

            #if port_change == True or restart_postgresql == True:
            if port_change == True:
                logger.info(f"wait readwrite instance update finish")
                waiting_cluster_correct_status(meta, spec, patch, status,
                                               logger)

        if port_change == True:
            delete_services(meta, spec, patch, status, logger)
            create_services(meta, spec, patch, status, logger)
    if FIELD == DIFF_FIELD_AUTOFAILOVER_CONFIGS:
        autofailover_conns.free_conns()
    elif FIELD == DIFF_FIELD_POSTGRESQL_CONFIGS:
        readwrite_conns.free_conns()
        readonly_conns.free_conns()


def update_hbas(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    AC: str,
    FIELD: Tuple,
    OLD: Any,
    NEW: Any,
) -> None:
    conns = []
    cmd = ["pgtools", "-H"]

    if FIELD == DIFF_FIELD_AUTOFAILOVER_HBAS:
        autofailover_conns = connections(spec, meta, patch,
                                         get_field(AUTOFAILOVER), False, None,
                                         logger, None, status, False)
        conns += autofailover_conns.get_conns()
        hbas = spec[AUTOFAILOVER][HBAS]
    elif FIELD == DIFF_FIELD_POSTGRESQL_HBAS:
        readwrite_conns = connections(spec, meta, patch,
                                      get_field(POSTGRESQL, READWRITEINSTANCE),
                                      False, None, logger, None, status, False)
        conns += readwrite_conns.get_conns()

        readonly_conns = connections(spec, meta, patch,
                                     get_field(POSTGRESQL, READONLYINSTANCE),
                                     False, None, logger, None, status, False)
        conns += readonly_conns.get_conns()
        hbas = spec[POSTGRESQL][HBAS]

    if len(conns) != 0:
        for i, hba in enumerate(hbas):
            env_name = PG_HBA_PREFIX + str(i)
            env_value = hba
            cmd.append("-e")
            cmd.append(env_name + "='" + env_value + "'")

        logger.info("update hbas(" + str(cmd) + ")")
        for conn in conns:
            output = exec_command(conn, cmd, logger, interrupt=False)
            if output.find(SUCCESS) == -1:
                logger.error(f"update hbas {cmd} failed. {output}")
    if FIELD == DIFF_FIELD_AUTOFAILOVER_HBAS:
        autofailover_conns.free_conns()
    elif FIELD == DIFF_FIELD_POSTGRESQL_HBAS:
        readwrite_conns.free_conns()
        readonly_conns.free_conns()


def update_users(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    AC: str,
    FIELD: Tuple,
    OLD: Any,
    NEW: Any,
) -> None:
    if FIELD == DIFF_FIELD_POSTGRESQL_USERS or FIELD == DIFF_FIELD_POSTGRESQL_USERS_ADMIN or FIELD == DIFF_FIELD_POSTGRESQL_USERS_NORMAL:
        conns = connections(spec, meta, patch,
                            get_field(POSTGRESQL, READWRITEINSTANCE), False,
                            None, logger, None, status, False)
        conn = get_primary_conn(conns, 0, logger)

    if AC == DIFF_ADD:
        if FIELD == DIFF_FIELD_POSTGRESQL_USERS:
            create_users(meta, spec, patch, status, logger, conns)
        if FIELD == DIFF_FIELD_POSTGRESQL_USERS_ADMIN:
            create_users_admin(meta, spec, patch, status, logger, conns)
        if FIELD == DIFF_FIELD_POSTGRESQL_USERS_NORMAL:
            create_users_normal(meta, spec, patch, status, logger, conns)
    if AC == DIFF_REMOVE:
        users = []
        if FIELD == DIFF_FIELD_POSTGRESQL_USERS:
            if OLD.get(ADMIN_USER) != None:
                users += OLD[ADMIN_USER]
            if OLD.get(NORMAL_USER) != None:
                users += OLD[NORMAL_USER]
        if FIELD == DIFF_FIELD_POSTGRESQL_USERS_ADMIN:
            users += OLD
        if FIELD == DIFF_FIELD_POSTGRESQL_USERS_NORMAL:
            users += OLD

        for user in users:
            drop_one_user(conn, user[USER_NAME], logger)

    if AC == DIFF_CHANGE:

        def local_change_user_password(OS: List, NS: List):
            for o in OS:
                for n in NS:
                    if o[USER_NAME] == n[USER_NAME]:
                        if o[USER_PASSWORD] != n[USER_PASSWORD]:
                            change_user_password(conn, n[USER_NAME],
                                                 n[USER_PASSWORD], logger)

        def local_drop_user(OS: List, NS: List):
            for o in OS:
                found = False
                for n in NS:
                    if o[USER_NAME] == n[USER_NAME]:
                        found = True
                if found == False:
                    drop_one_user(conn, o[USER_NAME], logger)

        def local_create_user(OS: List, NS: List, admin: bool):
            for n in NS:
                found = False
                for o in OS:
                    if o[USER_NAME] == n[USER_NAME]:
                        found = True
                if found == False:
                    create_one_user(conn, n[USER_NAME], n[USER_PASSWORD],
                                    admin, logger)

        if FIELD == DIFF_FIELD_POSTGRESQL_USERS:
            logger.error("UNknow diff action")
        if FIELD == DIFF_FIELD_POSTGRESQL_USERS_ADMIN:
            local_change_user_password(OLD, NEW)
            local_drop_user(OLD, NEW)
            local_create_user(OLD, NEW, True)
        if FIELD == DIFF_FIELD_POSTGRESQL_USERS_NORMAL:
            local_change_user_password(OLD, NEW)
            local_drop_user(OLD, NEW)
            local_create_user(OLD, NEW, False)

    if FIELD == DIFF_FIELD_POSTGRESQL_USERS or FIELD == DIFF_FIELD_POSTGRESQL_USERS_ADMIN or FIELD == DIFF_FIELD_POSTGRESQL_USERS_NORMAL:
        conns.free_conns()


# kubectl patch pg lzzhang --patch '{"spec": {"action": "stop"}}' --type=merge
async def update_cluster(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
    diffs: kopf.Diff,
) -> None:
    for diff in diffs:
        AC = diff[0]
        FIELD = diff[1]
        OLD = diff[2]
        NEW = diff[3]

        logger.info(diff)
        update_replicas(meta, spec, patch, status, logger, AC, FIELD, OLD, NEW)
        update_action(meta, spec, patch, status, logger, AC, FIELD, OLD, NEW)
        update_service(meta, spec, patch, status, logger, AC, FIELD, OLD, NEW)
        update_hbas(meta, spec, patch, status, logger, AC, FIELD, OLD, NEW)
        update_users(meta, spec, patch, status, logger, AC, FIELD, OLD, NEW)
        update_streaming(meta, spec, patch, status, logger, AC, FIELD, OLD,
                         NEW)
        update_podspec_volume(meta, spec, patch, status, logger, AC, FIELD,
                              OLD, NEW)
        update_configs(meta, spec, patch, status, logger, AC, FIELD, OLD, NEW)