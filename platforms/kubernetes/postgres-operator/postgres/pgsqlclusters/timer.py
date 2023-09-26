import kopf
import logging
import copy
import time

from kubernetes import client

import pgsqlclusters.create as pgsql_create
import pgsqlclusters.update as pgsql_update
import pgsqlclusters.delete as pgsql_delete
import pgsqlclusters.utiles as pgsql_util
import pgsqlbackups.utils as backup_util
from pgsqlcommons.constants import *
from pgsqlcommons.typed import LabelType, InstanceConnection, InstanceConnections, TypedDict, InstanceConnectionMachine, InstanceConnectionK8S, Tuple, Any, List
from pgsqlclusters.utiles import get_conn_role, get_connhost, exec_command, connections, get_field, get_primary_conn, \
    machine_exec_command, get_readwrite_labels, dict_to_str, pod_exec_command, patch_role_body, \
    get_postgresql_config_port, set_cluster_status, to_int, create_ssl_key


def current_time() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def timer_cluster(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    # set the timer run time
    patch.status[CLUSTER_STATUS_TIMER] = current_time()
    #set_cluster_status(meta, CLUSTER_STATUS_TIMER, current_time(), logger)

    correct_postgresql_status_lsn(meta, spec, patch, status, logger)

    if pgsql_util.in_disaster_backup(meta, spec, patch, status,
                                     logger) == True:
        return

    correct_postgresql_role(meta, spec, patch, status, logger)
    correct_keepalived(meta, spec, patch, status, logger)
    correct_postgresql_password(meta, spec, patch, status, logger)
    correct_backup_status(meta, spec, patch, status, logger)
    correct_s3_profile(meta, spec, patch, status, logger)

    # last executed
    correct_ssl_server_crt(meta, spec, patch, status, logger)

    from .test import test
    test(meta, spec, patch, status, logger)


def correct_ssl_server_crt(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    if status.get(CLUSTER_STATUS_SERVER_CRT) == None:
        create_ssl_key(meta, spec, patch, status, logger)


def correct_postgresql_status_lsn(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    readwrite_conns = connections(spec, meta, patch,
                                  get_field(POSTGRESQL, READWRITEINSTANCE),
                                  False, None, logger, None, status, False)
    conn = readwrite_conns.get_conns()[0]

    local_str = ''
    if pgsql_util.in_disaster_backup(meta, spec, patch, status,
                                     logger) == True:
        local_str = '--local'

    pg_disaster_status_dict = {}
    if status.get(CLUSTER_STATUS_DISASTER_BACKUP_STATUS) == None:
        pg_disaster_status_old = {}
    else:
        pg_disaster_status_old = copy.deepcopy(
            status[CLUSTER_STATUS_DISASTER_BACKUP_STATUS])

    for i in range(1, 10):
        pg_disaster_status_cmd = [
            'pg_autoctl', 'show', 'state', local_str, '--pgdata',
            PG_DATABASE_DIR, '|', 'grep', AUTOCTL_DISASTER_NAME, '|', 'cut',
            '-d', "'|'", '-f', '3,4,6', '|', 'tr', '-d', "' '", '|', 'sed',
            '-n', f'{i}p'
        ]
        pg_disaster_status = exec_command(conn,
                                          pg_disaster_status_cmd,
                                          logger,
                                          interrupt=False)
        if pg_disaster_status.find(
                'Failed to connect to') == -1 and pg_disaster_status != FAILED:
            if len(pg_disaster_status) > 10:
                pg_disaster_status = [
                    s.strip() for s in pg_disaster_status.split('|')
                ]
                pg_disaster_status_dict[pg_disaster_status[0]] = {
                    "LSN": pg_disaster_status[1],
                    "state": pg_disaster_status[2]
                }
            else:
                break
        else:
            pg_disaster_status_dict = {}
            break

    # cleanup expired data
    if type(pg_disaster_status_old) == type({}):
        for old_key in pg_disaster_status_old.keys():
            if old_key not in pg_disaster_status_dict.keys():
                pg_disaster_status_dict = ''  # {} empty dict can't cleanup expired record.
                break

    patch.status[
        CLUSTER_STATUS_DISASTER_BACKUP_STATUS] = pg_disaster_status_dict
    readwrite_conns.free_conns()


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
        port = AUTO_FAILOVER_PORT
        user = AUTOCTL_NODE
        password = patch.status.get(AUTOCTL_NODE)
        if password == None:
            password = status.get(AUTOCTL_NODE)
    elif get_conn_role(conn) == POSTGRESQL:
        port = get_postgresql_config_port(meta, spec, patch, status, logger)
        user = PGAUTOFAILOVER_REPLICATOR
        password = patch.status.get(PGAUTOFAILOVER_REPLICATOR)
        if password == None:
            password = status.get(PGAUTOFAILOVER_REPLICATOR)

    if password == None:
        return

    cmd = [
        "bash", "-c",
        '''"PGPASSWORD=%s psql -h %s -d postgres -U %s -p %d -t -c 'select 1'"'''
        % (password, get_connhost(conn), user, port)
    ]
    #logger.info(f"check password with cmd {cmd} ")
    output = exec_command(conn, cmd, logger, interrupt=False).strip()
    if output.find(PASSWORD_FAILED_MESSAGEd) != -1:
        logger.error(f"password error: {output}")
        pgsql_update.change_user_password(conn, user, password, logger)


def correct_postgresql_password(
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
    conn = get_primary_conn(readwrite_conns, 0, logger, interrupt=False)
    if conn == None:
        logger.error(
            f"can't correct readwrite password. because get primary conn failed"
        )
    else:
        correct_user_password(meta, spec, patch, status, logger, conn)
    readwrite_conns.free_conns()


def correct_keepalived(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    main_vip = ""
    read_vip = ""
    autofailover_conns = connections(spec, meta, patch,
                                     get_field(AUTOFAILOVER), False, None,
                                     logger, None, status, False)
    if autofailover_conns.get_conns()[0].get_machine() == None:
        autofailover_conns.free_conns()
        return

    conns = connections(spec, meta, patch,
                        get_field(POSTGRESQL, READWRITEINSTANCE), False, None,
                        logger, None, status, False)
    readonly_conns = connections(spec, meta, patch,
                                 get_field(POSTGRESQL, READONLYINSTANCE),
                                 False, None, logger, None, status, False)
    # keepalived is stop
    for conn in (conns.get_conns() + readonly_conns.get_conns()):
        for service in spec[SERVICES]:
            if service[SELECTOR] == SERVICE_PRIMARY:
                main_vip = service[VIP]
            elif service[SELECTOR] == SERVICE_READONLY:
                read_vip = service[VIP]
            elif service[SELECTOR] == SERVICE_STANDBY_READONLY:
                read_vip = service[VIP]
            else:
                logger.error(f"unsupport service {service}")

        output = machine_exec_command(conn.get_machine().get_ssh(),
                                      GET_INET_CMD,
                                      interrupt=False)
        if len(main_vip) > 0 and len(read_vip) > 0 and (
                output.find(main_vip) == -1 or output.find(read_vip) == -1):
            machine_exec_command(
                conn.get_machine().get_ssh(),
                LVS_SET_NET.format(main_vip=main_vip, read_vip=read_vip))

        output = machine_exec_command(conn.get_machine().get_ssh(),
                                      STATUS_KEEPALIVED,
                                      interrupt=False)
        if output.find("Active: active (running)") == -1:
            logger.warning("keepalived is not running. recreate the services")
            pgsql_delete.delete_services(meta, spec, patch, status, logger)
            pgsql_create.create_services(meta, spec, patch, status, logger)
            break
    # can't access keepalived vip
    accept = False
    port = get_postgresql_config_port(meta, spec, patch, status, logger)
    for t in [1, 3, 6]:  # timeout
        cmd = [
            "pg_isready", "-U", "postgres", "-t",
            str(t), "-h", main_vip, "-p",
            str(port)
        ]
        output = exec_command(autofailover_conns.get_conns()[0],
                              cmd,
                              logger,
                              interrupt=False)
        if output.find("accepting connections") != -1:
            accept = True
            break
    if accept == False:
        logger.warning("can't access keepalived. restart keepalived")
        for conn in (conns.get_conns() + readonly_conns.get_conns()):
            if conn.get_machine() == None:
                break
            machine_exec_command(conn.get_machine().get_ssh(),
                                 START_KEEPALIVED,
                                 interrupt=False)
    conns.free_conns()
    readonly_conns.free_conns()
    autofailover_conns.free_conns()


def correct_postgresql_role(
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


def correct_backup_status(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    if backup_util.get_backup_mode(
            meta, spec, patch, status,
            logger) == BACKUP_MODE_S3_MANUAL or backup_util.get_backup_mode(
                meta, spec, patch, status, logger) == BACKUP_MODE_S3_CRON:
        if spec[SPEC_BACKUPCLUSTER][SPEC_BACKUPTOS3].get(
                SPEC_BACKUPTOS3_POLICY, {}).get(SPEC_BACKUPTOS3_POLICY_ARCHIVE,
                                                "") == "on":
            readwrite_conns = connections(
                spec, meta, patch, get_field(POSTGRESQL, READWRITEINSTANCE),
                False, None, logger, None, status, False)
            conn = get_primary_conn(readwrite_conns,
                                    0,
                                    logger,
                                    interrupt=False)
            cmd = [
                "pgtools", "-w", "0", "-q",
                ''' "select last_archived_wal, last_archived_time from pg_stat_archiver limit 1;" '''
            ]
            logger.info(f"correct_backup_status with cmd {cmd}")
            output = exec_command(conn, cmd, logger,
                                  interrupt=False).split("|")
            keys = ["last_archived_wal", "last_archived_time"]
            state = dict(zip(keys, output))

            readwrite_conns.free_conns()
        else:
            state = ""
        if status.get(CLUSTER_STATUS_ARCHIVE, None) != state:
            set_cluster_status(meta, CLUSTER_STATUS_ARCHIVE, state, logger)


def correct_s3_profile(
    meta: kopf.Meta,
    spec: kopf.Spec,
    patch: kopf.Patch,
    status: kopf.Status,
    logger: logging.Logger,
) -> None:
    # if backup_util.get_backup_mode(
    #         meta, spec, patch, status,
    #         logger) == BACKUP_MODE_S3_MANUAL or backup_util.get_backup_mode(
    #             meta, spec, patch, status, logger) == BACKUP_MODE_S3_CRON:
    # Verify S3, not verify archive=on
    # archive may be changed to off after the last backup, but the next backup is not performed. Archiving is still required at this point.
    if spec.get(SPEC_S3, None) is not None:
        is_correct = False
        readwrite_conns = connections(spec, meta, patch,
                                      get_field(POSTGRESQL, READWRITEINSTANCE),
                                      False, None, logger, None, status, False)
        s3_info = backup_util.get_need_s3_env(meta, spec, patch, status,
                                              logger, [SPEC_S3])

        for conn in readwrite_conns.get_conns():
            cmd = ["pgtools", "-w", "0", "-q", "'show archive_command;'"]
            output = exec_command(conn, cmd, logger, interrupt=False)
            if output.find("barman") != -1:
                is_correct = True
                break

        if not is_correct:
            logger.info(
                "archive_command is not barman, don't need correct s3 profile")
            return

        for conn in readwrite_conns.get_conns():
            cmd = ["aws configure list | grep 'None' | wc -l"]
            output = exec_command(conn,
                                  cmd,
                                  logger,
                                  interrupt=False,
                                  user="postgres")
            if to_int(output) == 4:
                cmd = ["pgtools", "-v"] + s3_info
                exec_command(conn, cmd, logger, interrupt=False)

        readwrite_conns.free_conns()
