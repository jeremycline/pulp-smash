# coding=utf-8
"""Test the `repository`_ API endpoints.

The assumptions explored in this module have the following dependencies::

        It is possible to create a repository.
        ├── It is impossible to create a repository with a duplicate ID
        │   or other invalid attributes.
        ├── It is possible to read a repository.
        ├── It is possible to update a repository.
        ├── It is possible to delete a repository.
        └── It is possible to trigger a lazy download for a repository.


.. _repository:
    https://pulp.readthedocs.org/en/latest/dev-guide/integration/rest-api/repo/index.html

"""
from __future__ import unicode_literals

import requests

from pulp_smash.config import get_config
from pulp_smash.constants import REPOSITORY_PATH, ERROR_KEYS
from pulp_smash.utils import create_repository, delete, require, uuid4
from requests.exceptions import HTTPError
from unittest2 import TestCase


class CreateSuccessTestCase(TestCase):
    """Establish that we can create repositories."""

    @classmethod
    def setUpClass(cls):
        """Create several repositories.

        Create one repository with the minimum required attributes, and a
        second with all available attributes except importers and distributors.

        """
        cls.cfg = get_config()
        cls.bodies = (
            {'id': uuid4()},
            {key: uuid4() for key in ('id', 'display_name', 'description')},
        )
        cls.bodies[1]['notes'] = {uuid4(): uuid4()}
        cls.responses = []
        cls.attrs_iter = tuple((  # 1:1 correlation with cls.bodies
            create_repository(cls.cfg, body, cls.responses)
            for body in cls.bodies
        ))

    def test_status_code(self):
        """Assert that each response has a HTTP 201 status code."""
        for i, response in enumerate(self.responses):
            with self.subTest(self.bodies[i]):
                self.assertEqual(response.status_code, 201)

    @require('2.7')  # https://pulp.plan.io/issues/695
    def test_location_header(self):
        """Assert that the Location header is correctly set in the response."""
        for response, attrs in zip(self.responses, self.attrs_iter):
            with self.subTest((response, attrs)):
                url = '{}{}{}/'.format(
                    self.cfg.base_url,
                    REPOSITORY_PATH,
                    attrs['id'],
                )
                self.assertEqual(response.headers['Location'], url)

    def test_attributes(self):
        """Assert that each repository has the requested attributes."""
        for body, attrs in zip(self.bodies, self.attrs_iter):
            with self.subTest((body, attrs)):
                self.assertLessEqual(set(body.keys()), set(attrs.keys()))
                attrs = {key: attrs[key] for key in body.keys()}
                self.assertEqual(body, attrs)

    @classmethod
    def tearDownClass(cls):
        """Delete the created repositories."""
        for attrs in cls.attrs_iter:
            delete(cls.cfg, attrs['_href'])


class CreateFailureTestCase(TestCase):
    """Establish that repositories are not created in documented scenarios."""

    @classmethod
    def setUpClass(cls):
        """Create several repositories.

        Each repository is created to test a different failure scenario. The
        first repository is created in order to test duplicate ids.

        """
        cls.cfg = get_config()
        cls.attrs_iter = (create_repository(cls.cfg, {'id': uuid4()}),)
        cls.bodies = (
            {'id': None},  # 400
            ['Incorrect data type'],  # 400
            {'missing_required_keys': 'id'},  # 400
            {'id': cls.attrs_iter[0]['id']},  # 409
        )
        cls.status_codes = (400, 400, 400, 409)
        cls.responses = []
        for body in cls.bodies:
            try:
                create_repository(cls.cfg, body, cls.responses)
            except HTTPError:
                pass

    def test_status_code(self):
        """Assert that each response has the expected HTTP status code."""
        for response, status_code in zip(self.responses, self.status_codes):
            with self.subTest((response, status_code)):
                self.assertEqual(response.status_code, status_code)

    def test_location_header(self):
        """Assert that the Location header is correctly set in the response."""
        for i, response in enumerate(self.responses):
            with self.subTest(i=i):
                self.assertNotIn('Location', response.headers)

    def test_exception_keys_json(self):
        """Assert the JSON body returned contains the correct keys."""
        for i, response in enumerate(self.responses):
            with self.subTest(i=i):
                self.assertEqual(
                    frozenset(response.json().keys()),
                    ERROR_KEYS,
                )

    def test_exception_json_http_status(self):
        """Assert the JSON body returned contains the correct HTTP code."""
        for response, status_code in zip(self.responses, self.status_codes):
            with self.subTest((response, status_code)):
                self.assertEqual(response.json()['http_status'], status_code)

    @classmethod
    def tearDownClass(cls):
        """Delete the created repositories."""
        for attrs in cls.attrs_iter:
            delete(cls.cfg, attrs['_href'])


