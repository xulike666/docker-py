import random

import docker

from ..helpers import force_leave_swarm, requires_api_version
from .base import BaseAPIIntegrationTest, BUSYBOX


class ServiceTest(BaseAPIIntegrationTest):
    def setUp(self):
        super(ServiceTest, self).setUp()
        force_leave_swarm(self.client)
        self.init_swarm()

    def tearDown(self):
        super(ServiceTest, self).tearDown()
        for service in self.client.services(filters={'name': 'dockerpytest_'}):
            try:
                self.client.remove_service(service['ID'])
            except docker.errors.APIError:
                pass
        force_leave_swarm(self.client)

    def get_service_name(self):
        return 'dockerpytest_{0:x}'.format(random.getrandbits(64))

    def create_simple_service(self, name=None):
        if name:
            name = 'dockerpytest_{0}'.format(name)
        else:
            name = self.get_service_name()

        container_spec = docker.types.ContainerSpec(
            BUSYBOX, ['echo', 'hello']
        )
        task_tmpl = docker.types.TaskTemplate(container_spec)
        return name, self.client.create_service(task_tmpl, name=name)

    @requires_api_version('1.24')
    def test_list_services(self):
        services = self.client.services()
        assert isinstance(services, list)

        test_services = self.client.services(filters={'name': 'dockerpytest_'})
        assert len(test_services) == 0
        self.create_simple_service()
        test_services = self.client.services(filters={'name': 'dockerpytest_'})
        assert len(test_services) == 1
        assert 'dockerpytest_' in test_services[0]['Spec']['Name']

    def test_inspect_service_by_id(self):
        svc_name, svc_id = self.create_simple_service()
        svc_info = self.client.inspect_service(svc_id)
        assert 'ID' in svc_info
        assert svc_info['ID'] == svc_id['ID']

    def test_inspect_service_by_name(self):
        svc_name, svc_id = self.create_simple_service()
        svc_info = self.client.inspect_service(svc_name)
        assert 'ID' in svc_info
        assert svc_info['ID'] == svc_id['ID']

    def test_remove_service_by_id(self):
        svc_name, svc_id = self.create_simple_service()
        assert self.client.remove_service(svc_id)
        test_services = self.client.services(filters={'name': 'dockerpytest_'})
        assert len(test_services) == 0

    def test_remove_service_by_name(self):
        svc_name, svc_id = self.create_simple_service()
        assert self.client.remove_service(svc_name)
        test_services = self.client.services(filters={'name': 'dockerpytest_'})
        assert len(test_services) == 0

    def test_create_service_simple(self):
        name, svc_id = self.create_simple_service()
        assert self.client.inspect_service(svc_id)
        services = self.client.services(filters={'name': name})
        assert len(services) == 1
        assert services[0]['ID'] == svc_id['ID']

    def test_create_service_custom_log_driver(self):
        container_spec = docker.types.ContainerSpec(
            BUSYBOX, ['echo', 'hello']
        )
        log_cfg = docker.types.DriverConfig('none')
        task_tmpl = docker.types.TaskTemplate(
            container_spec, log_driver=log_cfg
        )
        name = self.get_service_name()
        svc_id = self.client.create_service(task_tmpl, name=name)
        svc_info = self.client.inspect_service(svc_id)
        assert 'TaskTemplate' in svc_info['Spec']
        res_template = svc_info['Spec']['TaskTemplate']
        assert 'LogDriver' in res_template
        assert 'Name' in res_template['LogDriver']
        assert res_template['LogDriver']['Name'] == 'none'

    def test_create_service_with_volume_mount(self):
        vol_name = self.get_service_name()
        container_spec = docker.types.ContainerSpec(
            BUSYBOX, ['ls'],
            mounts=[
                docker.types.Mount(target='/test', source=vol_name)
            ]
        )
        self.tmp_volumes.append(vol_name)
        task_tmpl = docker.types.TaskTemplate(container_spec)
        name = self.get_service_name()
        svc_id = self.client.create_service(task_tmpl, name=name)
        svc_info = self.client.inspect_service(svc_id)
        assert 'ContainerSpec' in svc_info['Spec']['TaskTemplate']
        cspec = svc_info['Spec']['TaskTemplate']['ContainerSpec']
        assert 'Mounts' in cspec
        assert len(cspec['Mounts']) == 1
        mount = cspec['Mounts'][0]
        assert mount['Target'] == '/test'
        assert mount['Source'] == vol_name
        assert mount['Type'] == 'volume'

    def test_create_service_with_resources_constraints(self):
        container_spec = docker.types.ContainerSpec(BUSYBOX, ['true'])
        resources = docker.types.Resources(
            cpu_limit=4000000, mem_limit=3 * 1024 * 1024 * 1024,
            cpu_reservation=3500000, mem_reservation=2 * 1024 * 1024 * 1024
        )
        task_tmpl = docker.types.TaskTemplate(
            container_spec, resources=resources
        )
        name = self.get_service_name()
        svc_id = self.client.create_service(task_tmpl, name=name)
        svc_info = self.client.inspect_service(svc_id)
        assert 'TaskTemplate' in svc_info['Spec']
        res_template = svc_info['Spec']['TaskTemplate']
        assert 'Resources' in res_template
        assert res_template['Resources']['Limits'] == resources['Limits']
        assert res_template['Resources']['Reservations'] == resources[
            'Reservations'
        ]

    def test_create_service_with_update_config(self):
        container_spec = docker.types.ContainerSpec(BUSYBOX, ['true'])
        task_tmpl = docker.types.TaskTemplate(container_spec)
        update_config = docker.types.UpdateConfig(
            parallelism=10, delay=5, failure_action='pause'
        )
        name = self.get_service_name()
        svc_id = self.client.create_service(
            task_tmpl, update_config=update_config, name=name
        )
        svc_info = self.client.inspect_service(svc_id)
        assert 'UpdateConfig' in svc_info['Spec']
        uc = svc_info['Spec']['UpdateConfig']
        assert update_config['Parallelism'] == uc['Parallelism']
        assert update_config['Delay'] == uc['Delay']
        assert update_config['FailureAction'] == uc['FailureAction']

    @requires_api_version('1.25')
    def test_create_service_with_update_config_monitor(self):
        container_spec = docker.types.ContainerSpec('busybox', ['true'])
        task_tmpl = docker.types.TaskTemplate(container_spec)
        update_config = docker.types.UpdateConfig(
            monitor=300000000, max_failure_ratio=0.4
        )
        name = self.get_service_name()
        svc_id = self.client.create_service(
            task_tmpl, update_config=update_config, name=name
        )
        svc_info = self.client.inspect_service(svc_id)
        assert 'UpdateConfig' in svc_info['Spec']
        uc = svc_info['Spec']['UpdateConfig']
        assert update_config['Monitor'] == uc['Monitor']
        assert update_config['MaxFailureRatio'] == uc['MaxFailureRatio']

    def test_create_service_with_restart_policy(self):
        container_spec = docker.types.ContainerSpec(BUSYBOX, ['true'])
        policy = docker.types.RestartPolicy(
            docker.types.RestartPolicy.condition_types.ANY,
            delay=5, max_attempts=5
        )
        task_tmpl = docker.types.TaskTemplate(
            container_spec, restart_policy=policy
        )
        name = self.get_service_name()
        svc_id = self.client.create_service(task_tmpl, name=name)
        svc_info = self.client.inspect_service(svc_id)
        assert 'RestartPolicy' in svc_info['Spec']['TaskTemplate']
        assert policy == svc_info['Spec']['TaskTemplate']['RestartPolicy']

    def test_create_service_with_custom_networks(self):
        net1 = self.client.create_network(
            'dockerpytest_1', driver='overlay', ipam={'Driver': 'default'}
        )
        self.tmp_networks.append(net1['Id'])
        net2 = self.client.create_network(
            'dockerpytest_2', driver='overlay', ipam={'Driver': 'default'}
        )
        self.tmp_networks.append(net2['Id'])
        container_spec = docker.types.ContainerSpec(BUSYBOX, ['true'])
        task_tmpl = docker.types.TaskTemplate(container_spec)
        name = self.get_service_name()
        svc_id = self.client.create_service(
            task_tmpl, name=name, networks=[
                'dockerpytest_1', {'Target': 'dockerpytest_2'}
            ]
        )
        svc_info = self.client.inspect_service(svc_id)
        assert 'Networks' in svc_info['Spec']
        assert svc_info['Spec']['Networks'] == [
            {'Target': net1['Id']}, {'Target': net2['Id']}
        ]

    def test_create_service_with_placement(self):
        node_id = self.client.nodes()[0]['ID']
        container_spec = docker.types.ContainerSpec(BUSYBOX, ['true'])
        task_tmpl = docker.types.TaskTemplate(
            container_spec, placement=['node.id=={}'.format(node_id)]
        )
        name = self.get_service_name()
        svc_id = self.client.create_service(task_tmpl, name=name)
        svc_info = self.client.inspect_service(svc_id)
        assert 'Placement' in svc_info['Spec']['TaskTemplate']
        assert (svc_info['Spec']['TaskTemplate']['Placement'] ==
                {'Constraints': ['node.id=={}'.format(node_id)]})

    def test_create_service_with_endpoint_spec(self):
        container_spec = docker.types.ContainerSpec(BUSYBOX, ['true'])
        task_tmpl = docker.types.TaskTemplate(container_spec)
        name = self.get_service_name()
        endpoint_spec = docker.types.EndpointSpec(ports={
            12357: (1990, 'udp'),
            12562: (678,),
            53243: 8080,
        })
        svc_id = self.client.create_service(
            task_tmpl, name=name, endpoint_spec=endpoint_spec
        )
        svc_info = self.client.inspect_service(svc_id)
        print(svc_info)
        ports = svc_info['Spec']['EndpointSpec']['Ports']
        for port in ports:
            if port['PublishedPort'] == 12562:
                assert port['TargetPort'] == 678
                assert port['Protocol'] == 'tcp'
            elif port['PublishedPort'] == 53243:
                assert port['TargetPort'] == 8080
                assert port['Protocol'] == 'tcp'
            elif port['PublishedPort'] == 12357:
                assert port['TargetPort'] == 1990
                assert port['Protocol'] == 'udp'
            else:
                self.fail('Invalid port specification: {0}'.format(port))

        assert len(ports) == 3

    def test_create_service_with_env(self):
        container_spec = docker.types.ContainerSpec(
            BUSYBOX, ['true'], env={'DOCKER_PY_TEST': 1}
        )
        task_tmpl = docker.types.TaskTemplate(
            container_spec,
        )
        name = self.get_service_name()
        svc_id = self.client.create_service(task_tmpl, name=name)
        svc_info = self.client.inspect_service(svc_id)
        assert 'TaskTemplate' in svc_info['Spec']
        assert 'ContainerSpec' in svc_info['Spec']['TaskTemplate']
        con_spec = svc_info['Spec']['TaskTemplate']['ContainerSpec']
        assert 'Env' in con_spec
        assert con_spec['Env'] == ['DOCKER_PY_TEST=1']

    def test_create_service_global_mode(self):
        container_spec = docker.types.ContainerSpec(
            BUSYBOX, ['echo', 'hello']
        )
        task_tmpl = docker.types.TaskTemplate(container_spec)
        name = self.get_service_name()
        svc_id = self.client.create_service(
            task_tmpl, name=name, mode='global'
        )
        svc_info = self.client.inspect_service(svc_id)
        assert 'Mode' in svc_info['Spec']
        assert 'Global' in svc_info['Spec']['Mode']

    def test_create_service_replicated_mode(self):
        container_spec = docker.types.ContainerSpec(
            BUSYBOX, ['echo', 'hello']
        )
        task_tmpl = docker.types.TaskTemplate(container_spec)
        name = self.get_service_name()
        svc_id = self.client.create_service(
            task_tmpl, name=name,
            mode=docker.types.ServiceMode('replicated', 5)
        )
        svc_info = self.client.inspect_service(svc_id)
        assert 'Mode' in svc_info['Spec']
        assert 'Replicated' in svc_info['Spec']['Mode']
        assert svc_info['Spec']['Mode']['Replicated'] == {'Replicas': 5}

    @requires_api_version('1.25')
    def test_update_service_force_update(self):
        container_spec = docker.types.ContainerSpec(
            'busybox', ['echo', 'hello']
        )
        task_tmpl = docker.types.TaskTemplate(container_spec)
        name = self.get_service_name()
        svc_id = self.client.create_service(task_tmpl, name=name)
        svc_info = self.client.inspect_service(svc_id)
        assert 'TaskTemplate' in svc_info['Spec']
        assert 'ForceUpdate' in svc_info['Spec']['TaskTemplate']
        assert svc_info['Spec']['TaskTemplate']['ForceUpdate'] == 0
        version_index = svc_info['Version']['Index']

        task_tmpl = docker.types.TaskTemplate(container_spec, force_update=10)
        self.client.update_service(name, version_index, task_tmpl, name=name)
        svc_info = self.client.inspect_service(svc_id)
        new_index = svc_info['Version']['Index']
        assert new_index > version_index
        assert svc_info['Spec']['TaskTemplate']['ForceUpdate'] == 10
