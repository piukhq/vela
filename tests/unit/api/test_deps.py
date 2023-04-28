import pytest

from fastapi import HTTPException
from pytest_mock import MockerFixture

from vela.api.deps import get_authorization_token, user_is_authorised


def test_get_authorization_token() -> None:
    # GIVEN
    expected_token = "blah123blah456blah"
    test_authorization = f"token {expected_token}"

    # WHEN
    token = get_authorization_token(authorization=test_authorization)

    # THEN
    assert token == expected_token


def test_get_authorization_token_raises_httpexception() -> None:
    # GIVEN
    expected_token = "blah123blah456blah"
    test_authorization = f"not_a_token {expected_token}"

    # WHEN
    with pytest.raises(HTTPException):
        get_authorization_token(authorization=test_authorization)

    # GIVEN
    test_authorization = ""

    # WHEN
    with pytest.raises(HTTPException):
        get_authorization_token(authorization=test_authorization)


def test_user_is_authorised_raises_httpexception(mocker: MockerFixture) -> None:
    # GIVEN
    test_token = "token BADTOKENBAD"
    from vela.api import deps

    spy = mocker.spy(deps, "get_authorization_token")

    # WHEN
    with pytest.raises(HTTPException):
        user_is_authorised(token=test_token)
        assert spy.call_count == 1
