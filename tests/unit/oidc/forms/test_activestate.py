# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pretend
import pytest
import wtforms

from requests import ConnectionError, HTTPError, Timeout
from webob.multidict import MultiDict

from warehouse.oidc.forms import activestate

fake_username = "some-username"
fake_org_name = "some-org"
fake_user_info = {"user_id": "some-user-id"}
fake_org_info = {"added": "somedatestring"}
fake_gql_org_response = {"data": {"organizations": [fake_org_info]}}
fake_gql_user_response = {"data": {"users": [fake_user_info]}}


class TestPendingActiveStatePublisherForm:
    def test_validate(self, monkeypatch):
        project_factory = []
        data = MultiDict(
            {
                "organization": "some-org",
                "project": "some-project",
                "actor": "someuser",
                "project_name": "some-project",
            }
        )
        form = activestate.PendingActiveStatePublisherForm(
            MultiDict(data), project_factory=project_factory
        )

        # Test built-in validations
        monkeypatch.setattr(form, "_lookup_actor", lambda *o: {"user_id": "some-id"})

        monkeypatch.setattr(
            form, "_lookup_organization", lambda *o: {"added": "somedatestring"}
        )

        assert form._project_factory == project_factory
        assert form.validate()

    def test_validate_project_name_already_in_use(self):
        project_factory = ["some-project"]
        form = activestate.PendingActiveStatePublisherForm(
            project_factory=project_factory
        )

        field = pretend.stub(data="some-project")
        with pytest.raises(wtforms.validators.ValidationError):
            form.validate_project_name(field)


