import pytest

from seaworthy import wait_for_logs_matching
from seaworthy.containers.base import ContainerBase
from seaworthy.containers.provided import (
    PostgreSQLContainer, RabbitMQContainer)
from seaworthy.ps import list_container_processes
from seaworthy.pytest.fixtures import clean_container_fixtures
from seaworthy.utils import output_lines


raw_db_container, db_container = clean_container_fixtures(
    PostgreSQLContainer(), 'db_container', scope='module')


raw_amqp_container, amqp_container = clean_container_fixtures(
    RabbitMQContainer(vhost='/mysite'), 'amqp_container', scope='module')


class DjangoBootstrapContainer(ContainerBase):
    def __init__(self, name, image, wait_patterns, kwargs):
        super().__init__(name, image, wait_patterns)
        self._kwargs = kwargs

    def create_kwargs(self):
        return self._kwargs

    def wait_for_start(self, docker_helper, container):
        if self.wait_matchers:
            for matcher in self.wait_matchers:
                wait_for_logs_matching(container, matcher)

    def list_processes(self):
        return list_container_processes(self.inner())

    def stdout_logs(self):
        return output_lines(self.inner().logs(stdout=True, stderr=False))

    def exec_find(self, params):
        return output_lines(self.inner().exec_run(['find'] + params))


class NginxContainer(ContainerBase):
    def __init__(self, name, image):
        super().__init__(name, image)

    def create_kwargs(self):
        return {
            'ports': {'80/tcp': ('127.0.0.1',)}
        }

    def list_processes(self):
        return list_container_processes(self.inner())

    def stdout_logs(self):
        return output_lines(self.inner().logs(stdout=True, stderr=False))


def create_django_bootstrap_container(
        request, name, wait_lines, command=None, single_container=False,
        publish_port=True, other_fixtures=()):
    # FIXME: there are probably better ways to skip these tests
    pods = request.getfixturevalue('pods')
    if single_container and pods:
        pytest.skip()
    if request.fixturename == 'web_only_container' and pods:
        pytest.skip()
    if request.fixturename == 'gunicorn_container' and not pods:
        pytest.skip()

    for fix in other_fixtures:
        request.getfixturevalue(fix)
    image = request.getfixturevalue('django_bootstrap_image')
    # FIXME: Get these URLs in a better way.
    database_url = PostgreSQLContainer().database_url()
    celery_broker_url = RabbitMQContainer(vhost='/mysite').broker_url()
    kwargs = {
        'command': command,
        'environment': {
            'SECRET_KEY': 'secret',
            'ALLOWED_HOSTS': 'localhost,127.0.0.1,0.0.0.0',
            'DATABASE_URL': database_url,
            'CELERY_BROKER_URL': celery_broker_url,
        },
    }
    if single_container:
        kwargs['environment'].update({
            'CELERY_WORKER': '1',
            'CELERY_BEAT': '1',
        })
    if publish_port:
        kwargs['ports'] = {'8000/tcp': ('127.0.0.1',)}

    return DjangoBootstrapContainer(name, image, wait_lines, kwargs)


def container_factory_fixture(factory, name, kwargs, scope='function'):
    @pytest.fixture(name=name, scope=scope)
    def raw_fixture(request, docker_helper):
        container = factory(request, **kwargs)
        container.create_and_start(docker_helper)
        yield container
        container.stop_and_remove(docker_helper)

    return raw_fixture


def make_app_container(
        name, container_name, other_fixtures, wait_lines, command=None,
        single_container=False, publish_port=True):
    return container_factory_fixture(
        create_django_bootstrap_container, name, kwargs={
            'name': container_name,
            'wait_lines': wait_lines,
            'command': command,
            'single_container': single_container,
            'publish_port': publish_port,
            'other_fixtures': other_fixtures,
        })


single_container = make_app_container(
    'single_container', 'web', ['db_container', 'amqp_container'],
    [r'Booting worker', r'celery@\w+ ready', r'beat: Starting\.\.\.'],
    single_container=True)

web_only_container = make_app_container(
    'web_only_container', 'web', ['db_container', 'amqp_container'],
    [r'Booting worker'])

gunicorn_container = make_app_container(
    'gunicorn_container', 'web', ['db_container', 'amqp_container'],
    [r'Booting worker'], publish_port=False)

worker_only_container = make_app_container(
    'worker_only_container', 'worker', ['amqp_container'],
    [r'celery@\w+ ready'], command=['celery', 'worker'], publish_port=False)

beat_only_container = make_app_container(
    'beat_only_container', 'beat', ['amqp_container'],
    [r'beat: Starting\.\.\.'], command=['celery', 'beat'], publish_port=False)


def make_multi_container(name, containers):
    @pytest.fixture(name=name, params=containers)
    def containers(request):
        yield request.getfixturevalue(request.param)
    return containers


web_container = make_multi_container(
    'web_container',
    ['single_container', 'web_only_container', 'gunicorn_container'])

nginx_container = make_multi_container(
    'nginx_container',
    ['single_container', 'web_only_container', 'nginx_only_container'])

worker_container = make_multi_container(
    'worker_container', ['single_container', 'worker_only_container'])

beat_container = make_multi_container(
    'beat_container', ['single_container', 'beat_only_container'])


@pytest.fixture
def nginx_only_container(request, pods, nginx_image, docker_helper):
    if not pods:
        pytest.skip()

    container = NginxContainer('nginx', nginx_image)
    container.create_and_start(docker_helper)
    yield container
    container.stop_and_remove(docker_helper)


__all__ = [
    'amqp_container',
    'beat_container',
    'beat_only_container',
    'db_container',
    'gunicorn_container',
    'nginx_container',
    'nginx_only_container',
    'raw_amqp_container',
    'raw_db_container',
    'single_container',
    'web_container',
    'web_only_container',
    'worker_container',
    'worker_only_container',
]