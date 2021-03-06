#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: wushuiyong
# @Created Time : 日  1/ 1 23:43:12 2017
# @Description:

from fabric2 import Connection
from flask import current_app
from flask_socketio import emit
from walle.model.record import RecordModel
from invoke import Result
from walle.service.code import Code

class Waller(Connection):
    connections, success, errors = {}, {}, {}
    release_version_tar, release_version = None, None

    def run(self, command, wenv=None, sudo=False, exception=True, **kwargs):
        '''
        pty=True/False是直接影响到输出.False较适合在获取文本,True更适合websocket

        :param command:
        :param wenv:
        :param sudo:      False/True default False
        :param exception: False/True default True
                          False return Result(exited=xx, stderr=xx, stdout=xx) for process to raise custom exception by exited code
                          True raise Exception
        :param kwargs:
        :return:
        '''
        message = 'deploying task_id=%s [%s@%s]$ %s ' % (wenv['task_id'], self.user, self.host, command)
        current_app.logger.info(message)
        try:
            if sudo:
                result = super(Waller, self).sudo(command, pty=False, **kwargs)
            else:
                result = super(Waller, self).run(command, pty=True, warn=True, **kwargs)

            if result.failed:
                exitcode, stdout, stderr = result.exited, '', result.stdout
            else:
                exitcode, stdout, stderr = 0, result.stdout, ''

            message = 'task_id=%s, user:%s host:%s command:%s status:%s, success:%s, error:%s' % (
                wenv['task_id'], self.user, self.host, command, exitcode, stdout, stderr
            )
            # TODO
            ws_dict = {
                'user': self.user,
                'host': self.host,
                'cmd': command,
                'status': exitcode,
                'stage': wenv['stage'],
                'sequence': wenv['sequence'],
                'success': stdout,
                'error': stderr,
            }
            if wenv['console']:
                emit('console', {'event': 'task:console', 'data': ws_dict}, room=wenv['task_id'])

            RecordModel().save_record(stage=wenv['stage'], sequence=wenv['sequence'], user_id=wenv['user_id'],
                                      task_id=wenv['task_id'], status=exitcode, host=self.host, user=self.user,
                                      command=result.command, success=stdout,
                                      error=stderr)
            current_app.logger.info(result)
            if exitcode != Code.Ok:
                current_app.logger.error(message, exc_info=1)
                current_app.logger.exception(result.stdout.strip(), exc_info=1)
                return result
            return result

        except Exception as e:
            current_app.logger.exception(e)

            # TODO 貌似可能的异常有很多种，需要分层才能完美解决 something wrong without e.result
            error = e.result if 'result' in e else e.message
            RecordModel().save_record(stage=wenv['stage'], sequence=wenv['sequence'], user_id=wenv['user_id'],
                                      task_id=wenv['task_id'], status=1, host=self.host, user=self.user,
                                      command=command, success='', error=error)
            if hasattr(e, 'reason') and hasattr(e, 'result'):
                message = 'task_id=%s, user:%s host:%s command:%s, status=1, reason:%s, result:%s exception:%s' % (
                    wenv['task_id'], self.user, self.host, command, e.reason, error, e.message
                )
            else:
                message = 'task_id=%s, user:%s host:%s command:%s, status=1, message:%s' % (
                    wenv['task_id'], self.user, self.host, command, e.message
                )
            current_app.logger.error(message, exc_info=1)

            # TODO
            ws_dict = {
                'user': self.user,
                'host': self.host,
                'cmd': command,
                'status': 1,
                'stage': wenv['stage'],
                'sequence': wenv['sequence'],
                'success': '',
                'error': error,
            }
            if wenv['console']:
                emit('console', {'event': 'console', 'data': ws_dict}, room=wenv['task_id'])

            if exception:
                raise e
            return Result(exited=-1, stderr=error, stdout=error)

    def sudo(self, command, wenv=None, **kwargs):
        return self.run(command, wenv=wenv, sudo=True, **kwargs)

    def get(self, remote, local=None, wenv=None):
        return self.sync(wtype='get', remote=remote, local=local, wenv=wenv)

    def put(self, local, remote=None, wenv=None, *args, **kwargs):
        return self.sync(wtype='put', local=local, remote=remote, wenv=wenv, *args, **kwargs)

    def sync(self, wtype, remote=None, local=None, wenv=None):
        command = 'scp %s %s@%s:%s' % (local, self.user, self.host, remote) if wtype == 'put' \
            else 'scp %s@%s:%s %s' % (self.user, self.host, remote, local)
        message = 'deploying task_id=%s [%s@%s]$ %s ' % (wenv['task_id'], self.user, self.host, command)
        current_app.logger.info(message)

        try:
            if wtype == 'put':
                result = super(Waller, self).put(local=local, remote=remote)
                current_app.logger.info('put: local %s, remote %s', local, remote)
                op_user = current_app.config.get('LOCAL_SERVER_USER')
                op_host = current_app.config.get('LOCAL_SERVER_HOST')

            else:
                result = super(Waller, self).get(remote=remote, local=local)
                current_app.logger.info('get: local %s, remote %s', local, remote)
                current_app.logger.info('get: orig_local %s, local %s', result.orig_local, result.local)
                op_user = self.user
                op_host = self.host

            current_app.logger.info('put: %s, %s', result, dir(result))
            # TODO 可能会有非22端口的问题
            RecordModel().save_record(stage=wenv['stage'], sequence=wenv['sequence'], user_id=wenv['user_id'],
                                      task_id=wenv['task_id'], status=0, host=self.host, user=self.user,
                                      command=command, )

            # TODO
            ws_dict = {
                'user': op_user,
                'host': op_host,
                'cmd': command,
                'status': 1,
                'stage': wenv['stage'],
                'sequence': wenv['sequence'],
                'success': '',
                'error': '',
            }
            if wenv['console']:
                emit('console', {'event': 'task:console', 'data': ws_dict}, room=wenv['task_id'])

            return result

        except Exception as e:
            # TODO 收尾下
            current_app.logger.info('put: %s, %s', e, dir(e))

            # TODO command
            ws_dict = {
                'user': self.user,
                'host': self.host,
                'cmd': command,
                'status': 1,
                'stage': wenv['stage'],
                'sequence': wenv['sequence'],
                'success': '',
                'error': e.message,
            }
            if wenv['console']:
                emit('console', {'event': 'task:console', 'data': ws_dict}, room=wenv['task_id'])
