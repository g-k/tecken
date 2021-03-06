# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, you can obtain one at http://mozilla.org/MPL/2.0/.

import os
import requests

BASE_URL = os.environ.get('BASE_URL')
assert BASE_URL


def _request(payload, uri='/symbolicate/v4', **options):
    url = BASE_URL + uri
    return requests.post(url, json=payload, timeout=30, **options)


def test_basic_symbolication():
    crash_ping = {
        'version': 4,
        'memoryMap': [
            ['firefox.pdb', 'C617B8AF472444AD952D19A0CFD7C8F72'],
            ['wntdll.pdb', 'D74F79EB1F8D4A45ABCD2F476CCABACC2']
        ],
        'stacks': [
            [
                [0, 154348],
                [1, 65802]
            ]
        ]
    }
    response = _request(crash_ping)
    assert response.status_code == 200
    assert response.json() == {
        'symbolicatedStacks': [
            [
                'sandbox::TargetProcess::~TargetProcess() (in firefox.pdb)',
                'KiUserCallbackDispatcher (in wntdll.pdb)',
            ]
        ],
        'knownModules': [True, True]
    }

    # And it should be possible to do it via the root URI too
    second_response = _request(crash_ping, uri='/')
    assert response.status_code == 200
    assert response.json() == second_response.json()


def test_basic_symbolication_with_debug():
    crash_ping = {
        'version': 4,
        'memoryMap': [
            ['firefox.pdb', 'C617B8AF472444AD952D19A0CFD7C8F72'],
            ['wntdll.pdb', 'D74F79EB1F8D4A45ABCD2F476CCABACC2']
        ],
        'stacks': [
            [
                [0, 154348],
                [1, 65802]
            ]
        ],
    }
    response = _request(crash_ping, headers={
        'Debug': 'true'
    })
    assert response.status_code == 200
    debug = response.json()['debug']
    assert debug
    assert debug['cache_lookups']['count'] == 1
    assert debug['modules']['count'] == 2
    assert debug['stacks']['count'] == 2


def test_basic_symbolication_cached():
    crash_ping = {
        'version': 4,
        'memoryMap': [
            ['firefox.pdb', 'C617B8AF472444AD952D19A0CFD7C8F72'],
            ['wntdll.pdb', 'D74F79EB1F8D4A45ABCD2F476CCABACC2']
        ],
        'stacks': [
            [
                [0, 154348],
                [1, 65802]
            ]
        ],
    }
    response = _request(crash_ping)
    assert response.status_code == 200
    assert response.json()['knownModules'] == [True, True]
    response = _request(crash_ping, headers={
        'Debug': 'true'
    })
    assert response.status_code == 200
    assert response.json()['knownModules'] == [True, True]
    # The second time, the debug information should definitely
    # indicate that no downloads were necessary.
    assert response.json()['debug']['downloads']['count'] == 0