class ReadUpdateDeleteSuccessTestCase(TestCase):
    """Establish that we can read, update, and delete repositories.

    This test assumes that the assertions in :class:`CreateSuccessTestCase` are
    valid.

    """

    @classmethod
    def setUpClass(cls):
        """Create three repositories to read, update, and delete."""
        cls.cfg = get_config()
        cls.attrs_iter = tuple((
            create_repository(cls.cfg, {'id': uuid4()}) for _ in range(3)
        ))
        cls.update_body = {'delta': {
            key: uuid4() for key in ('description', 'display_name')
        }}

        # Read, update, and delete the three repositories, respectively.
        cls.responses = {}
        cls.responses['read'] = requests.get(
            cls.cfg.base_url + cls.attrs_iter[0]['_href'],
            **cls.cfg.get_requests_kwargs()
        )
        cls.responses['update'] = requests.put(
            cls.cfg.base_url + cls.attrs_iter[1]['_href'],
            json=cls.update_body,
            **cls.cfg.get_requests_kwargs()
        )
        cls.responses['delete'] = requests.delete(
            cls.cfg.base_url + cls.attrs_iter[2]['_href'],
            **cls.cfg.get_requests_kwargs()
        )

    def test_status_codes(self):
        """Assert each response has a correct HTTP status code."""
        for action, code in zip(('read', 'update', 'delete'), (200, 200, 202)):
            with self.subTest((action, code)):
                self.assertEqual(self.responses[action].status_code, code)

    def test_read(self):
        """Assert the "read" response body contains the correct attributes."""
        create_attrs = self.attrs_iter[0]
        read_attrs = self.responses['read'].json()
        self.assertLessEqual(set(create_attrs.keys()), set(read_attrs.keys()))
        read_attrs = {key: read_attrs[key] for key in create_attrs.keys()}
        self.assertEqual(create_attrs, read_attrs)

    def test_update_spawned_tasks(self):
        """Assert the "update" response body mentions no spawned tasks."""
        attrs = self.responses['update'].json()
        self.assertIn('spawned_tasks', attrs)
        self.assertListEqual([], attrs['spawned_tasks'])

    def test_update_attributes_result(self):
        """Assert the "update" response body has the correct attributes."""
        attrs = self.responses['update'].json()
        self.assertIn('result', attrs)
        for key, value in self.update_body['delta'].items():
            with self.subTest(key=key):
                self.assertIn(key, attrs['result'])
                self.assertEqual(value, attrs['result'][key])

    @classmethod
    def tearDownClass(cls):
        """Delete the created repositories."""
        cls.attrs_iter = cls.attrs_iter[:-1]  # pop last item
        for attrs in cls.attrs_iter:
            delete(cls.cfg, attrs['_href'])


