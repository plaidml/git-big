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
import StringIO
import urlparse

import boto
import libcloud
import progressbar
from boto.gs.resumable_upload_handler import ResumableUploadHandler
from boto.s3.resumable_download_handler import ResumableDownloadHandler
from libcloud.storage.types import ObjectDoesNotExistError

from git_big.fix_progressbar import AdaptiveTransferSpeed

CHUNK_SIZE = 1024 * 1024
NUM_CB = -1


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
        AdaptiveTransferSpeed(),
    ]
    return progressbar.ProgressBar(widgets=widgets, max_value=size)


class Storage(object):
    def __init__(self, config):
        pass

    def has_object(self, obj_path):
        raise NotImplementedError()

    def delete_object(self, obj_path):
        raise NotImplementedError()

    def get_file(self, obj_path, file_path, tracker_path):
        raise NotImplementedError()

    def put_file(self, obj_path, file_path, tracker_path):
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
        parts = urlparse.urlparse(self.__config.url)
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
            self.bucket.get_object(obj_path)
            return True
        except ObjectDoesNotExistError:
            return False

    def delete_object(self, obj_path):
        try:
            obj = self.bucket.get_object(obj_path)
        except ObjectDoesNotExistError:
            return
        self.bucket.delete_object(obj)

    def get_file(self, obj_path, file_path, tracker_path):
        obj = self.bucket.get_object(obj_path)
        filename = os.path.basename(obj_path)
        with make_progress_bar(filename, obj.size) as pbar:
            stream = self.bucket.download_object_as_stream(
                obj, chunk_size=CHUNK_SIZE)
            with open(file_path, 'w') as file_:
                total_len = 0
                for chunk in stream:
                    file_.write(chunk)
                    total_len += len(chunk)
                    pbar.update(total_len)

    def put_file(self, obj_path, file_path, tracker_path):
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        with make_progress_bar(filename, file_size) as pbar:
            self.bucket.upload_object(file_path, obj_path)

    def get_string(self, obj_path):
        try:
            obj = self.bucket.get_object(obj_path)
            buf = StringIO.StringIO()
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
        stream = StringIO.StringIO(data)
        self.bucket.upload_object_via_stream(stream, obj_path, extra=extra)


class BotoStorage(Storage):
    def __init__(self, config):
        self.__uri = boto.storage_uri(config.url)
        self.__key = config.key
        self.__secret = config.secret
        self.__bucket = None

    @property
    def bucket(self):
        if not self.__bucket:
            self.__connect()
        return self.__bucket

    def __connect(self):
        self.__uri.connect(self.__key, self.__secret)
        self.__bucket = self.__uri.get_bucket()

    def has_object(self, obj_path):
        key = self.bucket.get_key(obj_path)
        return key is not None

    def delete_object(self, obj_path):
        self.bucket.delete_key(obj_path)

    def get_file(self, obj_path, file_path, tracker_path):
        key = self.bucket.get_key(obj_path)
        if key is None:
            return None

        handler = ResumableDownloadHandler(tracker_path)
        filename = os.path.basename(obj_path)

        with make_progress_bar(filename, key.size) as pbar:

            def callback(total_xfer, total_size):
                pbar.update(total_xfer)

            with open(file_path, 'ab') as file_:
                key.get_contents_to_file(
                    file_,
                    cb=callback,
                    num_cb=NUM_CB,
                    res_download_handler=handler)

    def put_file(self, obj_path, file_path, tracker_path):
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        with make_progress_bar(filename, file_size) as pbar:

            def callback(total_xfer, total_size):
                pbar.update(total_xfer)

            key = self.bucket.new_key(obj_path)
            if self.__uri.scheme == 'gs':
                handler = ResumableUploadHandler(tracker_path)
                key.set_contents_from_filename(
                    file_path,
                    cb=callback,
                    num_cb=NUM_CB,
                    res_upload_handler=handler)
            else:
                key.set_contents_from_filename(
                    file_path, cb=callback, num_cb=NUM_CB)

    def get_string(self, obj_path):
        key = self.bucket.get_key(obj_path)
        if key is None:
            return None
        data = key.get_contents_as_string()
        return StorageObject(data, key.metadata, key.last_modified)

    def put_string(self, obj_path, data, metadata={}):
        key = self.bucket.new_key(obj_path)
        key.metadata = metadata
        key.set_contents_from_string(data)


DRIVERS = {
    's3': BotoStorage,
    'gs': BotoStorage,
}


def get_driver(config):
    parts = urlparse.urlparse(config.url)
    driver = DRIVERS.get(parts.scheme)
    if driver:
        return driver(config)
    return LibcloudStorage(config)