class TestActiveStatePublisherForm:
    def test_validate(self, monkeypatch):
        data = MultiDict(
            {
                "organization": "some-org",
                "project": "some-project",
                "actor": "someuser",
            }
        )
        form = activestate.ActiveStatePublisherForm(MultiDict(data))

        org_info = {"added": "somedatestring"}
        monkeypatch.setattr(form, "_lookup_organization", lambda o: org_info)
        owner_info = {"user_id": "some-user-id"}
        monkeypatch.setattr(form, "_lookup_actor", lambda o: owner_info)

        assert form.validate(), str(form.errors)

    # _lookup_actor
    def test_lookup_actor_404(self, monkeypatch):
        response = pretend.stub(
            status_code=404,
            raise_for_status=pretend.raiser(HTTPError),
            content=b"fake-content",
        )
        requests = pretend.stub(
            post=pretend.call_recorder(lambda o, **kw: response), HTTPError=HTTPError
        )

        monkeypatch.setattr(activestate, "requests", requests)

        form = activestate.ActiveStatePublisherForm()
        with pytest.raises(wtforms.validators.ValidationError):
            form._lookup_actor(fake_username)

        assert requests.post.calls == [
            pretend.call(
                "https://platform.activestate.com/graphql/v1/graphql",
                json={
                    "query": "query($username: String) {users(where: {username: {_eq: $username}}) {user_id}}",  # noqa
                    "variables": {"username": fake_username},
                },
                timeout=5,
            )
        ]

    def test_lookup_actor_other_http_error(self, monkeypatch):
        response = pretend.stub(
            # anything that isn't 404 or 403
            status_code=422,
            raise_for_status=pretend.raiser(HTTPError),
            content=b"fake-content",
        )
        requests = pretend.stub(
            post=pretend.call_recorder(lambda o, **kw: response),
            HTTPError=HTTPError,
        )
        monkeypatch.setattr(activestate, "requests", requests)

        sentry_sdk = pretend.stub(capture_message=pretend.call_recorder(lambda s: None))
        monkeypatch.setattr(activestate, "sentry_sdk", sentry_sdk)

        form = activestate.ActiveStatePublisherForm()
        with pytest.raises(wtforms.validators.ValidationError):
            form._lookup_actor(fake_username)

        assert requests.post.calls == [
            pretend.call(
                "https://platform.activestate.com/graphql/v1/graphql",
                json={
                    "query": "query($username: String) {users(where: {username: {_eq: $username}}) {user_id}}",  # noqa
                    "variables": {"username": fake_username},
                },
                timeout=5,
            )
        ]

        assert sentry_sdk.capture_message.calls == [
            pretend.call(
                "Unexpected error from ActiveState user lookup: "
                "response.content=b'fake-content'"
            )
        ]

    def test_lookup_actor_http_timeout(self, monkeypatch):
        requests = pretend.stub(
            post=pretend.raiser(Timeout),
            Timeout=Timeout,
            HTTPError=HTTPError,
            ConnectionError=ConnectionError,
        )
        monkeypatch.setattr(activestate, "requests", requests)

        sentry_sdk = pretend.stub(capture_message=pretend.call_recorder(lambda s: None))
        monkeypatch.setattr(activestate, "sentry_sdk", sentry_sdk)

        form = activestate.ActiveStatePublisherForm()
        with pytest.raises(wtforms.validators.ValidationError):
            form._lookup_actor(fake_username)

        assert sentry_sdk.capture_message.calls == [
            pretend.call("Timeout from ActiveState user lookup API (possibly offline)")
        ]

    def test_lookup_actor_connection_error(self, monkeypatch):
        requests = pretend.stub(
            post=pretend.raiser(ConnectionError),
            Timeout=Timeout,
            HTTPError=HTTPError,
            ConnectionError=ConnectionError,
        )
        monkeypatch.setattr(activestate, "requests", requests)

        sentry_sdk = pretend.stub(capture_message=pretend.call_recorder(lambda s: None))
        monkeypatch.setattr(activestate, "sentry_sdk", sentry_sdk)

        form = activestate.ActiveStatePublisherForm()
        with pytest.raises(wtforms.validators.ValidationError):
            form._lookup_actor(fake_username)

        assert sentry_sdk.capture_message.calls == [
            pretend.call(
                "Connection error from ActiveState user lookup API (possibly offline)"
            )
        ]

    def test_lookup_actor_gql_error(self, monkeypatch):
        response = pretend.stub(
            status_code=200,
            raise_for_status=pretend.call_recorder(lambda: None),
            json=lambda: {"errors": ["some error"]},
            content=b"fake-content",
        )
        requests = pretend.stub(
            post=pretend.call_recorder(lambda o, **kw: response), HTTPError=HTTPError
        )
        monkeypatch.setattr(activestate, "requests", requests)

        sentry_sdk = pretend.stub(capture_message=pretend.call_recorder(lambda s: None))
        monkeypatch.setattr(activestate, "sentry_sdk", sentry_sdk)

        form = activestate.ActiveStatePublisherForm()
        with pytest.raises(wtforms.validators.ValidationError):
            form._lookup_actor(fake_username)

        assert requests.post.calls == [
            pretend.call(
                "https://platform.activestate.com/graphql/v1/graphql",
                json={
                    "query": "query($username: String) {users(where: {username: {_eq: $username}}) {user_id}}",  # noqa
                    "variables": {"username": fake_username},
                },
                timeout=5,
            )
        ]
        assert sentry_sdk.capture_message.calls == [
            pretend.call(
                "Unexpected error from ActiveState user lookup: ['some error']"
            )
        ]

    def test_lookup_actor_gql_no_data(self, monkeypatch):
        response = pretend.stub(
            status_code=200,
            raise_for_status=pretend.call_recorder(lambda: None),
            json=lambda: {"data": {"users": []}},
        )
        requests = pretend.stub(
            post=pretend.call_recorder(lambda o, **kw: response), HTTPError=HTTPError
        )
        monkeypatch.setattr(activestate, "requests", requests)

        form = activestate.ActiveStatePublisherForm()
        with pytest.raises(wtforms.validators.ValidationError):
            form._lookup_actor(fake_username)

        assert requests.post.calls == [
            pretend.call(
                "https://platform.activestate.com/graphql/v1/graphql",
                json={
                    "query": "query($username: String) {users(where: {username: {_eq: $username}}) {user_id}}",  # noqa
                    "variables": {"username": fake_username},
                },
                timeout=5,
            )
        ]

    # gql not found, ie. empty list of users returned

    def test_lookup_actor_succeeds(self, monkeypatch):
        response = pretend.stub(
            status_code=200,
            raise_for_status=pretend.call_recorder(lambda: None),
            json=lambda: fake_gql_user_response,
        )
        requests = pretend.stub(
            post=pretend.call_recorder(lambda o, **kw: response), HTTPError=HTTPError
        )
        monkeypatch.setattr(activestate, "requests", requests)

        form = activestate.ActiveStatePublisherForm()
        info = form._lookup_actor(fake_username)

        assert requests.post.calls == [
            pretend.call(
                "https://platform.activestate.com/graphql/v1/graphql",
                json={
                    "query": "query($username: String) {users(where: {username: {_eq: $username}}) {user_id}}",  # noqa
                    "variables": {"username": fake_username},
                },
                timeout=5,
            )
        ]
        assert response.raise_for_status.calls == [pretend.call()]
        assert info == fake_user_info

    # _lookup_organization
    def test_lookup_organization_404(self, monkeypatch):
        response = pretend.stub(
            status_code=404,
            raise_for_status=pretend.raiser(HTTPError),
            content=b"fake-content",
        )
        requests = pretend.stub(
            post=pretend.call_recorder(lambda o, **kw: response), HTTPError=HTTPError
        )

        monkeypatch.setattr(activestate, "requests", requests)

        form = activestate.ActiveStatePublisherForm()
        with pytest.raises(wtforms.validators.ValidationError):
            form._lookup_organization(fake_org_name)

        assert requests.post.calls == [
            pretend.call(
                "https://platform.activestate.com/graphql/v1/graphql",
                json={
                    "query": "query($orgname: String) {organizations(where: {display_name: {_eq: $orgname}}) {added}}",  # noqa
                    "variables": {"orgname": fake_org_name},
                },
                timeout=5,
            )
        ]

    def test_lookup_organization_other_http_error(self, monkeypatch):
        response = pretend.stub(
            # anything that isn't 404 or 403
            status_code=422,
            raise_for_status=pretend.raiser(HTTPError),
            content=b"fake-content",
        )
        requests = pretend.stub(
            post=pretend.call_recorder(lambda o, **kw: response),
            HTTPError=HTTPError,
        )
        monkeypatch.setattr(activestate, "requests", requests)

        sentry_sdk = pretend.stub(capture_message=pretend.call_recorder(lambda s: None))
        monkeypatch.setattr(activestate, "sentry_sdk", sentry_sdk)

        form = activestate.ActiveStatePublisherForm()
        with pytest.raises(wtforms.validators.ValidationError):
            form._lookup_organization(fake_org_name)

        assert requests.post.calls == [
            pretend.call(
                "https://platform.activestate.com/graphql/v1/graphql",
                json={
                    "query": "query($orgname: String) {organizations(where: {display_name: {_eq: $orgname}}) {added}}",  # noqa
                    "variables": {"orgname": fake_org_name},
                },
                timeout=5,
            )
        ]

        assert sentry_sdk.capture_message.calls == [
            pretend.call(
                "Unexpected error from ActiveState user lookup: "
                "response.content=b'fake-content'"
            )
        ]

    def test_lookup_organization_http_timeout(self, monkeypatch):
        requests = pretend.stub(
            post=pretend.raiser(Timeout),
            Timeout=Timeout,
            HTTPError=HTTPError,
            ConnectionError=ConnectionError,
        )
        monkeypatch.setattr(activestate, "requests", requests)

        sentry_sdk = pretend.stub(capture_message=pretend.call_recorder(lambda s: None))
        monkeypatch.setattr(activestate, "sentry_sdk", sentry_sdk)

        form = activestate.ActiveStatePublisherForm()
        with pytest.raises(wtforms.validators.ValidationError):
            form._lookup_organization(fake_org_name)

        assert sentry_sdk.capture_message.calls == [
            pretend.call("Timeout from ActiveState user lookup API (possibly offline)")
        ]

    def test_lookup_organization_connection_error(self, monkeypatch):
        requests = pretend.stub(
            post=pretend.raiser(ConnectionError),
            Timeout=Timeout,
            HTTPError=HTTPError,
            ConnectionError=ConnectionError,
        )
        monkeypatch.setattr(activestate, "requests", requests)

        sentry_sdk = pretend.stub(capture_message=pretend.call_recorder(lambda s: None))
        monkeypatch.setattr(activestate, "sentry_sdk", sentry_sdk)

        form = activestate.ActiveStatePublisherForm()
        with pytest.raises(wtforms.validators.ValidationError):
            form._lookup_organization(fake_org_name)

        assert sentry_sdk.capture_message.calls == [
            pretend.call(
                "Connection error from ActiveState user lookup API (possibly offline)"
            )
        ]

    def test_lookup_organization_gql_error(self, monkeypatch):
        response = pretend.stub(
            status_code=200,
            raise_for_status=pretend.call_recorder(lambda: None),
            json=lambda: {"errors": ["some error"]},
            content=b"fake-content",
        )
        requests = pretend.stub(
            post=pretend.call_recorder(lambda o, **kw: response), HTTPError=HTTPError
        )
        monkeypatch.setattr(activestate, "requests", requests)

        sentry_sdk = pretend.stub(capture_message=pretend.call_recorder(lambda s: None))
        monkeypatch.setattr(activestate, "sentry_sdk", sentry_sdk)

        form = activestate.ActiveStatePublisherForm()
        with pytest.raises(wtforms.validators.ValidationError):
            form._lookup_organization(fake_org_name)

        assert requests.post.calls == [
            pretend.call(
                "https://platform.activestate.com/graphql/v1/graphql",
                json={
                    "query": "query($orgname: String) {organizations(where: {display_name: {_eq: $orgname}}) {added}}",  # noqa
                    "variables": {"orgname": fake_org_name},
                },
                timeout=5,
            )
        ]
        assert sentry_sdk.capture_message.calls == [
            pretend.call(
                "Unexpected error from ActiveState user lookup: ['some error']"
            )
        ]

    def test_lookup_organization_gql_no_data(self, monkeypatch):
        response = pretend.stub(
            status_code=200,
            raise_for_status=pretend.call_recorder(lambda: None),
            json=lambda: {"data": {"organizations": []}},
        )
        requests = pretend.stub(
            post=pretend.call_recorder(lambda o, **kw: response), HTTPError=HTTPError
        )
        monkeypatch.setattr(activestate, "requests", requests)

        form = activestate.ActiveStatePublisherForm()
        with pytest.raises(wtforms.validators.ValidationError):
            form._lookup_organization(fake_org_name)

        assert requests.post.calls == [
            pretend.call(
                "https://platform.activestate.com/graphql/v1/graphql",
                json={
                    "query": "query($orgname: String) {organizations(where: {display_name: {_eq: $orgname}}) {added}}",  # noqa
                    "variables": {"orgname": fake_org_name},
                },
                timeout=5,
            )
        ]

    # gql not found, ie. empty list of users returned

    def test_lookup_organization_succeeds(self, monkeypatch):
        response = pretend.stub(
            status_code=200,
            raise_for_status=pretend.call_recorder(lambda: None),
            json=lambda: fake_gql_org_response,
        )
        requests = pretend.stub(
            post=pretend.call_recorder(lambda o, **kw: response), HTTPError=HTTPError
        )
        monkeypatch.setattr(activestate, "requests", requests)

        form = activestate.ActiveStatePublisherForm()
        form._lookup_organization(fake_org_name)

        assert requests.post.calls == [
            pretend.call(
                "https://platform.activestate.com/graphql/v1/graphql",
                json={
                    "query": "query($orgname: String) {organizations(where: {display_name: {_eq: $orgname}}) {added}}",  # noqa
                    "variables": {"orgname": fake_org_name},
                },
                timeout=5,
            )
        ]
        assert response.raise_for_status.calls == [pretend.call()]

    @pytest.mark.parametrize(
        "data",
        [
            {"organization": None, "project": "good", "actor": "good"},
            {"organization": "", "project": "good", "actor": "good"},
            {
                "organization": "invalid_characters@",
                "project": "good",
                "actor": "good",
            },
            {"project": None, "organization": "good", "actor": "good"},
            {"project": "", "organization": "good", "actor": "good"},
            {
                "project": "$invalid#characters",
                "organization": "good",
                "actor": "good",
            },
            {"actor": None, "project": "good", "organization": "good"},
            {"actor": "", "project": "good", "organization": "good"},
            {"actor": "$invalid#characters", "project": "good", "organization": "good"},
        ],
    )
    def test_validate_basic_invalid_fields(self, monkeypatch, data):
        form = activestate.ActiveStatePublisherForm(MultiDict(data))

        # We're testing only the basic validation here.
        monkeypatch.setattr(form, "_lookup_actor", lambda o: fake_user_info)
        monkeypatch.setattr(form, "_lookup_organization", lambda o: None)

        assert not form.validate()

    def test_validate_owner(self, monkeypatch):
        form = activestate.ActiveStatePublisherForm()

        monkeypatch.setattr(form, "_lookup_actor", lambda o: fake_user_info)

        field = pretend.stub(data=fake_username)
        form.validate_actor(field)

        assert form.actor_id == "some-user-id"
