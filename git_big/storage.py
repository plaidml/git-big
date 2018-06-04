# Copyright (c) 2017 Vertex.AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function

import os

import boto3
import botocore
import libcloud
import progressbar
from libcloud.storage.types import ObjectDoesNotExistError
from six import BytesIO

from six.moves.urllib.parse import urlparse

CHUNK_SIZE = 1024 * 1024


def make_progress_bar(name, size):
    widgets = [
        '%s: ' % name[:8],
        progressbar.Percentage(),
        ' ',
        progressbar.Bar(),
        ' ',
        progressbar.AdaptiveETA(),
        ' ',
        progressbar.DataSize(),
        ' ',
        progressbar.AdaptiveTransferSpeed(),
    ]
    return progressbar.ProgressBar(widgets=widgets, max_value=size)


class Storage(object):
    def __init__(self, config):
        pass

    def has_object(self, obj_path):
        raise NotImplementedError()

    def delete_object(self, obj_path):
        raise NotImplementedError()

    def get_file(self, obj_path, file_path):
        raise NotImplementedError()

    def put_file(self, obj_path, file_path):
        raise NotImplementedError()

    def get_string(self, obj_path):
        raise NotImplementedError()

    def put_string(self, obj_path, data, metadata={}):
        raise NotImplementedError()


class StorageObject(object):
    def __init__(self, data, metadata, last_modified):
        self.data = data
        self.metadata = metadata
        self.last_modified = last_modified


class LibcloudStorage(Storage):
    def __init__(self, config):
        self.__config = config
        self.__bucket = None

    def __connect(self):
        parts = urlparse(self.__config.url)
        driver = libcloud.get_driver(libcloud.DriverType.STORAGE, parts.scheme)
        service = driver(self.__config.key, self.__config.secret)
        self.__bucket = service.get_container(parts.hostname)

    @property
    def bucket(self):
        if not self.__bucket:
            self.__connect()
        return self.__bucket

    def has_object(self, obj_path):
        try:
            obj = self.bucket.get_object(obj_path)
            return obj.size
        except ObjectDoesNotExistError:
            return None

    def delete_object(self, obj_path):
        try:
            obj = self.bucket.get_object(obj_path)
        except ObjectDoesNotExistError:
            return
        self.bucket.delete_object(obj)

    def get_file(self, obj_path, file_path):
        obj = self.bucket.get_object(obj_path)
        filename = os.path.basename(obj_path)
        with make_progress_bar(filename, obj.size) as pbar:
            stream = self.bucket.download_object_as_stream(
                obj, chunk_size=CHUNK_SIZE)
            with open(file_path, 'wb') as file_:
                total_len = 0
                for chunk in stream:
                    file_.write(chunk)
                    total_len += len(chunk)
                    pbar.update(total_len)

    def put_file(self, obj_path, file_path):
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        with make_progress_bar(filename, file_size) as pbar:
            self.bucket.upload_object(file_path, obj_path)

    def get_string(self, obj_path):
        try:
            obj = self.bucket.get_object(obj_path)
            buf = BytesIO()
            stream = obj.as_stream()
            for chunk in stream:
                buf.write(chunk)
            data = buf.getvalue()
            return StorageObject(data, obj.extra,
                                 obj.meta_data['last_modified'])
        except ObjectDoesNotExistError:
            return None

    def put_string(self, obj_path, data, metadata={}):
        extra = {'meta_data': metadata}
        stream = BytesIO(data.encode())
        self.bucket.upload_object_via_stream(stream, obj_path, extra=extra)


class BotoProgress(object):
    def __init__(self, pbar):
        self.pbar = pbar
        self.total = 0

    def __call__(self, bytes_amount):
        self.total += bytes_amount
        self.pbar.update(self.total)


class BotoStorage(Storage):
    def __init__(self, config):
        session = boto3.session.Session(
            aws_access_key_id=config.key,
            aws_secret_access_key=config.secret,
        )
        parts = urlparse(config.url)
        bucket_name = parts.hostname
        if parts.scheme == 'gs':
            s3 = session.resource(
                's3',
                endpoint_url='https://storage.googleapis.com',
                config=botocore.client.Config(signature_version='s3v4'))
        elif parts.scheme == 's3+http':
            s3 = session.resource(
                's3', endpoint_url='http://{}'.format(parts.netloc))
            bucket_name = parts.path[1:]  # skip leading '/'
        else:
            s3 = session.resource('s3')
        self.__bucket = s3.Bucket(bucket_name)

    @property
    def bucket(self):
        return self.__bucket

    def has_object(self, obj_path):
        try:
            obj = self.bucket.Object(obj_path)
            return obj.content_length
        except botocore.exceptions.ClientError as ex:
            if ex.response['Error']['Code'] == '404':
                return None
            raise

    def delete_object(self, obj_path):
        self.bucket.delete_objects(Delete={'Objects': [{'Key': obj_path}]})

    def get_file(self, obj_path, file_path):
        filename = os.path.basename(obj_path)
        obj = self.bucket.Object(obj_path)
        with make_progress_bar(filename, obj.content_length) as pbar:
            obj.download_file(file_path, Callback=BotoProgress(pbar))

    def put_file(self, obj_path, file_path):
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        with make_progress_bar(filename, file_size) as pbar:
            self.bucket.upload_file(
                file_path, obj_path, Callback=BotoProgress(pbar))

    def get_string(self, obj_path):
        obj = self.bucket.Object(obj_path)
        try:
            body = obj.get()['Body']
            data = body.read().decode('utf-8')
            return StorageObject(data, obj.metadata, obj.last_modified)
        except botocore.exceptions.ClientError as ex:
            if ex.response['Error']['Code'] == 'NoSuchKey':
                return None
            raise

    def put_string(self, obj_path, data, metadata={}):
        stream = BytesIO(data.encode())
        self.bucket.upload_fileobj(
            stream, obj_path, ExtraArgs={'Metadata': metadata})


DRIVERS = {
    'gs': BotoStorage,
    's3': BotoStorage,
    's3+http': BotoStorage,
}


def get_driver(config):
    parts = urlparse(config.url)
    driver = DRIVERS.get(parts.scheme)
    if driver:
        return driver(config)
    return LibcloudStorage(config)
