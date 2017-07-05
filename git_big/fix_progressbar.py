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

# This fix is needed until this PR is properly merged and available in the latest release:
# https://github.com/WoLpH/python-progressbar/pull/123

from __future__ import print_function

from progressbar.widgets import FormatWidgetMixin, TimeSensitiveWidgetBase, SamplesMixin
from progressbar import utils


class FileTransferSpeed(FormatWidgetMixin, TimeSensitiveWidgetBase):
    '''
    WidgetBase for showing the transfer speed (useful for file transfers).
    '''

    def __init__(self,
                 format='%(scaled)5.1f %(prefix)s%(unit)-s/s',
                 inverse_format='%(scaled)5.1f s/%(prefix)s%(unit)-s',
                 unit='B',
                 prefixes=('', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi', 'Yi'),
                 **kwargs):
        self.unit = unit
        self.prefixes = prefixes
        self.inverse_format = inverse_format
        FormatWidgetMixin.__init__(self, format=format, **kwargs)
        TimeSensitiveWidgetBase.__init__(self, **kwargs)

    def _speed(self, value, elapsed):
        speed = float(value) / elapsed
        return utils.scale_1024(speed, len(self.prefixes))

    def __call__(self, progress, data, value=None, total_seconds_elapsed=None):
        '''Updates the widget with the current SI prefixed speed.'''
        if value is None:
            value = data['value']

        if total_seconds_elapsed is None:
            elapsed = data['total_seconds_elapsed']
        else:
            elapsed = total_seconds_elapsed

        if value is not None and elapsed is not None \
                and elapsed > 2e-6 and value > 2e-6:  # =~ 0
            scaled, power = self._speed(value, elapsed)
        else:
            scaled = power = 0

        data['unit'] = self.unit
        if power == 0 and scaled < 0.1:
            if scaled > 0:
                scaled = 1 / scaled
            data['scaled'] = scaled
            data['prefix'] = self.prefixes[0]
            return FormatWidgetMixin.__call__(self, progress, data,
                                              self.inverse_format)
        else:
            data['scaled'] = scaled
            data['prefix'] = self.prefixes[power]
            return FormatWidgetMixin.__call__(self, progress, data)


class AdaptiveTransferSpeed(FileTransferSpeed, SamplesMixin):
    '''WidgetBase for showing the transfer speed, based on the last X samples
    '''

    def __init__(self, **kwargs):
        FileTransferSpeed.__init__(self, **kwargs)
        SamplesMixin.__init__(self, **kwargs)

    def __call__(self, progress, data):
        times, values = SamplesMixin.__call__(self, progress, data)
        if len(times) <= 1:
            # No samples so just return the normal transfer speed calculation
            value = None
            elapsed = None
        else:
            value = values[-1] - values[0]
            elapsed = utils.timedelta_to_seconds(times[-1] - times[0])

        return FileTransferSpeed.__call__(self, progress, data, value, elapsed)