class DownloadRepoTestCase(TestCase):
    """Establish that we can dispatch a task to download a repository.

    This test assumes that the assertions in :class:`CreateSuccessTestCase` are
    valid.

    """

    @classmethod
    def setUpClass(cls):
        """Create one repository to dispatch a download task for."""
        cls.cfg = get_config()
        cls.url = cls.cfg.base_url + REPOSITORY_PATH
        cls.create_body = {'id': uuid4()}
        cls.create_response = requests.post(
            cls.url,
            json=cls.create_body,
            **cls.cfg.get_requests_kwargs()
        )
        cls.download_success_response = requests.post(
            cls.url + cls.create_body['id'] + '/actions/download/',
            json={},
            **cls.cfg.get_requests_kwargs()
        )
        cls.download_failure_response = requests.post(
            cls.url + uuid4() + '/actions/download/',
            json={},
            **cls.cfg.get_requests_kwargs()
        )

    def test_create_status_code(self):
        """Assert that the create call has a 201 status code."""
        self.assertEqual(self.create_response.status_code, 201)

    def test_download_success_status_code(self):
        """Assert that the download success call has a 202 status code."""
        self.assertEqual(self.download_success_response.status_code, 202)

    def test_download_failure_status_code(self):
        """Assert that the download failure call has a 404 status code."""
        self.assertEqual(self.download_failure_response.status_code, 404)

    def test_download_success_attributes_spawned_tasks(self):
        """Assert that `spawned_tasks` is present and a task was created."""
        response = self.download_success_response.json()
        self.assertIn('spawned_tasks', response)
        self.assertEqual(len(response['spawned_tasks']), 1)

    @classmethod
    def tearDownClass(cls):
        """Delete the created repositories."""
        requests.delete(
            cls.url + cls.create_body['id'] + '/',
            **cls.cfg.get_requests_kwargs()
        ).raise_for_status()


class ReadDetailsTestCase(TestCase):
    """Establish that we can read a repository and retrieve a detailed view.

    This test assumes that the assertions in :class:`CreateSuccessTestCase` are
    valid.

    """

    @classmethod
    def setUpClass(cls):
        """Create a repository to read details from."""
        cls.cfg = get_config()
        cls.attributes = create_repository(cls.cfg, {'id': uuid4()})

        # Read with details, read with importer, and read with distributor.
        cls.responses = {}
        cls.responses['read_details'] = requests.get(
            cls.cfg.base_url + cls.attributes['_href'] + '?details=true',
            **cls.cfg.get_requests_kwargs()
        )
        cls.responses['read_importers'] = requests.get(
            cls.cfg.base_url + cls.attributes['_href'] + '?importers=true',
            **cls.cfg.get_requests_kwargs()
        )
        cls.responses['read_distributors'] = requests.get(
            cls.cfg.base_url + cls.attributes['_href'] + '?distributors=true',
            **cls.cfg.get_requests_kwargs()
        )

    def test_status_codes(self):
        """Assert each response has a correct HTTP status code."""
        for action, code in zip(self.responses.keys(), (200, 200, 200)):
            with self.subTest((action, code)):
                self.assertEqual(self.responses[action].status_code, code)

    def test_read_details_attributes(self):
        """
        Assert the "read_details" response body contains the correct
        attributes.
        """
        expected_details = (
            'distributors',
            'importers',
            'total_repository_units',
            'locally_stored_units'
        )
        for key in expected_details:
            with self.subTest(key):
                self.assertIn(key, self.responses['read_details'].json())

    def test_read_details_total_repo_units(self):
        """Assert that the repo has 0 total repo units."""
        response_body = self.responses['read_details'].json()
        self.assertEqual(0, response_body['total_repository_units'])

    def test_read_details_locally_stored_units(self):
        """Assert that the repo has 0 locally stored units."""
        response_body = self.responses['read_details'].json()
        self.assertEqual(0, response_body['locally_stored_units'])

    def test_read_importers(self):
        """Assert the "read_importers" response body contains the importer."""
        self.assertIn('importers', self.responses['read_importers'].json())

    def test_read_distributor(self):
        """
        Assert the "read_distributors" response body contains the
        distributor.
        """
        self.assertIn(
            'distributors',
            self.responses['read_distributors'].json()
        )

    @classmethod
    def tearDownClass(cls):
        """Delete the created repositories."""
        delete(cls.cfg, cls.attributes['_href'])
