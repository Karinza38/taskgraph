# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Support for running jobs that are invoked via the `run-task` script.
"""

from __future__ import absolute_import, print_function, unicode_literals

from six import text_type

from taskgraph.transforms.task import taskref_or_string
from taskgraph.transforms.job import run_job_using
from taskgraph.util import path
from taskgraph.util.schema import Schema
from taskgraph.transforms.job.common import support_vcs_checkout
from voluptuous import Required, Any, Optional

run_task_schema = Schema({
    Required('using'): 'run-task',

    # if true, add a cache at ~worker/.cache, which is where things like pip
    # tend to hide their caches.  This cache is never added for level-1 jobs.
    # TODO Once bug 1526028 is fixed, this and 'use-caches' should be merged.
    Required('cache-dotcache'): bool,

    # Whether or not to use caches.
    Optional('use-caches'): bool,

    # if true (the default), perform a checkout on the worker
    Required('checkout'): bool,

    Optional(
        "cwd",
        description="Path to run command in. If a checkout is present, the path "
        "to the checkout will be interpolated with the key `checkout`",
    ): text_type,

    # The sparse checkout profile to use. Value is the filename relative to the
    # directory where sparse profiles are defined (build/sparse-profiles/).
    Required('sparse-profile'): Any(basestring, None),

    # The command arguments to pass to the `run-task` script, after the
    # checkout arguments.  If a list, it will be passed directly; otherwise
    # it will be included in a single argument to `bash -cx`.
    Required('command'): Any([taskref_or_string], taskref_or_string),

    # Base work directory used to set up the task.
    Required('workdir'): basestring,

    # Whether to run as root. (defaults to False)
    Optional('run-as-root'): bool,
})


def common_setup(config, job, taskdesc, command):
    run = job['run']
    if run['checkout']:
        support_vcs_checkout(config, job, taskdesc,
                             sparse=bool(run['sparse-profile']))
        command.append('--vcs-checkout={}'.format(taskdesc['worker']['env']['VCS_PATH']))

    if run['sparse-profile']:
        command.append('--vcs-sparse-profile=build/sparse-profiles/%s' %
                       run['sparse-profile'])

    taskdesc['worker'].setdefault('env', {})['MOZ_SCM_LEVEL'] = config.params['level']


worker_defaults = {
    'cache-dotcache': False,
    'checkout': True,
    'sparse-profile': None,
    'run-as-root': False,
}


def run_task_url(config):
    return '{}/raw-file/{}/taskcluster/scripts/run-task'.format(
        config.params['head_repository'], config.params['head_rev'])


@run_job_using("docker-worker", "run-task", schema=run_task_schema, defaults=worker_defaults)
def docker_worker_run_task(config, job, taskdesc):
    run = job['run']
    worker = taskdesc['worker'] = job['worker']
    command = ['/usr/local/bin/run-task']
    common_setup(config, job, taskdesc, command)

    if run.get('cache-dotcache'):
        worker['caches'].append({
            'type': 'persistent',
            'name': '{project}-dotcache'.format(**config.params),
            'mount-point': '{workdir}/.cache'.format(**run),
            'skip-untrusted': True,
        })

    run_command = run['command']
    run_cwd = run.get('cwd')
    if run_cwd and run['checkout']:
        run_cwd = path.normpath(run_cwd.format(checkout=taskdesc['worker']['env']['VCS_PATH']))
    elif run_cwd and "{checkout}" in run_cwd:
        raise Exception(
            "Found `{{checkout}}` interpolation in `cwd` for task {name} "
            "but the task doesn't have a checkout: {cwd}".format(
                cwd=run_cwd, name=job.get("name", job.get("label"))
            )
        )

    # dict is for the case of `{'task-reference': basestring}`.
    if isinstance(run_command, (basestring, dict)):
        run_command = ['bash', '-cx', run_command]
    command.append('--fetch-hgfingerprint')
    if run['run-as-root']:
        command.extend(('--user', 'root', '--group', 'root'))
    if run_cwd:
        command.extend(('--task-cwd', run_cwd))
    command.append('--')
    command.extend(run_command)
    worker['command'] = command


@run_job_using("generic-worker", "run-task", schema=run_task_schema, defaults=worker_defaults)
def generic_worker_run_task(config, job, taskdesc):
    run = job['run']
    worker = taskdesc['worker'] = job['worker']
    is_win = worker['os'] == 'windows'
    is_mac = worker['os'] == 'macosx'

    if is_win:
        command = ['C:/mozilla-build/python3/python3.exe', 'run-task']
    elif is_mac:
        command = ['/tools/python36/bin/python3.6', 'run-task']
    else:
        command = ['./run-task']

    common_setup(config, job, taskdesc, command)

    worker.setdefault('mounts', [])
    if run.get('cache-dotcache'):
        worker['mounts'].append({
            'cache-name': '{project}-dotcache'.format(**config.params),
            'directory': '{workdir}/.cache'.format(**run),
        })
    worker['mounts'].append({
        'content': {
            'url': run_task_url(config),
        },
        'file': './run-task',
    })

    run_command = run['command']
    run_cwd = run.get('cwd')
    if run_cwd and run['checkout']:
        run_cwd = path.normpath(run_cwd.format(checkout=taskdesc['worker']['env']['VCS_PATH']))
    elif run_cwd and "{checkout}" in run_cwd:
        raise Exception(
            "Found `{{checkout}}` interpolation in `cwd` for task {name} "
            "but the task doesn't have a checkout: {cwd}".format(
                cwd=run_cwd, name=job.get("name", job.get("label"))
            )
        )

    if isinstance(run_command, basestring):
        if is_win:
            run_command = '"{}"'.format(run_command)
        run_command = ['bash', '-cx', run_command]

    if run['run-as-root']:
        command.extend(('--user', 'root', '--group', 'root'))
    if run_cwd:
        command.extend(('--task-cwd', run_cwd))
    command.append('--')
    command.extend(run_command)

    if is_win:
        worker['command'] = [' '.join(command)]
    else:
        worker['command'] = [
            ['chmod', '+x', 'run-task'],
            command,
        ]
