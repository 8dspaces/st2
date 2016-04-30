# Licensed to the StackStorm, Inc ('StackStorm') under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import os

from keyczar.keys import AesKey
from oslo_config import cfg
import six

from st2common.exceptions.keyvalue import CryptoKeyNotSetupException
from st2common.log import logging
from st2common.util import isotime
from st2common.util import date as date_utils
from st2common.util.crypto import symmetric_encrypt, symmetric_decrypt
from st2common.models.api.base import BaseAPI
from st2common.models.db.keyvalue import KeyValuePairDB

LOG = logging.getLogger(__name__)


class KeyValuePairAPI(BaseAPI):
    crypto_setup = False
    model = KeyValuePairDB
    schema = {
        'type': 'object',
        'properties': {
            'id': {
                'type': 'string'
            },
            "uid": {
                "type": "string"
            },
            'name': {
                'type': 'string'
            },
            'description': {
                'type': 'string'
            },
            'value': {
                'type': 'string',
                'required': True
            },
            'secret': {
                'type': 'boolean',
                'required': False,
                'default': False
            },
            'encrypted': {
                'type': 'boolean',
                'required': False,
                'default': False
            },
            'expire_timestamp': {
                'type': 'string',
                'pattern': isotime.ISO8601_UTC_REGEX
            },
            # Note: Those values are only used for input
            # TODO: Improve
            'ttl': {
                'type': 'integer'
            }
        },
        'additionalProperties': False
    }

    @staticmethod
    def _setup_crypto():
        LOG.info('Checking if encryption is enabled for key-value store.')
        KeyValuePairAPI.is_encryption_enabled = cfg.CONF.keyvalue.enable_encryption
        LOG.debug('Encryption enabled? : %s', KeyValuePairAPI.is_encryption_enabled)
        if KeyValuePairAPI.is_encryption_enabled:
            KeyValuePairAPI.crypto_key_path = cfg.CONF.keyvalue.encryption_key_path
            LOG.info('Encryption enabled. Looking for key in path %s',
                     KeyValuePairAPI.crypto_key_path)
            if not os.path.exists(KeyValuePairAPI.crypto_key_path):
                msg = ('Encryption key file does not exist in path %s.' %
                       KeyValuePairAPI.crypto_key_path)
                LOG.exception(msg)
                LOG.info('All API requests will now send out BAD_REQUEST ' +
                         'if you ask to store secrets in key value store.')
                KeyValuePairAPI.crypto_key = None
            else:
                KeyValuePairAPI.crypto_key = KeyValuePairAPI._read_crypto_key(
                    KeyValuePairAPI.crypto_key_path
                )
        KeyValuePairAPI.crypto_setup = True

    @staticmethod
    def _read_crypto_key(key_path):
        with open(key_path) as key_file:
            key = AesKey.Read(key_file.read())
            return key

    @classmethod
    def from_model(cls, model, mask_secrets=True):
        if not KeyValuePairAPI.crypto_setup:
            KeyValuePairAPI._setup_crypto()

        doc = cls._from_model(model, mask_secrets=mask_secrets)

        if 'id' in doc:
            del doc['id']

        if model.expire_timestamp:
            doc['expire_timestamp'] = isotime.format(model.expire_timestamp, offset=False)

        encrypted = False
        if model.secret:
            encrypted = True

        if not mask_secrets and model.secret:
            doc['value'] = symmetric_decrypt(KeyValuePairAPI.crypto_key, model.value)
            encrypted = False

        doc['encrypted'] = encrypted
        attrs = {attr: value for attr, value in six.iteritems(doc) if value is not None}
        return cls(**attrs)

    @classmethod
    def to_model(cls, kvp):
        if not KeyValuePairAPI.crypto_setup:
            KeyValuePairAPI._setup_crypto()

        name = getattr(kvp, 'name', None)
        description = getattr(kvp, 'description', None)
        value = kvp.value
        secret = False

        if getattr(kvp, 'ttl', None):
            expire_timestamp = (date_utils.get_datetime_utc_now() +
                                datetime.timedelta(seconds=kvp.ttl))
        else:
            expire_timestamp = None

        if getattr(kvp, 'secret', False):
            if not KeyValuePairAPI.crypto_key:
                msg = ('Crypto key not found in %s. Unable to encrypt value for key %s.' %
                       (KeyValuePairAPI.crypto_key_path, name))
                raise CryptoKeyNotSetupException(msg)
            value = symmetric_encrypt(KeyValuePairAPI.crypto_key, value)
            secret = True

        model = cls.model(name=name, description=description, value=value,
                          secret=secret,
                          expire_timestamp=expire_timestamp)

        return model
